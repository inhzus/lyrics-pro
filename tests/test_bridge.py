from concurrent.futures import Future
import io
import json
import os
from pathlib import Path
from queue import Queue
import signal
import subprocess
import sys
from threading import Event
from unittest.mock import patch

import pytest

from lyrics_pro.artwork import ARTWORK_SCRIPT, MAX_ARTWORK_BYTES, read_local_artwork
from lyrics_pro.bridge import Bridge, read_commands
from lyrics_pro.lyric_session import LyricSession
from lyrics_pro.models import Playback
from lyrics_pro.music import MusicCancelled, MusicError, read_playback, run_script


A = Playback("playing", "A", "Artist", "Album", 200, 12)
B = Playback("paused", "B", "Artist", "Album", 210, 25)


@pytest.fixture
def bridge():
    events, current = [], [A]

    def reader(**kwargs):
        assert kwargs["permission_owner"] == "Lyrics Pro"
        if isinstance(current[0], Exception):
            raise current[0]
        return current[0]

    cancelled = Event()
    worker = Bridge(lambda e: events.append(e) if e["type"] != "lyrics" else None,
                    cancelled, Queue(), reader=reader,
                    artwork_reader=lambda *_: "aW1hZ2U=",
                    lyrics=LyricSession(cancelled, fetch=lambda *_: None))
    yield worker, events, current
    worker.close()


def test_live_updates_pause_seek_and_clear_on_stop(bridge):
    worker, events, current = bridge
    worker.tick()
    worker.pending[0].result(timeout=1)
    worker.tick()
    assert events[-1]["type"] == "artwork"
    generation = worker.generation
    current[0] = Playback("paused", "A", "Artist", "Album", 200, 100)
    worker.tick()
    assert events[-1]["playback"]["position"] == 100
    assert events[-1]["generation"] == generation
    current[0] = Playback("stopped")
    worker.tick()
    assert events[-1]["track"] is None
    assert events[-1]["generation"] > generation


def test_old_artwork_is_rejected_even_after_a_b_a(bridge):
    worker, events, current = bridge
    # Keep the initial A request pending across the entire A -> B -> A sequence.
    pending = Future()
    with patch.object(worker.pool, "submit", return_value=pending):
        worker.tick()
    current[0] = B
    worker.tick()
    current[0] = A
    worker.tick()
    pending.set_result("c3RhbGU=")
    worker.tick()
    assert not any(event["type"] == "artwork" for event in events)
    worker.pending[0].result(timeout=1)
    worker.tick()
    assert events[-1]["image"] == "aW1hZ2U="


def test_permission_denial_waits_for_explicit_retry(bridge):
    worker, events, current = bridge
    worker.tick()
    current[0] = MusicError("Enable Music for Lyrics Pro", "permission_denied")
    worker.tick()
    assert events[-1]["code"] == "permission_denied"
    assert events[-1]["track"] is None
    count = len(events)
    current[0] = B
    worker.tick()
    assert len(events) == count
    worker.commands.put("retry")
    worker.tick()
    assert any(e.get("playback", {}).get("title") == "B" for e in events)


def test_transient_music_error_recovers_automatically(bridge):
    worker, events, current = bridge
    current[0] = MusicError("Unavailable")
    worker.tick()
    current[0] = A
    worker.tick()
    assert any(e["type"] == "playback" and e["playback"]["title"] == A.title for e in events)


def test_missing_artwork_is_cached_and_retry_invalidates_it(bridge):
    worker, events, _ = bridge
    calls = []

    def missing(*args):
        calls.append(args)
        return None

    worker.artwork_reader = missing
    worker.tick()
    worker.pending[0].result(timeout=1)
    worker.tick()
    worker.tick()
    assert len(calls) == 1
    assert any(e["type"] == "artwork" and e["image"] is None for e in events)
    worker.commands.put("retry")
    worker.tick()
    worker.pending[0].result(timeout=1)
    assert len(calls) == 2


@pytest.mark.parametrize("message", ["", '{"version":1,"command":"shutdown"}\n', "x" * 65537])
def test_parent_eof_shutdown_or_oversized_command_cancels(message):
    stopped, queue = Event(), Queue()
    read_commands(io.StringIO(message), queue, stopped)
    assert stopped.is_set()


def test_bad_commands_are_ignored_and_retry_is_queued():
    stopped, queue = Event(), Queue()
    read_commands(io.StringIO('garbage\n[]\n{"version":1,"command":"retry"}\n'), queue, stopped)
    assert queue.get_nowait() == "retry"
    assert queue.empty()


