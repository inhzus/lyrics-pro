"""NDJSON worker for the native app (docs/protocol.md). Stdout is protocol-only."""

from collections import OrderedDict
from dataclasses import asdict
from functools import partial
import argparse
import json
import os
from queue import Empty, Queue
import signal
import sys
from threading import Event, Thread
import time

from .artwork import read_artwork
from .diagnostics import event
from .jobs import JobSlot
from .lyric_session import LANGUAGES, LyricSession
from .music import MusicCancelled, MusicError, read_playback
from .playback_control import control_playback
from .protocol import (
    MAX_COMMAND_BYTES, ChooseRecording, ClearData, ForgetRecording, GetDataStats, ListRecordings,
    PlaybackControl, RetryLyrics, SetLanguage, SetSongLanguage, Shutdown, event_frame, parse_command,
)


POLL_SECONDS = 0.5


class ArtworkLoader:
    """Fetch one cover per track change; keep a small session-only cache."""

    CACHE_LIMIT = 8
    MISSING_SECONDS = 60  # Missing covers are rechecked on a later visit.

    def __init__(self, reader, cancelled):
        self.reader = reader
        self.slot = JobSlot("artwork", cancelled)
        self.cancelled = cancelled
        self.cache = OrderedDict()  # track key -> (image or None, expiry)
        self.revision = 0
        self.finished = False

    def reset(self, key=None, *, invalidate=False):
        self.revision += 1
        self.slot.cancel()
        if invalidate:
            self.cache.pop(key, None)
        self.finished = False

    def has_image(self, key) -> bool:
        return bool(self.cache.get(key, (None, 0))[0])

    def tick(self, generation, key, track, send):
        if job := self.slot.take_done():
            try:
                artwork = job.future.result()
            except MusicCancelled:
                if self.cancelled.is_set():
                    raise
                artwork = None
            except Exception as exc:
                event("artwork_failure", category=type(exc).__name__)
                artwork = None
            # Bounded, session-only cache; never display a stale cover.
            if job.current((generation, key, self.revision)):
                self.cache[key] = (artwork, float("inf") if artwork else time.monotonic() + self.MISSING_SECONDS)
                while len(self.cache) > self.CACHE_LIMIT:
                    self.cache.popitem(last=False)
        if not key or self.finished:
            return
        if key in self.cache and self.cache[key][1] <= time.monotonic():
            self.cache.pop(key)
        if key in self.cache:
            self.cache.move_to_end(key)
            send(self.cache[key][0])
            self.finished = True
        elif not self.slot.busy:
            self.slot.start("artwork", (generation, key, self.revision), partial(self.reader, track))


class ControlRunner:
    """Run playback controls one at a time; never repeat or retry one."""

    def __init__(self, controller, cancelled):
        self.controller = controller
        self.slot = JobSlot("playback-control", cancelled)
        self.last_id = 0
        self.completed_id = 0  # Highest control that has finished, successfully or not.
        self.results = []

    def _finish(self, command_id, error=None):
        result = {"command_id": command_id, "ok": error is None}
        if error is not None:
            result.update(code=error.code, message=str(error))
        self.results.append(result)
        self.completed_id = max(self.completed_id, command_id)

    def collect(self):
        if not (job := self.slot.take_done()):
            return
        error = None
        try:
            job.future.result()
        except MusicCancelled:
            raise
        except MusicError as exc:
            error = exc
        except Exception:
            error = MusicError("Music could not complete the control.", code="control_failed")
        event("control_result", command_id=job.payload, ok=error is None, code=error.code if error else "")
        self._finish(job.payload, error)

    def submit(self, command: PlaybackControl, generation, key):
        if command.command_id <= self.last_id:
            return  # Never repeat a transport action, even after a timeout.
        self.last_id = command.command_id
        if command.generation != generation or command.track != key:
            self._finish(command.command_id, MusicError("The song changed. Try the control again.", code="stale_track"))
        elif self.slot.busy:
            self._finish(command.command_id,
                         MusicError("Music is still processing the previous control.", code="control_busy"))
        else:
            self.slot.start("control", None, lambda token: self.controller(command, cancelled=token),
                            payload=command.command_id)

    def take_results(self):
        results, self.results = self.results, []
        return results


