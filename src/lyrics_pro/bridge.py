"""Version 1 NDJSON worker for the native app. Stdout is protocol-only."""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import argparse
import json
import os
from queue import Empty, Queue
import signal
import sys
from threading import Event, Thread
import time

from .artwork import read_artwork
from .music import MusicCancelled, MusicError, read_playback
from .lyric_session import LANGUAGES, LyricSession
from .playback_control import control_playback, valid_command


class Bridge:
    def __init__(self, emit, cancelled, commands, *, reader=read_playback, artwork_reader=read_artwork,
                 language="auto", lyrics=None, controller=control_playback):
        self.emit = emit
        self.cancelled = cancelled
        self.commands = commands
        self.reader = reader
        self.controller = controller
        self.last_control_id = 0
        self.completed_control_id = 0
        self.control_pending = None
        self.control_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="playback-control")
        self.artwork_reader = artwork_reader
        self.generation = 0
        self.key = None
        self.cache = OrderedDict()
        self.pending = None
        self.artwork_finished = False
        self.denied = False
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="artwork")
        self.lyrics = lyrics if lyrics is not None else LyricSession(cancelled, language=language)

    def send(self, kind, **payload):
        self.emit({"version": 1, "type": kind, "generation": self.generation,
                   "track": self.key, **payload})

    def tick(self):
        control_results = []
        if self.control_pending and self.control_pending[0].done():
            future, command_id = self.control_pending
            self.control_pending = None
            result = {"command_id": command_id, "ok": True}
            try:
                future.result()
            except MusicCancelled:
                raise
            except MusicError as error:
                result.update(ok=False, code=error.code, message=str(error))
            except Exception:
                result.update(ok=False, code="control_failed", message="Music could not complete the control.")
            control_results.append(result)
            self.completed_control_id = max(self.completed_control_id, command_id)
        try:
            while True:
                command = self.commands.get_nowait()
                if isinstance(command, dict):
                    if command["command"] == "playback_control":
                        command_id = command["command_id"]
                        if command_id <= self.last_control_id:
                            continue  # Never repeat a transport action, even after a timeout.
                        self.last_control_id = command_id
                        try:
                            if (command["generation"] != self.generation
                                    or tuple(command["track"]) != self.key):
                                raise MusicError("The song changed. Try the control again.", code="stale_track")
                            if self.control_pending:
                                raise MusicError("Music is still processing the previous control.", code="control_busy")
                            self.control_pending = (
                                self.control_pool.submit(self.controller, command, cancelled=self.cancelled), command_id)
                        except MusicError as error:
                            control_results.append({"command_id": command_id, "ok": False,
                                                    "code": error.code, "message": str(error)})
                            self.completed_control_id = max(self.completed_control_id, command_id)
                        continue
                    self.lyrics.configure(command["language"], command["request_id"],
                                          retry=command["command"] == "retry_lyrics",
                                          generation=command.get("generation"),
                                          **({"choice_id": command["song_id"], "choice_request_id": command["choice_request_id"]}
                                             if command["command"] == "choose_recording" else
                                             {"forget": True} if command["command"] == "forget_recording" else {}))
                    continue
                if command == "shutdown":
                    self.cancelled.set()
                    return
                if command == "retry":
                    self.denied = False
                    self.cache.pop(self.key, None)
                    self.artwork_finished = False
        except Empty:
            pass
        if self.denied:
            for result in control_results:
                self.send("control_result", **result)
            return
        # Capture before the read: a command may finish while the snapshot is sampled.
        # Such a snapshot must not confirm an optimistic action in the native UI.
        sampled_control_id = self.completed_control_id
        try:
            track = self.reader(cancelled=self.cancelled, permission_owner="Lyrics Pro")
        except MusicError as error:
            # Invalidate all in-flight work and remove stale metadata on disconnect.
            if self.key is not None:
                self.generation += 1
                self.key = None
            self.artwork_finished = False
            self.lyrics.update_track(None, self.generation)
            self.denied = error.code == "permission_denied"
            self.send("status", code=error.code, message=str(error))
            for result in control_results:
                self.send("control_result", **result)
            return
        if track.key != self.key:
            self.key = track.key
            self.generation += 1
            self.artwork_finished = False
        self.send("playback", playback=asdict(track), completed_control_id=sampled_control_id)
        for result in control_results:
            self.send("control_result", **result)
        self.lyrics.update_track(track, self.generation)
        self.lyrics.tick(lambda payload: self.send("lyrics", lyric=payload))

        if self.pending and self.pending[0].done():
            future, generation, key = self.pending
            self.pending = None
            try:
                artwork = future.result()
            except MusicCancelled:
                raise
            except Exception:
                artwork = None
            if generation == self.generation and key == self.key:
                # Bounded, session-only cache; never display a stale cover.
                self.cache[key] = artwork
                while len(self.cache) > 8:
                    self.cache.popitem(last=False)
        if self.key and not self.artwork_finished:
            if self.key in self.cache:
                artwork = self.cache[self.key]
                self.cache.move_to_end(self.key)
                self.send("artwork", image=artwork)
                self.artwork_finished = True
            elif self.pending is None:
                self.pending = (self.pool.submit(self.artwork_reader, track, self.cancelled),
                                self.generation, self.key)

    def close(self):
        self.cancelled.set()
        self.control_pool.shutdown(wait=True, cancel_futures=True)
        self.lyrics.close()
        self.pool.shutdown(wait=True, cancel_futures=True)


def read_commands(stream, commands, cancelled):
    try:
        while not cancelled.is_set():
            line = stream.readline(65537)
            if not line:
                return
            if len(line) > 65536:
                return
            try:
                message = json.loads(line)
                if message.get("version") != 1:
                    continue
                if message.get("command") == "playback_control":
                    if valid_command(message):
                        commands.put(message)
                elif message.get("command") in {"language", "retry_lyrics", "choose_recording", "forget_recording"}:
                    if (message.get("language") in LANGUAGES
                            and type(message.get("request_id")) is int and message["request_id"] >= 0
                            and (message["command"] == "language" or type(message.get("generation")) is int)
                            and (message["command"] != "choose_recording" or
                                 (type(message.get("song_id")) is int and message["song_id"] > 0
                                  and type(message.get("choice_request_id")) is int and message["choice_request_id"] >= 0))):
                        commands.put(message)
                elif message.get("command") in {"retry", "shutdown"}:
                    if message["command"] == "shutdown":
                        return
                    commands.put(message["command"])
            except (ValueError, AttributeError, TypeError):
                continue
    finally:
        # Parent closes stdin or exits: stop even while a script is in flight.
        cancelled.set()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=sorted(LANGUAGES), default="auto")
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
            cancelled.wait(max(0, 0.5 - (time.monotonic() - started)))
    except (MusicCancelled, BrokenPipeError):
        pass
    finally:
        worker.close()


if __name__ == "__main__":
    main()
