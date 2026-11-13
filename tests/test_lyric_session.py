from concurrent.futures import Future
from dataclasses import replace
from queue import Queue
from threading import Event

import pytest

from lyrics_pro.bridge import Bridge
from lyrics_pro.lyric_session import LyricSession
from lyrics_pro.models import Lyrics, LyricLine, LookupCancelled, LookupFailure, Playback


A = Playback("playing", "A", "Eason Chan", "Album", 200, 12)
B = replace(A, title="B", artist="Wu Bai")
RAW = Lyrics((LyricLine("令神仙鱼归天要怪谁", 21.6),),
             "NetEase https://music.163.com/song?id=1", True)


class ControlledPool:
    """Advance each job explicitly, including jobs that finish after cancellation."""
    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args):
        future = Future()
        self.jobs.append((future, fn, args))
        return future

    def finish(self):
        future, fn, args = self.jobs.pop(0)
        try:
            future.set_result(fn(*args))
        except Exception as error:
            future.set_exception(error)

    def shutdown(self, **kwargs):
        pass


@pytest.fixture
def session():
    calls, updates = [], []

    def fetch(track, token):
        calls.append(track.key)
        return RAW

    worker = LyricSession(Event(), fetch=fetch)
    worker.lookups.pool.shutdown()
    worker.lookups.pool = ControlledPool()
    yield worker, calls, updates
    worker.close()


def settle(worker, updates):
    for _ in range(6):
        worker.tick(updates.append)
        if worker.finished:
            return updates[-1]
        if worker.lookups.pool.jobs:
            worker.lookups.pool.finish()
    raise AssertionError("Lyrics did not settle")


def test_real_jyutping_preserves_source_times_and_original_text(session):
    worker, calls, updates = session
    worker.update_track(A, 1)
    result = settle(worker, updates)
    assert result["status"] == "ready"
    assert result["reason"] == "global default"
    assert result["selected_language"] == "cantonese"
    assert result["lyrics"]["source"] == RAW.source
    assert result["lyrics"]["lines"][0] == {
        "text": "令神仙鱼归天要怪谁", "time": 21.6,
        "pronunciation": "ling6 san4 sin1 jyu2 gwai1 tin1 jiu3 gwaai3 seoi4",
    }
    assert len(calls) == 1


def test_language_change_during_fetch_reuses_request_and_annotations(session):
    worker, calls, updates = session
    worker.update_track(A, 1)
    worker.tick(updates.append)
    worker.set_language("original", 1)
    worker.lookups.pool.finish()
    result = settle(worker, updates)
    assert result["request_id"] == 1
    assert result["selected_language"] is None
    assert result["lyrics"]["lines"][0]["pronunciation"] is None
    worker.set_language("cantonese", 2)
    result = settle(worker, updates)
    assert result["lyrics"]["lines"][0]["pronunciation"]
    worker.set_language("original", 3)
    assert settle(worker, updates)["request_id"] == 3
    assert not worker.lookups.pool.jobs
    assert len(calls) == 1


def test_language_change_cancels_inflight_annotation(session):
    worker, calls, updates = session
    worker.update_track(A, 1)
    worker.tick(updates.append)
    worker.lookups.pool.finish()
    worker.tick(updates.append)
    assert worker.lookups.job.kind == "annotate"
    token = worker.lookups.job.token
    worker.set_language("original", 1)
    assert token.is_set()
    worker.lookups.pool.finish()
    result = settle(worker, updates)
    assert result["language"] == "original"
    assert not result["lyrics"]["lines"][0]["pronunciation"]
    assert len(calls) == 1


def test_a_b_a_discards_old_fetch_even_if_it_returns(session):
    worker, calls, updates = session
    worker.update_track(A, 1)
    worker.tick(updates.append)
    old_token = worker.lookups.job.token
    worker.update_track(B, 2)
    worker.update_track(A, 3)
    assert old_token.is_set()
    worker.lookups.pool.finish()  # Simulate a provider returning despite cancellation.
    worker.tick(updates.append)
    assert not worker.caches.raw
    assert worker.lookups.job.context == (A.key, 3)
    settle(worker, updates)
    # Cancellation is now checked before the queued provider work starts.
    assert len(calls) == 1


@pytest.mark.parametrize("raw,status", [
    (None, "unavailable"),
    (Lyrics((), "NetEase", False), "unavailable"),
    (Lyrics((), "NetEase", False, True), "instrumental"),
    (replace(RAW, synced=False, lines=(LyricLine("text"),)), "plain"),
])
def test_missing_instrumental_and_plain_are_distinct_and_cached(session, raw, status):
    worker, _, updates = session
    calls = []
    worker.fetch = lambda *_: calls.append(1) or raw
    worker.update_track(A, 1)
    assert settle(worker, updates)["status"] == status
    worker.update_track(None, 2)
    worker.update_track(A, 3)
    assert settle(worker, updates)["status"] == status
    assert len(calls) == 1


