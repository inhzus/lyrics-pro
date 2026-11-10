from dataclasses import replace
from threading import Event
import io
import json
import subprocess
from queue import Queue
from unittest.mock import patch

import pytest

from lyrics_pro.lyrics import Candidate, LyricsProvider, NetEaseProvider, RecordingChoiceRequired, recording_candidates
from lyrics_pro.models import LookupFailure, Playback
from lyrics_pro.recording_choices import RecordingChoices
from test_lyric_session import ControlledPool, RAW, settle
from lyrics_pro.lyric_session import LyricSession
from lyrics_pro.bridge import read_commands
from lyrics_pro.lyrics import http_json


TRACK = Playback("playing", "故鄉", "Lo Ta-You", "故鄉 - Single", 275.693)


@pytest.fixture(autouse=True)
def isolate_new_provider(monkeypatch):
    monkeypatch.setattr("lyrics_pro.lyrics.LrcAPIProvider.lookup", lambda *_: None)

RECORD = {"id": 5284269, "name": "故乡", "artists": [{"name": "罗大佑"}],
          "album": {"name": "新乐园"}, "duration": 277676}


def test_primary_keeps_unverified_candidates_separate_from_verified_results():
    calls = []
    def fetch(endpoint, params):
        calls.append((endpoint, params))
        assert endpoint == "search/get"
        return {"result": {"songs": [RECORD]} } if params["type"] == 1 else {"result": {"albums": []}}
    with pytest.raises(RecordingChoiceRequired) as error:
        NetEaseProvider(fetch).lookup(TRACK)
    assert error.value.candidates == tuple(recording_candidates([RECORD], TRACK))
    assert len(error.value.candidates) == 1
    assert any(p["s"] == "故乡" for _, p in calls)


def test_suggestions_reject_wrong_versions_and_bound_and_rank_results():
    records = [RECORD | {"id": n} for n in range(1, 9)]
    records += [RECORD | {"id": 10, "name": "故乡 (Live)"},
                RECORD | {"id": 11, "duration": 242119},
                RECORD | {"id": 12, "artists": []},
                RECORD | {"id": 13, "album": {"name": "故鄉 - Single"}}]
    choices = recording_candidates(records + [records[-1]], TRACK)
    assert len(choices) == 9 and choices[0].song_id == 13
    assert not {10, 11, 12} & {c.song_id for c in choices}
    assert len(recording_candidates([RECORD | {"id": n} for n in range(1, 40)], TRACK)) == 30


def test_artist_query_relevance_precedes_title_only_duration_coincidence():
    unrelated = RECORD | {"id": 2, "artists": [{"name": "Other singer"}], "duration": 275693}
    assert recording_candidates([RECORD, unrelated], TRACK)[0].song_id == 5284269


def test_verified_fallback_beats_unverified_automatic_selection():
    suggestion = RecordingChoiceRequired(recording_candidates([RECORD], TRACK))
    calls = []
    class Primary:
        def lookup(self, track): raise suggestion
        def lyrics_for(self, song_id):
            calls.append(song_id)
            return RAW
    class Secondary:
        def lookup(self, track): return RAW
    assert LyricsProvider(Primary(), Secondary()).lookup(TRACK) is RAW
    assert not calls
    class Broken:
        def lookup(self, track): raise LookupFailure("timeout", retryable=True)
    assert LyricsProvider(Primary(), Broken()).lookup(TRACK) is RAW
    assert calls == [5284269]


def test_saved_choice_is_exact_track_scoped_persistent_and_forgettable(tmp_path):
    path = tmp_path / "choices.json"
    choices = RecordingChoices(path)
    choices.set(TRACK, 5284269)
    restored = RecordingChoices(path)
    assert restored.get(replace(TRACK, position=100, state="paused")) == "netease:5284269"
    for track in [replace(TRACK, artist="Someone else"), replace(TRACK, duration=250), replace(TRACK, album="Live")]:
        assert restored.get(track) is None
    restored.set(TRACK, None)
    assert RecordingChoices(path).get(TRACK) is None
    path.write_text("broken json")
    assert RecordingChoices(path).get(TRACK) is None


