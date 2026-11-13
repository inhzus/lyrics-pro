import argparse
from concurrent.futures import ThreadPoolExecutor
import re
import sys
from threading import Event
import time

from .follow import Follower
from .lyrics import LyricsProvider
from .models import LookupCancelled, LookupFailure
from .music import MusicError, read_playback
from .pronunciation import Romanizer, choose_language, supplied_annotation
from .curated import curated_lyrics
from .lyrics_cache import LyricsCache
from .diagnostics import setup, event


def safe_text(value: str) -> str:
    # Lyrics/metadata are untrusted terminal text, including escape sequences.
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", value)


def emit(message=""):
    print(safe_text(message), flush=True)


def show_line(line):
    if line.time is None:
        stamp = ""
    else:
        stamp = f"[{int(line.time) // 60:02}:{line.time % 60:05.2f}] "
    emit(stamp + (line.text or "♪"))
    if line.pronunciation and line.pronunciation != line.text:
        emit("    " + line.pronunciation)


def run(language: str):
    cancelled = Event()
    provider = LyricsProvider(cancelled=cancelled)
    romanizer = Romanizer()
    disk_cache = LyricsCache()
    cache = {}
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lyrics")
    current_key, follower, pending = None, None, None
    generation = 0
    notice = None
    attempts, retry_at, finished = 0, 0, False

    def load(track):
        key = disk_cache.key(track)
        lyrics = curated_lyrics(track, cancelled=cancelled) or disk_cache.get(key)
        if lyrics is None:
            lyrics = provider.lookup(track)
            if lyrics and not cancelled.is_set():
                disk_cache.put(key, lyrics)
        if not lyrics:
            return None
        selected, _ = choose_language(track.artist, language, lyrics)
        supplied = supplied_annotation(lyrics, selected)
        if supplied is not None:
            return supplied
        annotated = disk_cache.annotated(lyrics, selected)
        if annotated is None:
            annotated = romanizer.annotate(lyrics, selected)
            if not cancelled.is_set():
                disk_cache.put_annotation(lyrics, selected, annotated)
        return annotated

    emit("Lyrics Pro — following Music. Ctrl-C to exit; no AI services are used.")
    try:
        while True:
            started = time.monotonic()
            try:
                playback = read_playback()
            except MusicError as exc:
                if str(exc) != notice:
                    emit(str(exc))
                    notice = str(exc)
                time.sleep(1)
                continue
            if playback.key != current_key:
                current_key = playback.key
                generation += 1
                follower = None
                attempts, retry_at, finished = 0, 0, False
                if current_key:
                    selected, reason = choose_language(playback.artist, language)
                    emit()
                    emit(f"{playback.title} — {playback.artist} | {playback.album} | {playback.duration:.1f}s")
                    emit(f"Pronunciation: {selected or 'original lyrics only'} ({reason}).")
                    emit("Looking up lyrics…")
            if not current_key:
                message = "Music is closed. Open it and play a song." if playback.state == "closed" else "Music is stopped. Waiting for a song."
                if notice != message:
                    emit(message)
                    notice = message
            elif notice != playback.state:
                emit(f"Music: {playback.state}")
                notice = playback.state

            # Do not queue stale tracks: finish the bounded request, then load
            # whichever track is current. The generation also handles A→B→A.
            if pending and pending[0].done():
                future, task_generation = pending
                pending = None
                if task_generation == generation and current_key:
                    try:
                        cache[current_key] = future.result()
                    except LookupCancelled:
                        return
                    except LookupFailure as exc:
                        emit(str(exc))
                        if exc.retryable and attempts < 3:
                            retry_at = time.monotonic() + 2 ** attempts
                            emit("Will retry lyrics shortly.")
                        else:
                            finished = True
                            emit("Lyrics unavailable for this track. Waiting for the next song.")
                    except Exception as exc:
                        finished = True
                        emit(f"Could not prepare lyrics: {type(exc).__name__}: {exc}")

            if current_key and not finished:
                if current_key in cache:
                    lyrics = cache[current_key]
                    finished = True
                    if lyrics is None:
                        emit("No matching lyrics within ±2 seconds. Waiting for the next song.")
                    elif lyrics.instrumental:
                        emit(f"Marked instrumental by {lyrics.source}.")
                    else:
                        emit(f"Source: {lyrics.source}")
                        if lyrics.proofread:
                            emit(f"Proofread: {lyrics.proofread.attribution}")
                            selected, reason = choose_language(playback.artist, language, lyrics)
                            emit(f"Pronunciation: {selected or 'original lyrics only'} ({reason}).")
                        if not lyrics.synced:
                            emit("Unsynchronized lyrics — printing the whole song once.")
                        follower = Follower(lyrics)
                elif pending is None and time.monotonic() >= retry_at:
                    attempts += 1
                    pending = pool.submit(load, playback), generation
            if follower and current_key:
                for line in follower.update(playback.position):
                    show_line(line)
            time.sleep(max(0, 0.5 - (time.monotonic() - started)))
    except KeyboardInterrupt:
        emit("Exiting.")
    finally:
        cancelled.set()
        pool.shutdown(wait=True, cancel_futures=True)


def main():
    setup()
    event("cli_start")
    parser = argparse.ArgumentParser(description="Follow macOS Music with local Jyutping or Taiwanese Hokkien pronunciation.")
    parser.add_argument("--language", choices=("cantonese", "hokkien", "original"), default="cantonese")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("This prototype requires macOS and the Music app.")
    try:
        run(args.language)
    except BrokenPipeError:
        pass
    finally:
        event("cli_stop")
