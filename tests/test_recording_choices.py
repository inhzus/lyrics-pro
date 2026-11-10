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
RECORD = {"id": 5284269, "name": "故乡", "artists": [{"name": "罗大佑"}],
          "album": {"name": "新乐园"}, "duration": 277676}


def test_unknown_artist_is_suggested_never_automatically_accepted():
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
    assert len(choices) == 5 and choices[0].song_id == 13
    assert not {10, 11, 12} & {c.song_id for c in choices}


def test_artist_query_relevance_precedes_title_only_duration_coincidence():
    unrelated = RECORD | {"id": 2, "artists": [{"name": "Other singer"}], "duration": 275693}
    assert recording_candidates([RECORD, unrelated], TRACK)[0].song_id == 5284269


def test_verified_fallback_beats_suggestions_but_failure_does_not_hide_them():
    suggestion = RecordingChoiceRequired(recording_candidates([RECORD], TRACK))
    class Primary:
        def lookup(self, track): raise suggestion
    class Secondary:
        def lookup(self, track): return RAW
    assert LyricsProvider(Primary(), Secondary()).lookup(TRACK) is RAW
    class Broken:
        def lookup(self, track): raise LookupFailure("timeout", retryable=True)
    with pytest.raises(RecordingChoiceRequired):
        LyricsProvider(Primary(), Broken()).lookup(TRACK)


def test_saved_choice_is_exact_track_scoped_persistent_and_forgettable(tmp_path):
    path = tmp_path / "choices.json"
    choices = RecordingChoices(path)
    choices.set(TRACK, 5284269)
    restored = RecordingChoices(path)
    assert restored.get(replace(TRACK, position=100, state="paused")) == 5284269
    for track in [replace(TRACK, artist="Someone else"), replace(TRACK, duration=250), replace(TRACK, album="Live")]:
        assert restored.get(track) is None
    restored.set(TRACK, None)
    assert RecordingChoices(path).get(TRACK) is None
    path.write_text("broken json")
    assert RecordingChoices(path).get(TRACK) is None


def test_chooser_selects_only_current_suggestions_and_reuses_saved_recording(tmp_path):
    calls = []
    def fetch(*_):
        calls.append("search")
        raise RecordingChoiceRequired(recording_candidates([RECORD], TRACK))
    def selected(song_id, token):
        calls.append(song_id)
        return RAW
    path = tmp_path / "choices.json"
    worker = LyricSession(Event(), language="original", fetch=fetch,
                          choices=RecordingChoices(path), selected_fetch=selected)
    worker.pool.shutdown()
    worker.pool = ControlledPool()
    updates = []
    try:
        worker.update_track(TRACK, 1)
        assert settle(worker, updates)["status"] == "choose_recording"
        for generation, request, song_id in [(0, 0, 5284269), (1, 9, 5284269), (1, 0, 999)]:
            worker.configure("original", 1, generation=generation, choice_request_id=request, choice_id=song_id)
            assert worker.choices.get(TRACK) is None and worker.request_id == 0
        worker.configure("original", 1, generation=1, choice_request_id=0, choice_id=5284269)
        assert settle(worker, updates)["status"] == "ready"
        assert updates[-1]["saved_choice"] is True
        assert calls == ["search", 5284269]
        # A fresh session reads the saved choice and bypasses candidate search.
        restored = RecordingChoices(path)
        assert restored.get(TRACK) == 5284269
        worker.raw_cache.clear()
        worker.update_track(None, 2)
        worker.update_track(TRACK, 3)
        assert settle(worker, updates)["status"] == "ready"
        assert calls == ["search", 5284269, 5284269]
        worker.configure("original", 2, generation=3, forget=True)
        assert settle(worker, updates)["status"] == "choose_recording"
        assert RecordingChoices(path).get(TRACK) is None
    finally:
        worker.close()


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
