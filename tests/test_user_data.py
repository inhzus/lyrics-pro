import json
from queue import Queue
import sqlite3
from threading import Event
import time

import pytest

from lyrics_pro.bridge import Bridge
from lyrics_pro.lyric_session import LyricSession
from lyrics_pro.lyrics_cache import LyricsCache
from lyrics_pro.models import LyricLine, Lyrics, Playback
from lyrics_pro.music import MusicError
from lyrics_pro.protocol import ClearData, GetDataStats, parse_command
from lyrics_pro.recording_choices import RecordingChoices
from lyrics_pro.song_languages import SongLanguages


A = Playback("playing", "A", "Eason Chan", "Album", 200, 12)
RAW = Lyrics((LyricLine("令神仙鱼归天要怪谁", 21.6),), "NetEase https://music.163.com/song?id=1", True)


def test_cache_stats_and_clear(tmp_path):
    cache = LyricsCache(tmp_path / "cache.sqlite3")
    assert cache.stats() == (0, 0)
    cache.put(LyricsCache.key(A), RAW)
    cache.put_annotation(RAW, "cantonese", RAW)
    entries, size = cache.stats()
    assert entries == 1 and size > 0
    assert cache.clear() and cache.stats() == (0, 0)
    assert cache.get(LyricsCache.key(A)) is None


def test_recording_choices_clear_is_atomic_and_persistent(tmp_path):
    path = tmp_path / "choices.json"
    choices = RecordingChoices(path)
    choices.set(A, "netease:1")
    assert choices.count == 1
    choices.clear()
    assert choices.count == 0 and json.loads(path.read_text()) == {}
    assert RecordingChoices(path).get(A) is None


def test_clearing_song_languages_never_reimports_the_json_backup(tmp_path):
    path = tmp_path / "preferences.sqlite3"
    legacy = tmp_path / "song-languages.json"
    legacy.write_text(json.dumps({"version": 1, "overrides": {SongLanguages.key(A): "hokkien"}}))
    store = SongLanguages(path)
    assert store.get(A) == "hokkien" and store.count == 1
    store.forget_all()
    store.clear()
    assert store.count == 0 and legacy.exists()
    reopened = SongLanguages(path)
    assert reopened.get(A) == "default" and reopened.count == 0


def test_clear_also_works_when_saved_preferences_were_unreadable(tmp_path):
    path = tmp_path / "preferences.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=1")
        db.execute("CREATE TABLE song_languages (song_key TEXT, language TEXT)")
        db.execute("INSERT INTO song_languages VALUES ('bad', 'klingon')")
    store = SongLanguages(path)
    assert store.warning
    store.clear()
    assert SongLanguages(path).warning == ""


@pytest.mark.parametrize("message,expected", [
    ({"version": 2, "type": "get_data_stats", "payload": {}}, GetDataStats()),
    ({"version": 2, "type": "clear_data", "payload": {"targets": ["lyrics_cache", "song_languages"]}},
     ClearData(("lyrics_cache", "song_languages"))),
])
def test_data_commands_parse(message, expected):
    assert parse_command(message) == expected


@pytest.mark.parametrize("targets", [[], ["everything"], ["lyrics_cache", "lyrics_cache"], "lyrics_cache", [1]])
def test_invalid_clear_targets_are_rejected(targets):
    assert parse_command({"version": 2, "type": "clear_data", "payload": {"targets": targets}}) is None


@pytest.fixture
def session(tmp_path):
    cancelled = Event()
    worker = LyricSession(cancelled, fetch=lambda *_: RAW, cache=LyricsCache(tmp_path / "cache.sqlite3"),
                          choices=RecordingChoices(tmp_path / "choices.json"),
                          song_languages=SongLanguages(tmp_path / "preferences.sqlite3"))
    yield worker
    worker.close()


def settle_storage(worker, timeout=3):
    reports = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and (worker.data_jobs or worker.preference_saves or not reports):
        worker.tick_storage(reports.append)
        time.sleep(0.01)
    return reports


def settle_lyrics(worker, timeout=3):
    updates = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        worker.tick(updates.append)
        if updates and updates[-1]["status"] != "loading" and worker.finished:
            return updates[-1]
        time.sleep(0.01)
    raise AssertionError("Lyrics did not settle")


def test_stats_report_counts_and_cache_size(session):
    session.update_track(A, 1)
    settle_lyrics(session)
    session.choices.set(A, "netease:1")
    session.request_data_stats()
    report = settle_storage(session)[-1]
    assert report["lyrics_entries"] == 1 and report["lyrics_bytes"] > 0
    assert report["recording_choices"] == 1 and report["song_languages"] == 0 and report["message"] == ""


def test_clearing_keeps_visible_lyrics_and_re_resolves_song_language(session):
    session.update_track(A, 1)
    settle_lyrics(session)
    session.set_song_language("cantonese", 1, "hokkien", generation=1, track_identity=A.key)
    assert settle_lyrics(session)["selected_language"] == "hokkien"
    settle_storage(session)
    session.clear_data(("lyrics_cache", "recording_choices", "song_languages"))
    report = settle_storage(session)[-1]
    assert report == dict(lyrics_entries=0, lyrics_bytes=0, recording_choices=0, song_languages=0, message="")
    update = settle_lyrics(session)
    assert update["status"] == "ready" and update["song_language"] == "default"
    assert update["selected_language"] == "cantonese" and update["lyrics"]["lines"]
    assert SongLanguages(session.song_languages.path).get(A) == "default"


def test_failed_cache_clear_is_reported(session, monkeypatch):
    monkeypatch.setattr(session.disk_cache, "clear", lambda: False)
    session.clear_data(("lyrics_cache",))
    assert settle_storage(session)[-1]["message"] == "Couldn’t clear the lyrics cache."


def test_bridge_reports_storage_even_when_music_cannot_be_read(tmp_path):
    events, commands, cancelled = [], Queue(), Event()

    def reader(**_):
        raise MusicError("Music did not respond; waiting to reconnect.")

    lyrics = LyricSession(cancelled, fetch=lambda *_: None, cache=LyricsCache(tmp_path / "cache.sqlite3"),
                          choices=RecordingChoices(tmp_path / "choices.json"),
                          song_languages=SongLanguages(memory_only=True))
    bridge = Bridge(events.append, cancelled, commands, reader=reader, artwork_reader=lambda *_: None, lyrics=lyrics)
    try:
        commands.put(GetDataStats())
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not any(e["type"] == "data_stats" for e in events):
            bridge.tick()
            time.sleep(0.01)
        stats = next(e for e in events if e["type"] == "data_stats")
        assert stats["payload"]["lyrics_entries"] == 0 and stats["version"] == 2
    finally:
        bridge.close()