def test_picker_keeps_lyrics_and_commits_only_successful_current_selection(tmp_path):
    calls = []
    def fetch(*_):
        calls.append("search")
        return RAW
    def selected(song_id, track, token):
        calls.append(song_id)
        return replace(RAW, source=f"NetEase https://music.163.com/song?id={song_id.split(':')[1]}")
    path = tmp_path / "choices.json"
    worker = LyricSession(Event(), language="original", fetch=fetch,
                          choices=RecordingChoices(path), selected_fetch=selected,
                          discover=lambda *_: tuple(recording_candidates([RECORD], TRACK)))
    worker.pool.shutdown()
    worker.pool = ControlledPool()
    worker.discovery_pool.shutdown()
    worker.discovery_pool = ControlledPool()
    updates = []
    try:
        worker.update_track(TRACK, 1)
        assert settle(worker, updates)["status"] == "ready"
        assert worker.choices.get(TRACK) is None
        worker.configure("original", 1, generation=1, discover=True)
        recordings = []
        worker.tick(updates.append, recordings.append)
        assert recordings[-1]["status"] == "loading" and updates[-1]["status"] == "ready"
        worker.discovery_pool.finish()
        worker.tick(updates.append, recordings.append)
        assert recordings[-1]["status"] == "ready"
        for generation, request, song_id in [(0, 1, 5284269), (1, 9, 5284269), (1, 1, 999)]:
            worker.configure("original", 2, generation=generation, choice_request_id=request, choice_id=song_id)
            assert worker.choices.get(TRACK) is None and worker.request_id == 1
        worker.configure("original", 2, generation=1, choice_request_id=1, choice_id=5284269)
        worker.tick(updates.append, recordings.append)
        assert recordings[-1]["switching"] and worker.choices.get(TRACK) is None
        assert worker.raw_cache[TRACK.key] is RAW
        assert settle(worker, updates)["status"] == "ready"
        assert updates[-1]["selection_revision"] == 1
        assert calls == ["search", "netease:5284269"]
        # A fresh session reads the saved choice and bypasses candidate search.
        restored = RecordingChoices(path)
        assert restored.get(TRACK) == "netease:5284269"
        worker.raw_cache.clear()
        worker.update_track(None, 2)
        worker.update_track(TRACK, 3)
        assert settle(worker, updates)["status"] == "ready"
        assert calls == ["search", "netease:5284269", "netease:5284269"]
        worker.configure("original", 3, generation=3, forget=True)
        assert settle(worker, updates)["status"] == "ready"
        assert RecordingChoices(path).get(TRACK) is None
    finally:
        worker.close()


@pytest.fixture
def picker_session(tmp_path):
    worker = LyricSession(Event(), language="original", fetch=lambda *_: RAW,
                          choices=RecordingChoices(tmp_path / "choices.json"),
                          selected_fetch=lambda song_id, track, _: replace(RAW, source=f"NetEase https://music.163.com/song?id={song_id.split(':')[1]}"))
    worker.pool.shutdown()
    worker.pool = ControlledPool()
    worker.discovery_pool.shutdown()
    worker.discovery_pool = ControlledPool()
    worker.update_track(TRACK, 1)
    updates = []
    settle(worker, updates)
    worker.candidates = tuple(recording_candidates([RECORD | {"id": 1}, RECORD | {"id": 2}], TRACK))
    yield worker, updates
    worker.close()


def test_failed_switch_keeps_display_and_saved_choice(picker_session):
    worker, updates = picker_session
    def failure(*_): raise LookupFailure("Recording unavailable")
    worker.selected_fetch = failure
    worker.configure("original", 1, generation=1, choice_request_id=0, choice_id=2)
    assert settle(worker, updates)["lyrics"]["source"] == RAW.source
    assert worker.choices.get(TRACK) is None and worker.selection_revision == 0
    assert worker.selection_error == "Recording unavailable"


