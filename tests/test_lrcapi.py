from dataclasses import replace
from threading import Event
from unittest.mock import Mock
import json
import pytest

from lyrics_pro.lyrics import LrcAPIProvider, LyricsProvider, NetEaseProvider
from lyrics_pro.models import Playback, LookupFailure, LookupCancelled
from lyrics_pro.recording_choices import RecordingChoices
from lyrics_pro.recording_ref import source_ref

TRACK = Playback("playing", "忽然", "Li Zhi", "你好,鄭州", 126.853)
RECORD = dict(id="1447841672", title="忽然", artist="李志", album="你好,郑州",
              duration=126.853, lrc="[00:02.10]test one\n[00:09.53]test two")


def provider(records):
    return LrcAPIProvider(lambda _: records)


def stub(result):
    value = Mock()
    if isinstance(result, Exception): value.lookup.side_effect = result
    else: value.lookup.return_value = result
    return value


def test_alias_free_recording_evidence_matches_current_track():
    result = provider([RECORD]).lookup(TRACK)
    assert result.synced and len(result.lines) == 2
    assert source_ref(result.source) == "lrcapi:1447841672"
    assert provider([RECORD]).lookup(replace(TRACK, album="Another album")) is None
    assert provider([RECORD]).lookup(replace(TRACK, artist="李志", album="Another album")).synced


@pytest.mark.parametrize("patch", [dict(title="忽然 (Live)"), dict(duration=150), dict(duration=None),
                                  dict(duration=True), dict(duration=float("nan")), dict(id="https://bad"),
                                  dict(artist=""), dict(album=None)])
def test_bad_or_wrong_recordings_are_excluded(patch):
    assert provider([RECORD | patch]).lookup(TRACK) is None


def test_lrcapi_handles_plain_empty_and_oversized_timing():
    assert not provider([RECORD | {"lrc": "[!text]plain words"}]).lookup(TRACK).synced
    assert provider([RECORD | {"lrc": None}]).lookup(TRACK) is None
    assert provider([RECORD | {"lrc": "[10:00.00]wrong version"}]).lookup(TRACK) is None
    with pytest.raises(LookupFailure): provider({}).lookup(TRACK)


def test_source_priority_and_plain_fallback():
    timed = provider([RECORD]).lookup(TRACK)
    plain = replace(timed, synced=False)
    primary, secondary, last = stub(timed), stub(timed), stub(timed)
    assert LyricsProvider(primary, last, lrcapi=secondary).lookup(TRACK) is timed
    secondary.lookup.assert_not_called()
    last.lookup.assert_not_called()
    primary.lookup.return_value = plain
    assert LyricsProvider(primary, last, lrcapi=secondary).lookup(TRACK) is timed
    last.lookup.assert_not_called()
    secondary.lookup.side_effect = LookupFailure("temporary", retryable=True)
    assert LyricsProvider(primary, last, lrcapi=secondary).lookup(TRACK) is timed
    last.lookup.return_value = None
    assert LyricsProvider(primary, last, lrcapi=secondary).lookup(TRACK) is plain


def test_cancellation_does_not_run_later_provider():
    last = stub(None)
    with pytest.raises(LookupCancelled):
        LyricsProvider(stub(None), last, lrcapi=stub(LookupCancelled("stop"))).lookup(TRACK)
    last.lookup.assert_not_called()
    token = Event(); token.set()
    request = Mock()
    with pytest.raises(LookupCancelled): LrcAPIProvider(request, cancelled=token).lookup(TRACK)
    request.assert_not_called()


def test_selection_is_provider_qualified_and_legacy_choices_migrate(tmp_path):
    path = tmp_path / "choices.json"
    path.write_text(json.dumps({RecordingChoices.key(TRACK): 1447841672}))
    choices = RecordingChoices(path)
    assert choices.get(TRACK) == "netease:1447841672"
    choices.set(TRACK, "lrcapi:1447841672")
    assert RecordingChoices(path).get(TRACK) == "lrcapi:1447841672"
    candidate = provider([RECORD]).alternatives(TRACK)[0]
    assert candidate.reference == "lrcapi:1447841672"
    assert provider([RECORD]).lyrics_for(candidate.song_id, TRACK).synced
    assert provider([RECORD]).lyrics_for("missing", TRACK) is None


def test_lrcapi_choice_commits_after_success_and_emits_qualified_selection(tmp_path):
    from lyrics_pro.lyric_session import LyricSession
    from test_lyric_session import ControlledPool, RAW, settle
    chosen = provider([RECORD]).lookup(TRACK)
    calls = []
    def selected(reference, track, token):
        calls.append((reference, track.key))
        return chosen
    worker = LyricSession(Event(), language="original", fetch=lambda *_: RAW,
                          choices=RecordingChoices(tmp_path / "choices.json"), selected_fetch=selected)
    worker.lookups.pool.shutdown(); worker.lookups.pool = ControlledPool()
    updates, recordings = [], []
    try:
        worker.update_track(TRACK, 1)
        settle(worker, updates)
        worker.recordings.candidates = provider([RECORD]).alternatives(TRACK)
        worker.choose_recording("original", 1, "lrcapi:1447841672", generation=1, choice_request_id=0)
        assert worker.choices.get(TRACK) is None
        assert settle(worker, updates)["lyrics"]["source"] == chosen.source
        worker.tick(updates.append, recordings.append)
        assert recordings[-1]["selected_id"] == "lrcapi:1447841672"
        assert recordings[-1]["candidates"][0]["recording_id"] == "lrcapi:1447841672"
        assert worker.choices.get(TRACK) == "lrcapi:1447841672"
        assert calls == [("lrcapi:1447841672", TRACK.key)]
    finally:
        worker.close()


def test_qualified_bridge_commands_are_validated():
    import io
    from queue import Queue
    from lyrics_pro.bridge import read_commands
    valid = dict(version=1, command="choose_recording", language="original", request_id=2,
                 generation=1, choice_request_id=1, recording_id="lrcapi:1447841672")
    queue = Queue()
    invalid = [valid | {"recording_id": value} for value in [True, "unknown:1", "lrcapi:https://bad", "netease:0"]]
    read_commands(io.StringIO("\n".join(map(json.dumps, invalid + [valid]))), queue, Event())
    assert queue.get_nowait() == valid and queue.empty()
