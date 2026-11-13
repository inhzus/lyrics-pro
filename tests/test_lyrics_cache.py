from dataclasses import replace
import json
import sqlite3
from threading import Event
import pytest
from lyrics_pro.lyrics_cache import LyricsCache
from lyrics_pro.lyric_session import LyricSession
from lyrics_pro.recording_choices import RecordingChoices
from lyrics_pro.models import LookupFailure
from test_lyric_session import A, RAW, ControlledPool, settle


def test_restart_selection_keys_and_annotation_versions(tmp_path, monkeypatch):
    path = tmp_path / "cache.sqlite3"
    cache = LyricsCache(path)
    key = cache.key(A)
    cache.put(key, RAW)
    cached = LyricsCache(path)
    assert cached.get(key) == RAW
    assert cached.get(cache.key(A, "lrcapi:1")) is None
    assert cached.get(cache.key(replace(A, duration=201))) is None
    annotation = replace(RAW, lines=(replace(RAW.lines[0], pronunciation="test"),))
    cache.put_annotation(RAW, "cantonese", annotation)
    assert cached.annotated(RAW, "cantonese") == annotation
    assert cached.annotated(RAW, "hokkien") is None
    monkeypatch.setattr("lyrics_pro.lyrics_cache.annotation_version", lambda _: "new-engine")
    assert cached.annotated(RAW, "cantonese") is None


def test_eviction_bounds_raw_and_annotation_payloads(tmp_path):
    cache = LyricsCache(tmp_path / "cache.sqlite3", max_entries=2, max_bytes=2000)
    for key in ["one", "two"]: cache.put(key, RAW)
    assert cache.get("one")
    cache.put("three", RAW)
    assert cache.get("two") is None
    assert cache.get("one") and cache.get("three")
    cache.put("huge", replace(RAW, lines=(replace(RAW.lines[0], text="x" * 5000),)))
    assert cache.get("huge") is None
    cache.put("missing", None)
    assert cache.get("missing") is None
    with sqlite3.connect(cache.path) as db:
        assert db.execute("SELECT count(*) FROM recordings").fetchone()[0] <= 2


def test_corrupt_storage_and_invalid_entries_are_misses(tmp_path):
    path = tmp_path / "cache.sqlite3"
    path.write_bytes(b"corrupt")
    cache = LyricsCache(path)
    assert cache.get("test") is None
    cache.put("test", RAW)  # Best effort; must not interrupt lookup.
    good = LyricsCache(tmp_path / "good.sqlite3")
    good.put("test", RAW)
    with sqlite3.connect(good.path) as db:
        db.execute("UPDATE recordings SET payload=?", ('{"lines": false}',))
    assert good.get("test") is None


def test_session_offline_restart_and_refresh_keep_usable_lyrics(tmp_path):
    cache = LyricsCache(tmp_path / "cache.sqlite3")
    calls = []
    def fetch(track, token):
        calls.append(track.key)
        if len(calls) > 1: raise LookupFailure("offline", retryable=True)
        return RAW
    def session():
        worker = LyricSession(Event(), language="original", fetch=fetch, cache=cache,
                              choices=RecordingChoices(tmp_path / "choices.json"))
        worker.lookups.pool.shutdown(); worker.lookups.pool = ControlledPool()
        worker.update_track(A, 1)
        return worker
    first = session()
    try: assert settle(first, [])["status"] == "ready"
    finally: first.close()
    second = session()
    updates = []
    try:
        assert settle(second, updates)["status"] == "ready"
        assert len(calls) == 1
        second.retry("original", 1, generation=1)
        assert settle(second, updates)["lyrics"]["source"] == RAW.source
        assert len(calls) == 2
        assert cache.get(cache.key(A)) == RAW
    finally: second.close()
