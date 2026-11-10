from concurrent.futures import Future
from unittest.mock import Mock, patch
import pytest
from lyrics_pro.lyrics_cache import LyricsCache

from lyrics_pro.cli import run
from lyrics_pro.lyrics import LyricsProvider
from lyrics_pro.models import LookupFailure, LyricLine, Lyrics, Playback


@pytest.fixture(autouse=True)
def isolated_disk_cache(monkeypatch, tmp_path):
    monkeypatch.setattr("lyrics_pro.cli.LyricsCache", lambda: LyricsCache(tmp_path / "cache.sqlite3"))


class Executor:
    def __init__(self):
        self.tasks = []

    def submit(self, fn, *args):
        future = Future()
        self.tasks.append((future, fn, args))
        return future

    def shutdown(self, **kwargs):
        pass


def test_stale_track_results_are_discarded(capsys):
    executor = Executor()
    track_a = Playback("playing", "A", "Unknown", "Album", 100, 15)
    track_b = Playback("playing", "B", "Unknown", "Album", 100, 15)
    snapshots = iter((track_a, track_b, track_b))
    iterations = 0

    def sleep(_):
        nonlocal iterations
        iterations += 1
        if iterations == 1:
            executor.tasks[0][0].set_result(Lyrics((LyricLine("STALE", 10),), "test", True))
        elif iterations == 2:
            executor.tasks[1][0].set_result(Lyrics((LyricLine("CURRENT", 10),), "test", True))
        else:
            raise KeyboardInterrupt

    with patch("lyrics_pro.cli.ThreadPoolExecutor", return_value=executor), \
         patch("lyrics_pro.cli.read_playback", side_effect=lambda: next(snapshots)), \
         patch("lyrics_pro.cli.time.sleep", side_effect=sleep):
        run("auto")
    output = capsys.readouterr().out
    assert "STALE" not in output
    assert "CURRENT" in output
    assert len(executor.tasks) == 2


def test_retries_are_bounded(capsys):
    class FailedExecutor(Executor):
        def submit(self, fn, *args):
            future = super().submit(fn, *args)
            future.set_exception(LookupFailure("Network failure", retryable=True))
            return future

    executor = FailedExecutor()
    count = 0
    clock = 0

    def sleep(_):
        nonlocal count, clock
        count += 1
        clock += 10
        if count == 8:
            raise KeyboardInterrupt

    track = Playback("playing", "A", "Unknown", "Album", 100, 15)
    with patch("lyrics_pro.cli.ThreadPoolExecutor", return_value=executor), \
         patch("lyrics_pro.cli.read_playback", return_value=track), \
         patch("lyrics_pro.cli.time.monotonic", side_effect=lambda: clock), \
         patch("lyrics_pro.cli.time.sleep", side_effect=sleep):
        run("auto")
    assert len(executor.tasks) == 3
    assert "Lyrics unavailable" in capsys.readouterr().out


def test_transient_failure_is_retried_then_fallback_source_is_cached(capsys):
    class ImmediateExecutor(Executor):
        def submit(self, fn, *args):
            future = super().submit(fn, *args)
            try:
                future.set_result(fn(*args))
            except Exception as exc:
                future.set_exception(exc)
            return future

    primary, fallback = Mock(), Mock()
    primary.lookup.return_value = None
    fallback.lookup.side_effect = [LookupFailure("LRCLIB timeout", retryable=True),
                                  Lyrics((LyricLine("CACHED", 10),), "LRCLIB cached-source", True)]
    lrcapi = Mock()
    lrcapi.lookup.return_value = None
    provider = LyricsProvider(primary, fallback, lrcapi=lrcapi)
    track = Playback("playing", "A", "Unknown", "Album", 100, 15)
    snapshots = iter([track, track, track, track, Playback("stopped"), track, track])
    ticks = 0

    def sleep(_):
        nonlocal ticks
        ticks += 1
        if ticks == 7:
            raise KeyboardInterrupt

    with patch("lyrics_pro.cli.LyricsProvider", return_value=provider), \
         patch("lyrics_pro.cli.ThreadPoolExecutor", return_value=ImmediateExecutor()), \
         patch("lyrics_pro.cli.read_playback", side_effect=lambda: next(snapshots)), \
         patch("lyrics_pro.cli.time.monotonic", side_effect=lambda: ticks * 10), \
         patch("lyrics_pro.cli.time.sleep", side_effect=sleep):
        run("auto")
    assert primary.lookup.call_count == fallback.lookup.call_count == 2
    output = capsys.readouterr().out
    assert "Will retry" in output
    assert output.count("Source: LRCLIB cached-source") == 2
    assert "No matching lyrics" not in output