def test_latest_switch_wins_and_track_change_cannot_save_old_choice(picker_session):
    worker, updates = picker_session
    worker.configure("original", 1, generation=1, choice_request_id=0, choice_id=1)
    worker.tick(updates.append)
    token = worker.pending[3]
    worker.configure("original", 2, generation=1, choice_request_id=1, choice_id=2)
    assert token.is_set()
    assert settle(worker, updates)["lyrics"]["source"].endswith("id=2")
    assert worker.choices.get(TRACK) == "netease:2" and worker.selection_revision == 1
    worker.configure("original", 3, generation=1, choice_request_id=2, choice_id=1)
    worker.tick(updates.append)
    worker.update_track(replace(TRACK, title="Another song"), 2)
    settle(worker, updates)
    assert worker.choices.get(TRACK) == "netease:2"


def test_opening_picker_does_not_cancel_an_inflight_switch(picker_session):
    worker, updates = picker_session
    worker.configure("original", 1, generation=1, choice_request_id=0, choice_id=2)
    worker.tick(updates.append)
    token = worker.pending[3]
    worker.discover = lambda *_: worker.candidates
    worker.configure("original", 2, generation=1, discover=True)
    assert not token.is_set()
    assert settle(worker, updates)["lyrics"]["source"].endswith("id=2")
    assert worker.choices.get(TRACK) == "netease:2"


def test_discovery_is_cached_and_does_not_hide_lyrics_on_failure(picker_session):
    worker, updates = picker_session
    calls = []
    def discover(*_):
        calls.append(1)
        return worker.candidates
    worker.discover = discover
    worker.configure("original", 1, generation=1, discover=True)
    worker.tick(updates.append)
    worker.discovery_pool.finish()
    worker.tick(updates.append)
    worker.configure("original", 2, generation=1, discover=True)
    worker.tick(updates.append)
    assert calls == [1] and not worker.discovery_pool.jobs
    assert updates[-1]["lyrics"]["source"] == RAW.source
    worker.discovery_status = "error"
    worker.discover = lambda *_: (_ for _ in ()).throw(LookupFailure("network error"))
    worker.configure("original", 3, generation=1, discover=True)
    worker.tick(updates.append)
    worker.discovery_pool.finish()
    worker.tick(updates.append)
    assert worker.discovery_status == "error" and updates[-1]["status"] == "ready"


def test_unverified_automatic_attempts_are_limited_to_three():
    calls = []
    class Primary:
        def lookup(self, track):
            raise RecordingChoiceRequired(recording_candidates([RECORD | {"id": i} for i in range(1, 8)], track))
        def lyrics_for(self, song_id):
            calls.append(song_id)
            return None
    class Secondary:
        def lookup(self, _): return None
    assert LyricsProvider(Primary(), Secondary()).lookup(TRACK) is None
    assert calls == [1, 2, 3]


def test_choice_commands_require_valid_revision_generation_and_id():
    valid = dict(version=1, command="choose_recording", language="original", request_id=2,
                 generation=3, choice_request_id=1, song_id=5284269)
    messages = [valid | {"song_id": True}, valid | {"song_id": -1}, valid | {"choice_request_id": None},
                valid | {"generation": "3"}, valid, valid | {"command": "forget_recording"}]
    queue, cancelled = Queue(), Event()
    read_commands(io.StringIO("\n".join(map(json.dumps, messages))), queue, cancelled)
    assert queue.get_nowait() == valid
    assert queue.get_nowait()["command"] == "forget_recording"
    assert queue.empty()


@pytest.mark.parametrize("exit_code,body,expected", [
    (28, b'{"lyric":"\\xe5', "network request failed"),
    (0, b'{"lyric":"\\xe5\\xff"}\\n200', "invalid JSON"),
])
def test_broken_utf8_becomes_retryable_lookup_failure(exit_code, body, expected):
    # Construct real malformed bytes, without allowing subprocess text decoding.
    body = body.replace(b"\\xe5", bytes([0xe5])).replace(b"\\xff", bytes([0xff])).replace(b"\\n", b"\n")
    response = subprocess.CompletedProcess([], exit_code, body, b"curl timed out")
    with patch("lyrics_pro.lyrics.run_curl", return_value=response):
        with pytest.raises(LookupFailure, match=expected) as error:
            http_json("https://music.163.com/", "NetEase")
    assert error.value.retryable