class Bridge:
    def __init__(self, emit, cancelled, commands, *, reader=read_playback, artwork_reader=read_artwork,
                 language="cantonese", lyrics=None, controller=control_playback):
        self.emit = emit
        self.cancelled = cancelled
        self.commands = commands
        self.reader = reader
        self.generation = 0
        self.key = None
        self.denied = False
        self.last_diagnostic_error = None
        self.artwork = ArtworkLoader(artwork_reader, cancelled)
        self.controls = ControlRunner(controller, cancelled)
        self.lyrics = lyrics if lyrics is not None else LyricSession(cancelled, language=language)

    def send(self, kind, payload=None):
        self.emit(event_frame(kind, self.generation, self.key, payload))

    def send_control_results(self):
        for result in self.controls.take_results():
            self.send("control_result", result)

    def lyric_command(self, command):
        # Only set_language changes the global language; other intents keep it.
        language = self.lyrics.language
        match command:
            case SetLanguage():
                self.lyrics.set_language(command.language, command.request_id)
            case SetSongLanguage():
                self.lyrics.set_song_language(language, command.request_id, command.song_language,
                                              generation=command.generation, track_identity=command.track)
            case RetryLyrics():
                if command.generation != self.generation:
                    return
                if (command.request_id > self.lyrics.request_id
                        and (command.retry_artwork or not self.artwork.has_image(self.key))):
                    self.artwork.reset(self.key, invalidate=True)
                self.lyrics.retry(language, command.request_id, generation=command.generation)
            case ChooseRecording():
                self.lyrics.choose_recording(language, command.request_id, command.recording_id,
                                             generation=command.generation,
                                             choice_request_id=command.choice_request_id)
            case ListRecordings():
                self.lyrics.list_recordings(language, command.request_id, generation=command.generation)
            case ForgetRecording():
                self.lyrics.forget_recording(language, command.request_id, generation=command.generation)

    def drain_commands(self):
        while True:
            try:
                command = self.commands.get_nowait()
            except Empty:
                return
            if isinstance(command, PlaybackControl):
                self.controls.submit(command, self.generation, self.key)
            elif isinstance(command, GetDataStats):
                self.lyrics.request_data_stats()
            elif isinstance(command, ClearData):
                self.lyrics.clear_data(command.targets)
            else:
                self.lyric_command(command)

    def tick(self):
        self.controls.collect()
        self.drain_commands()
        if not self.cancelled.is_set():
            self.lyrics.tick_storage(partial(self.send, "data_stats"))
        if self.denied:
            # Permission denial stops polling until the app restarts the worker.
            self.send_control_results()
            return
        # Capture before the read: a command may finish while the snapshot is sampled.
        # Such a snapshot must not confirm an optimistic action in the native UI.
        sampled_control_id = self.controls.completed_id
        try:
            track = self.reader(cancelled=self.cancelled, permission_owner="Lyrics Pro")
        except MusicError as error:
            if self.cancelled.is_set():
                return  # Shutting down: a failed final poll says nothing about Music.
            self.disconnected(error)
            self.send_control_results()
            return
        self.last_diagnostic_error = None
        if track.key != self.key:
            self.key = track.key
            self.generation += 1
            self.artwork.reset()
            event("track_changed", title=track.title, artist=track.artist, album=track.album,
                  duration=track.duration)
        self.send("playback", {"snapshot": asdict(track), "completed_control_id": sampled_control_id})
        self.send_control_results()
        self.lyrics.update_track(track, self.generation)
        self.lyrics.tick(partial(self.send, "lyrics"), partial(self.send, "recordings"))
        self.artwork.tick(self.generation, self.key, track, lambda image: self.send("artwork", {"image": image}))

    def disconnected(self, error):
        diagnostic = (error.code, str(error))
        if diagnostic != self.last_diagnostic_error:
            event("music_error", code=error.code, error=str(error))
            self.last_diagnostic_error = diagnostic
        # Invalidate all in-flight work and remove stale metadata on disconnect.
        if self.key is not None:
            self.generation += 1
            self.key = None
        self.artwork.reset()
        self.lyrics.update_track(None, self.generation)
        self.denied = error.code == "permission_denied"
        self.send("status", {"code": error.code, "message": str(error)})

    def close(self):
        self.cancelled.set()
        self.artwork.slot.cancel()
        self.controls.slot.shutdown()
        self.lyrics.close()
        self.artwork.slot.shutdown()


def read_commands(stream, commands, cancelled):
    try:
        while not cancelled.is_set():
            line = stream.readline(MAX_COMMAND_BYTES + 1)
            if not line or len(line) > MAX_COMMAND_BYTES:
                return
            try:
                command = parse_command(json.loads(line))
            except ValueError:
                continue
            if isinstance(command, Shutdown):
                return
            if command is not None:
                commands.put(command)
    finally:
        # Parent closes stdin or exits: stop even while a script is in flight.
        cancelled.set()


def main():
    from .diagnostics import setup
    setup(bridge=True)
    event("worker_start")
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=sorted(LANGUAGES), default="cantonese")
    args = parser.parse_args()
    os.setpgrp()  # Parent can terminate this worker and its script children together.
    cancelled, commands = Event(), Queue()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: cancelled.set())

    def emit(message):
        print(json.dumps(message, ensure_ascii=False, allow_nan=False), flush=True)

    worker = Bridge(emit, cancelled, commands, language=args.language)
    Thread(target=read_commands, args=(sys.stdin, commands, cancelled), daemon=True).start()
    try:
        worker.send("ready")
        while not cancelled.is_set():
            started = time.monotonic()
            worker.tick()
            cancelled.wait(max(0, POLL_SECONDS - (time.monotonic() - started)))
    except (MusicCancelled, BrokenPipeError):
        pass
    finally:
        worker.close()
        event("worker_stop")


if __name__ == "__main__":
    main()