def test_transient_failures_retry_three_times_then_manual_retry(session):
    worker, _, updates = session
    clock = [0]
    worker.clock = lambda: clock[0]
    calls = []

    def failure(*_):
        calls.append(1)
        raise LookupFailure("Network unavailable", retryable=True)

    worker.fetch = failure
    worker.update_track(A, 1)
    for attempt, delay in [(1, 2), (2, 4), (3, 0)]:
        worker.tick(updates.append)
        worker.lookups.pool.finish()
        worker.tick(updates.append)
        assert len(calls) == attempt
        if delay:
            assert worker.failure.retry_at == clock[0] + delay
            assert updates[-1]["status"] == "loading"
            worker.tick(updates.append)
            assert not worker.lookups.pool.jobs
            clock[0] += delay
    assert updates[-1]["status"] == "error"
    assert not worker.caches.raw
    worker.fetch = lambda *_: RAW
    worker.retry("original", 1, generation=1)
    assert settle(worker, updates)["status"] == "ready"


def test_retry_invalidates_cached_lyrics_but_stale_generation_does_not(session):
    worker, calls, updates = session
    worker.update_track(A, 5)
    settle(worker, updates)
    worker.retry("cantonese", 1, generation=4)
    assert settle(worker, updates)["request_id"] == 1
    assert len(calls) == 1
    worker.retry("cantonese", 2, generation=5)
    settle(worker, updates)
    assert len(calls) == 2
    worker.set_language("hokkien", 1)
    assert worker.language == "cantonese" and worker.request_id == 2


def test_unknown_artist_uses_global_default_and_hokkien_can_be_selected(session):
    worker, calls, updates = session
    worker.update_track(replace(A, artist="Unknown"), 1)
    result = settle(worker, updates)
    assert result["selected_language"] == "cantonese"
    assert result["reason"] == "global default"
    worker.set_language("hokkien", 1)
    result = settle(worker, updates)
    assert result["selected_language"] == "hokkien"
    assert result["lyrics"]["lines"][0]["pronunciation"]
    assert len(calls) == 1


def test_pending_lookup_does_not_block_music_and_is_cancelled_on_shutdown():
    started, ended, stopped = Event(), Event(), Event()
    events = []

    def fetch(track, token):
        started.set()
        try:
            while not token.is_set():
                stopped.wait(.01)
            raise LookupCancelled("Cancelled")
        finally:
            ended.set()

    lyrics = LyricSession(stopped, fetch=fetch)
    bridge = Bridge(events.append, stopped, Queue(), reader=lambda **_: A,
                    artwork_reader=lambda *_: None, lyrics=lyrics)
    try:
        bridge.tick()
        assert started.wait(1)
        for _ in range(3):
            bridge.tick()
        assert len([e for e in events if e["type"] == "playback"]) == 4
    finally:
        bridge.close()
    assert ended.is_set()


def test_original_lyrics_can_recover_after_pronunciation_engine_fails(session):
    worker, calls, updates = session

    class BrokenRomanizer:
        def line(self, *_):
            raise RuntimeError("Dictionary unavailable")

    worker.romanizer = BrokenRomanizer()
    worker.update_track(A, 1)
    assert settle(worker, updates)["status"] == "error"
    worker.set_language("original", 1)
    assert settle(worker, updates)["status"] == "ready"
    assert len(calls) == 1


def test_track_and_annotation_caches_are_bounded(session):
    worker, _, updates = session
    for index in range(20):
        worker.update_track(replace(A, title=str(index)), index + 1)
        worker.set_language("original", index * 2 + 1)
        settle(worker, updates)
        worker.set_language("cantonese", index * 2 + 2)
        settle(worker, updates)
    assert len(worker.caches.raw) == 16
    assert len(worker.caches.annotations) == 32


def test_refetch_after_raw_eviction_does_not_reuse_old_annotations(session):
    worker, _, updates = session
    worker.update_track(A, 1)
    settle(worker, updates)
    worker.caches.raw.pop(A.key)
    worker.fetch = lambda *_: replace(RAW, lines=(LyricLine("New recording lyrics", 5),))
    worker.update_track(None, 2)
    worker.update_track(A, 3)
    result = settle(worker, updates)
    assert result["lyrics"]["lines"][0]["text"] == "New recording lyrics"
    assert result["lyrics"]["lines"][0]["time"] == 5
