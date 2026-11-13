from dataclasses import replace
import json
import sqlite3
from threading import Event
from unittest.mock import patch

import pytest

from lyrics_pro.models import Playback, Lyrics, LyricLine, Proofread
from lyrics_pro.pronunciation import resolve_language, choose_language
from lyrics_pro.song_languages import SongLanguages, MAX_ENTRIES, MAX_BYTES
from lyrics_pro.lyric_session import LyricSession
from test_lyric_session import ControlledPool, settle, RAW, A, B


@pytest.mark.parametrize("global_language", ["cantonese", "hokkien", "original"])
@pytest.mark.parametrize("song_language", ["default", "cantonese", "hokkien", "original"])
@pytest.mark.parametrize("proofread", [None, "hokkien", "supplied"])
def test_precedence(global_language, song_language, proofread):
    lyrics = Lyrics((LyricLine("詞", 1, "provided"),), "test", True,
                    proofread=Proofread("asset", "1", proofread, "User") if proofread else None)
    selected, reason = resolve_language(global_language, song_language, lyrics)
    expected = song_language if song_language != "default" else proofread or global_language
    assert selected == (None if expected == "original" else expected)
    assert reason == ("song preference" if song_language != "default" else
                      "proofread transcription" if proofread else "global default")


def test_auto_is_not_an_explicit_language():
    with pytest.raises(ValueError):
        choose_language("Wu Bai", "auto")


def test_identity_persistence_and_clear(tmp_path):
    path = tmp_path / "preferences.sqlite3"
    store = SongLanguages(path)
    song = Playback("paused", "世界第一等 (Live)", "伍佰 & China Blue", "Album", 121)
    store.save(store.set(song, "hokkien"))
    restored = SongLanguages(path)
    assert restored.get(replace(song, album="Compilation", duration=248, artist="Wu Bai")) == "hokkien"
    assert restored.get(replace(song, title="世界第一等")) == "default"
    assert restored.get(replace(song, title="世界第一等 (Remix)")) == "default"
    assert restored.get(replace(song, artist="刘德华")) == "default"
    restored.save(restored.set(song, "default"))
    assert SongLanguages(path).get(song) == "default"


@pytest.mark.parametrize("payload", ["not json", "[]", '{"version":1,"overrides":{"bad":[]}}', "x" * (MAX_BYTES + 1)])
def test_corrupt_or_oversized_legacy_store_is_nonfatal(tmp_path, payload):
    path = tmp_path / "preferences.sqlite3"
    legacy = tmp_path / "song-languages.json"
    legacy.write_text(payload)
    store = SongLanguages(path)
    assert store.get(A) == "default" and store.warning
    store.save(store.set(A, "hokkien"))
    assert SongLanguages(path).get(A) == "hokkien"
    assert legacy.read_text() == payload


def test_capacity_and_failed_transaction_preserve_existing_choices(tmp_path):
    path = tmp_path / "preferences.sqlite3"
    store = SongLanguages(path)
    store.save(store.set(A, "hokkien"))
    before = path.read_bytes()
    with pytest.raises(ValueError):
        store.save({f"{i:064x}": "hokkien" for i in range(MAX_ENTRIES + 1)})
    assert path.read_bytes() == before
    values = store.set(A, "original")
    # Fail after DELETE/INSERT to prove the entire transaction rolls back.
    with patch.object(store, "_mark_migrated", side_effect=sqlite3.OperationalError("disk full")):
        with pytest.raises(sqlite3.OperationalError):
            store.save(values)
    assert store.get(A) == "original"
    assert path.read_bytes() == before
    assert SongLanguages(path).get(A) == "hokkien"
    assert list(tmp_path.iterdir()) == [path]


def test_json_migration_runs_once_and_default_does_not_resurrect(tmp_path):
    path = tmp_path / "preferences.sqlite3"
    legacy = tmp_path / "song-languages.json"
    original = json.dumps({"version": 1, "overrides": {SongLanguages.key(A): "hokkien"}})
    legacy.write_text(original)
    store = SongLanguages(path)
    assert store.get(A) == "hokkien" and not store.warning
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT song_key, language FROM song_languages").fetchall() == [(store.key(A), "hokkien")]
    store.save(store.set(A, "original"))
    assert SongLanguages(path).get(A) == "original"
    store.save(store.set(A, "default"))
    assert SongLanguages(path).get(A) == "default"
    assert legacy.read_text() == original


def test_migration_failure_rolls_back_and_retries(tmp_path):
    path = tmp_path / "preferences.sqlite3"
    legacy = tmp_path / "song-languages.json"
    legacy.write_text(json.dumps({"version": 1, "overrides": {SongLanguages.key(A): "hokkien"}}))
    with patch.object(SongLanguages, "_mark_migrated", side_effect=sqlite3.OperationalError("disk full")):
        failed = SongLanguages(path)
    assert failed.warning and failed.get(A) == "default"
    with pytest.raises(ValueError):
        failed.save(failed.set(B, "original"))
    assert SongLanguages(path).get(A) == "hokkien"


def test_existing_sqlite_preference_wins_during_migration(tmp_path):
    path = tmp_path / "preferences.sqlite3"
    store = SongLanguages(path)
    store.save(store.set(A, "original"))
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM migrations")
    (tmp_path / "song-languages.json").write_text(json.dumps({
        "version": 1, "overrides": {store.key(A): "hokkien", store.key(B): "cantonese"}}))
    restored = SongLanguages(path)
    assert restored.get(A) == "original" and restored.get(B) == "cantonese"