def test_cancelled_script_is_reaped():
    cancelled, children = Event(), []
    popen = subprocess.Popen

    def launch(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        cancelled.set()
        return child

    with patch("lyrics_pro.music.subprocess.Popen", side_effect=launch):
        with pytest.raises(MusicCancelled):
            run_script([sys.executable, "-c", "import time; time.sleep(30)"], timeout=4, cancelled=cancelled)
    assert children[0].poll() is not None


def test_script_timeout_is_bounded_and_reaped():
    children, popen = [], subprocess.Popen

    def launch(*args, **kwargs):
        child = popen(*args, **kwargs)
        children.append(child)
        return child

    with patch("lyrics_pro.music.subprocess.Popen", side_effect=launch):
        with pytest.raises(subprocess.TimeoutExpired):
            run_script([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.05, cancelled=Event())
    assert children[0].poll() is not None


@pytest.mark.parametrize("stop", ["eof", "signal"])
def test_worker_exits_when_parent_disconnects_or_terminates(stop):
    # Exercise the real worker lifecycle without contacting Music from a unit test.
    code = "from lyrics_pro import bridge; bridge.Bridge.tick = lambda self: self.cancelled.wait(.01); bridge.main()"
    child = subprocess.Popen([sys.executable, "-u", "-c", code], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        import select
        assert select.select([child.stdout], [], [], 3)[0]
        assert json.loads(child.stdout.readline())["type"] == "ready"
        if stop == "signal":
            child.send_signal(signal.SIGTERM)
        else:
            child.stdin.close()
            child.stdin = None
        child.wait(timeout=3)
        assert child.returncode == 0
        with pytest.raises(ProcessLookupError):
            os.killpg(child.pid, 0)
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate()


def test_artwork_metadata_is_passed_as_arguments_and_temp_file_is_removed():
    title = 'A "quoted" title\nwith a newline'
    track = Playback("playing", title, "Artist", "Album", 123)
    paths = []

    def script(args, **kwargs):
        assert args[2] == ARTWORK_SCRIPT
        assert args[3] == title
        assert title not in args[2]
        target = Path(args[-1])
        paths.append(target)
        target.write_bytes(b"image bytes")
        return subprocess.CompletedProcess(args, 0, "ok\n", "")

    with patch("lyrics_pro.artwork.run_script", side_effect=script), patch("lyrics_pro.artwork.valid_image", return_value=True):
        assert read_local_artwork(track, Event()) == "aW1hZ2UgYnl0ZXM="
    assert not paths[0].exists()


def test_oversized_artwork_uses_placeholder():
    def script(args, **kwargs):
        with open(args[-1], "wb") as output:
            output.truncate(MAX_ARTWORK_BYTES + 1)
        return subprocess.CompletedProcess(args, 0, "ok", "")
    with patch("lyrics_pro.artwork.run_script", side_effect=script):
        assert read_local_artwork(A, Event()) is None


def test_artwork_retry_cancels_and_discards_same_track_old_attempt(bridge):
    worker, events, _ = bridge
    future = Future()
    with patch.object(worker.pool, "submit", return_value=future):
        worker.tick()
    token = worker.pending[4]
    worker.commands.put(dict(command="retry_lyrics", generation=worker.generation, language="auto", request_id=1))
    worker.tick()
    assert token.is_set()
    future.set_result("stale")
    worker.tick()
    assert not any(e["type"] == "artwork" for e in events)
    worker.pending[0].result(timeout=1)
    worker.tick()
    assert events[-1]["image"] == "aW1hZ2U="


def test_missing_expiry_only_rechecks_on_revisit_and_success_cache_is_bounded(bridge):
    worker, _, current = bridge
    worker.artwork_reader = lambda *_: None
    with patch("lyrics_pro.bridge.time.monotonic", return_value=100):
        worker.tick()
        worker.pending[0].result(timeout=1)
        worker.tick()
    with patch("lyrics_pro.bridge.time.monotonic", return_value=200):
        worker.tick()
        assert worker.pending is None
        current[0] = B
        worker.tick()
        worker.pending[0].result(timeout=1)
        worker.tick()
        current[0] = A
        worker.tick()
        assert worker.pending is not None
        worker.pending[0].result(timeout=1)
        worker.tick()
    worker.artwork_reader = lambda *_: "cover"
    for n in range(10):
        current[0] = Playback("paused", str(n), "Artist", "Album", 200)
        worker.tick()
        worker.pending[0].result(timeout=1)
        worker.tick()
    assert len(worker.cache) == 8 and A.key not in worker.cache


def test_retry_preserves_success_unless_native_reports_invalid_image(bridge):
    worker, _, _ = bridge
    worker.tick()
    worker.pending[0].result(timeout=1)
    worker.tick()
    worker.commands.put(dict(command="retry_lyrics", generation=worker.generation, language="auto", request_id=1))
    worker.tick()
    assert worker.pending is None and worker.cache[A.key][0] == "aW1hZ2U="
    worker.commands.put(dict(command="retry_lyrics", generation=worker.generation - 1,
                             language="auto", request_id=2, retry_artwork=True))
    worker.tick()
    assert worker.pending is None
    worker.commands.put(dict(command="retry_lyrics", generation=worker.generation,
                             language="auto", request_id=2, retry_artwork=True))
    worker.tick()
    assert worker.pending is not None


@pytest.mark.parametrize("patch_data", [{"duration": float("nan")}, {"title": 123}, {"state": "invalid"}])
def test_invalid_playback_is_rejected(patch_data):
    data = A.__dict__ | patch_data
    with patch("lyrics_pro.music.subprocess.run", return_value=subprocess.CompletedProcess([], 0, json.dumps(data), "")):
        with pytest.raises(MusicError, match="invalid playback"):
            read_playback()
