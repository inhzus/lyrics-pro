from dataclasses import replace
import json
from queue import Queue
import subprocess
from threading import Event
from unittest.mock import patch

import pytest

from lyrics_pro.bridge import Bridge
from lyrics_pro.lyric_session import LyricSession
from lyrics_pro.models import Playback
from lyrics_pro.music import MusicError
from lyrics_pro.playback_control import control_playback
from lyrics_pro.protocol import PlaybackControl, track_object


A = Playback("paused", "A", "Artist", "Album", 200, 12)
B = Playback("playing", "B", "Artist", "Album", 210, 0)


def command(action="seek", **changes):
    return replace(PlaybackControl(1, 1, A.key, action, 90 if action == "seek" else None), **changes)


@pytest.mark.parametrize("action", ["play", "pause", "next", "previous", "seek"])
def test_commands_use_structured_arguments_and_bounded_script(action):
    title = 'A"; app.quit(); //'
    message = command(action, track=(title, *A.key[1:]))
    with patch("lyrics_pro.playback_control.run_script", return_value=subprocess.CompletedProcess([], 0, '{"ok":true}', "")) as run:
        control_playback(message)
    args = run.call_args.args[0]
    assert json.loads(args[-1]) == {"command_id": 1, "generation": 1, "track": track_object(message.track),
                                    "action": action, "position": message.position}
    assert title not in args[-2]
    assert run.call_args.kwargs["timeout"] == 4


@pytest.mark.parametrize("response,code", [
    ('{"ok":false,"code":"stale_track","message":"Changed"}', "stale_track"),
    ('{"ok":false,"code":"unseekable","message":"No duration"}', "unseekable"),
    ('{}', "control_failed"),
])
def test_script_errors_are_reported(response, code):
    with patch("lyrics_pro.playback_control.run_script", return_value=subprocess.CompletedProcess([], 0, response, "")):
        with pytest.raises(MusicError) as error:
            control_playback(command())
    assert error.value.code == code


def test_timeout_is_never_retried():
    with patch("lyrics_pro.playback_control.run_script", side_effect=subprocess.TimeoutExpired("osascript", 4)) as run:
        with pytest.raises(MusicError, match="Check playback"):
            control_playback(command("next"))
    assert run.call_count == 1


def test_bridge_refreshes_before_result_and_rejects_old_or_duplicate_controls():
    cancelled, commands, events, calls = Event(), Queue(), [], []
    current = [A]

    def controller(message, **kwargs):
        calls.append(message)
        current[0] = B

    worker = Bridge(events.append, cancelled, commands, reader=lambda **kw: current[0],
                    artwork_reader=lambda *a: None, controller=controller,
                    lyrics=LyricSession(cancelled, fetch=lambda *a: None))
    try:
        worker.tick()
        commands.put(command("next"))
        worker.tick()
        worker.controls.slot.job.future.result(timeout=1)
        worker.tick()
        result_index = next(i for i, e in enumerate(events) if e["type"] == "control_result")
        assert events[result_index - 1]["payload"]["snapshot"]["title"] == "B"
        assert events[result_index]["payload"]["ok"]
        commands.put(command("next"))
        worker.tick()
        assert len(calls) == 1
        commands.put(command(command_id=2))
        worker.tick()
        result = [e for e in events if e["type"] == "control_result"][-1]
        assert result["payload"]["code"] == "stale_track" and not result["payload"]["ok"]
        assert len(calls) == 1
    finally:
        worker.close()


def test_control_failure_keeps_current_track_and_does_not_retry():
    cancelled, commands, events = Event(), Queue(), []
    calls = []

    def controller(*a, **kw):
        calls.append(a)
        raise MusicError("Could not seek", code="control_failed")

    worker = Bridge(events.append, cancelled, commands, reader=lambda **kw: A,
                    artwork_reader=lambda *a: None, controller=controller,
                    lyrics=LyricSession(cancelled, fetch=lambda *a: None))
    try:
        worker.tick()
        commands.put(command())
        worker.tick()
        with pytest.raises(MusicError):
            worker.controls.slot.job.future.result(timeout=1)
        worker.tick()
        assert worker.key == A.key
        results = [e for e in events if e["type"] == "control_result"]
        assert len(results) == 1 and not results[0]["payload"]["ok"]
        assert len(calls) == 1
        assert not any(e["type"] == "status" for e in events)
    finally:
        worker.close()


def test_slow_control_does_not_block_polling_or_lyrics_and_shutdown_cancels_it():
    cancelled, commands, events, entered = Event(), Queue(), [], Event()
    reads = []

    def controller(*a, **kw):
        entered.set()
        assert kw["cancelled"].wait(2)

    def reader(**kw):
        reads.append(1)
        return A

    worker = Bridge(events.append, cancelled, commands, reader=reader,
                    artwork_reader=lambda *a: None, controller=controller,
                    lyrics=LyricSession(cancelled, fetch=lambda *a: None))
    try:
        worker.tick()
        commands.put(command())
        worker.tick()
        assert entered.wait(1)
        count = len(reads)
        for _ in range(3):
            worker.tick()
        assert len(reads) == count + 3
        assert not any(e["type"] == "control_result" for e in events)
        assert all(e["payload"]["completed_control_id"] == 0 for e in events if e["type"] == "playback")
        assert any(e["type"] == "lyrics" for e in events)
    finally:
        worker.close()
    assert cancelled.is_set() and worker.controls.slot.job.future.done()


def test_snapshot_started_before_completion_cannot_confirm_command():
    cancelled, release, entered = Event(), Event(), Event()
    commands, events = Queue(), []
    calls = []

    def controller(*a, **kw):
        entered.set()
        assert release.wait(1)

    def reader(**kw):
        if calls:
            assert entered.wait(1)
            release.set()
            worker.controls.slot.job.future.result(timeout=1)
        calls.append(1)
        return A

    worker = Bridge(events.append, cancelled, commands, reader=reader,
                    artwork_reader=lambda *a: None, controller=controller,
                    lyrics=LyricSession(cancelled, fetch=lambda *a: None))
    try:
        worker.tick()
        commands.put(command())
        worker.tick()
        snapshots = [e for e in events if e["type"] == "playback"]
        assert snapshots[-1]["payload"]["completed_control_id"] == 0
        worker.reader = lambda **kw: A
        worker.tick()
        snapshots = [e for e in events if e["type"] == "playback"]
        assert snapshots[-1]["payload"]["completed_control_id"] == 1
        assert [e for e in events if e["type"] == "control_result"][-1]["payload"]["ok"]
    finally:
        release.set()
        worker.close()