def test_corrupt_database_is_nonfatal_and_never_overwritten(tmp_path):
    path = tmp_path / "preferences.sqlite3"
    path.write_bytes(b"not sqlite")
    store = SongLanguages(path)
    assert store.warning
    with pytest.raises(ValueError):
        store.save(store.set(A, "original"))
    assert store.get(A) == "original" and path.read_bytes() == b"not sqlite"


def test_future_database_version_is_not_downgraded(tmp_path):
    path = tmp_path / "preferences.sqlite3"
    store = SongLanguages(path)
    store.save(store.set(A, "hokkien"))
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=2")
    restored = SongLanguages(path)
    assert restored.warning
    with pytest.raises(ValueError):
        restored.save(restored.set(A, "original"))
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute("SELECT language FROM song_languages").fetchone()[0] == "hokkien"


def test_locked_database_keeps_session_choice_and_can_save_after_unlock(tmp_path):
    store = SongLanguages(tmp_path / "preferences.sqlite3")
    store.save(store.set(A, "hokkien"))
    with sqlite3.connect(store.path) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError):
            store.save(store.set(A, "original"))
        assert store.get(A) == "original"
    store.save(dict(store.persistable))
    assert SongLanguages(store.path).get(A) == "original"


def test_capacity_failure_does_not_block_updates_to_existing_preferences(tmp_path):
    store = SongLanguages(tmp_path / "preferences.sqlite3")
    store.save(store.set(A, "hokkien"))
    store.persistable.update({f"{i:064x}": "hokkien" for i in range(MAX_ENTRIES - 1)})
    store.save(store.persistable)
    with pytest.raises(ValueError):
        store.save(store.set(B, "original"))
    assert store.get(B) == "original"
    store.save(store.set(A, "cantonese"))
    restored = SongLanguages(store.path)
    assert restored.get(A) == "cantonese" and restored.get(B) == "default"


@pytest.fixture
def session(tmp_path):
    store = SongLanguages(tmp_path / "preferences.sqlite3")
    worker = LyricSession(Event(), fetch=lambda *_: RAW, song_languages=store)
    worker.lookups.pool.shutdown()
    worker.lookups.pool = ControlledPool()
    worker.preferences_pool.shutdown()
    worker.preferences_pool = ControlledPool()
    worker.update_track(A, 1)
    yield worker, store
    while worker.preferences_pool.jobs:
        worker.preferences_pool.finish()
    worker.close()


def test_song_override_saved_during_fetch_and_shared_across_albums(session):
    worker, store = session
    updates = []
    worker.tick(updates.append)
    pending = worker.lookups.job
    worker.set_song_language("cantonese", 1, "original", generation=1, track_identity=A.key)
    assert worker.lookups.job == pending and not pending.token.is_set()
    worker.preferences_pool.finish()
    assert SongLanguages(store.path).get(A) == "original"
    result = settle(worker, updates)
    assert result["song_language"] == "original" and result["selected_language"] is None
    worker.update_track(replace(A, album="Other", duration=250), 2)
    assert settle(worker, [])["song_language"] == "original"
    worker.update_track(B, 3)
    assert settle(worker, [])["song_language"] == "default"


def test_stale_song_commands_never_change_or_save_preferences(session):
    worker, store = session
    for revision, (generation, identity) in enumerate([(0, A.key), (1, B.key)], 1):
        worker.set_song_language("cantonese", revision, "hokkien", generation=generation, track_identity=identity)
    assert store.get(A) == "default" and store.get(B) == "default"
    assert not worker.preferences_pool.jobs and worker.request_id == 2
    assert settle(worker, [])["request_id"] == 2
    worker.set_song_language("cantonese", 3, "hokkien", generation=1, track_identity=A.key)
    worker.set_song_language("cantonese", 3, "original", generation=1, track_identity=A.key)
    assert store.get(A) == "hokkien" and len(worker.preferences_pool.jobs) == 1


def test_override_cancels_old_annotation_and_default_clears_it(session):
    worker, store = session
    worker.tick(lambda _: None)
    worker.lookups.pool.finish()
    worker.tick(lambda _: None)
    old = worker.lookups.job
    worker.set_song_language("cantonese", 1, "original", generation=1, track_identity=A.key)
    assert old.token.is_set()
    worker.lookups.pool.finish()
    assert settle(worker, [])["selected_language"] is None
    worker.set_language("hokkien", 2)
    assert settle(worker, [])["selected_language"] is None
    worker.set_song_language("hokkien", 3, "default", generation=1, track_identity=A.key)
    assert settle(worker, [])["selected_language"] == "hokkien"
    assert store.get(A) == "default"


def test_failed_save_reports_warning_but_keeps_session_preference(session):
    worker, store = session
    worker.set_song_language("cantonese", 1, "original", generation=1, track_identity=A.key)
    with patch.object(store, "save", side_effect=OSError("read-only")):
        # ControlledPool captured the bound method; replace that job's function.
        future, _, args = worker.preferences_pool.jobs[0]
        worker.preferences_pool.jobs[0] = (future, store.save, args)
        worker.preferences_pool.finish()
    result = settle(worker, [])
    assert result["selected_language"] is None and "Couldn’t save" in result["preference_warning"]
    assert store.get(A) == "original"
