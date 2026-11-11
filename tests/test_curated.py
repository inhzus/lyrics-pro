from dataclasses import replace
from importlib.resources import files
import hashlib
import json
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest

from lyrics_pro import curated
from lyrics_pro.lyrics import Candidate
from lyrics_pro.lyrics_cache import LyricsCache, decode, encode, fingerprint
from lyrics_pro.lyric_session import Cancellation, LyricSession, lookup_recording
from lyrics_pro.models import LookupCancelled, LookupFailure, Playback
from lyrics_pro.pronunciation import Romanizer, choose_language
from lyrics_pro.recording_choices import RecordingChoices
from test_lyric_session import ControlledPool, RAW, settle


TRACK = Playback("paused", "少年吔，安啦！", "Unrecognized artist", "Another compilation", 413.786, 27)
PROOFREAD = "proofread:shao-nian-eh-an-la"


def asset():
    return json.loads(files("lyrics_pro").joinpath("data/proofread/shao-nian-eh-an-la.json").read_text())


def test_asset_preserves_every_timing_and_supplied_pair():
    root = Path(__file__).resolve().parents[1] / "resources/lyrics-spelling"
    inputs = root / "shao-nian-eh-an-la"
    report = asset()["alignment"]
    manual = json.loads((inputs / "proofread.json").read_text())
    timed = json.loads((inputs / "timed.json").read_text())
    allowed = {(b["text"], b["spelling"]) for b in manual["blocks"]}
    allowed.update((p["text"], p["spelling"]) for b in manual["blocks"] for p in b.get("parts", []))
    allowed = {(" ".join(text.split()), " ".join(spelling.split())) for text, spelling in allowed}
    raw = curated.curated_lyrics(TRACK)
    assert len(raw.lines) == 58
    assert [line.time for line in raw.lines] == [row["time"] for row in timed["lines"]]
    assert sum(bool(line.pronunciation) for line in raw.lines) == 49
    assert sum(not line.text for line in raw.lines) == 6
    for line in raw.lines:
        if line.pronunciation:
            assert (line.text, line.pronunciation) in allowed
    for name, path in [("manual", inputs / "proofread.json"), ("timed", inputs / "timed.json"),
                       ("original", root / "少年吔，安啦-伍佰")]:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == report["input_sha256"][name]
    assert report["boundary_warnings"] == [{"source_rows": [45, 46], "phrase": "叫我"}]
    assert report["audio_verified"] is False

    # The original column layout must not create large gaps in the app.
    verse = next(line for line in raw.lines if line.text.startswith("心內話"))
    assert verse.text == "心內話 沒人聽 眾人騎 沒人疼"
    assert verse.pronunciation == "sim-lāi-uē bô-lâng thiann tsiòng lâng khiâ bô-lâng thiànn"
    mixed = asset()
    mixed["alignment"]["rows"][3].update(text="\t滿腹\u3000 \t怨氣  ", spelling="  muá-pak\t\tê\u00a0hīn-khì\u3000 ")
    line = curated._decode_asset(json.dumps(mixed)).lyrics.lines[3]
    assert line.text == "滿腹 怨氣" and line.pronunciation == "muá-pak ê hīn-khì"
    assert line.time == 26.92


@pytest.mark.parametrize("patch", [
    {"artist": "伍佰 & China Blue", "album": ""}, {"artist": "", "album": "Live collection"},
    {"title": " 少年吔, 安啦 "}, {"duration": 411.786}, {"duration": 415.786},
])
def test_artist_album_and_punctuation_do_not_block_asset(patch):
    assert curated.curated_lyrics(replace(TRACK, **patch))


@pytest.mark.parametrize("patch", [
    {"title": "少年吔，安啦 (Live)"}, {"title": "少年吔，安啦 Remix"}, {"title": "Other song"},
    {"duration": 0}, {"duration": 410}, {"duration": float("nan")}, {"duration": float("inf")},
])
def test_title_version_and_duration_still_guard_timing(patch):
    assert curated.curated_lyrics(replace(TRACK, **patch)) is None


def test_recording_overrides_and_cancellation():
    assert curated.curated_lyrics(TRACK, PROOFREAD)
    for ref in ["netease:5237870", 5237870, "netease:1", "lrcapi:5237870", "proofread:missing", "bad"]:
        assert curated.curated_lyrics(TRACK, ref) is None
    cancelled = Event()
    cancelled.set()
    with pytest.raises(LookupCancelled):
        curated.curated_lyrics(TRACK, cancelled=cancelled)


def test_pronunciation_overrides_and_cache_revision(tmp_path):
    raw = curated.curated_lyrics(TRACK)
    romanizer = Romanizer()
    assert choose_language("Unknown", "auto", raw) == ("hokkien", "proofread transcription")
    assert romanizer.annotate(raw, "hokkien") is raw
    original = romanizer.annotate(raw, None)
    assert all(line.pronunciation is None for line in original.lines)
    assert [line.text for line in original.lines] == [line.text for line in raw.lines]
    jyutping = romanizer.annotate(raw, "cantonese")
    assert jyutping.lines[3].pronunciation != raw.lines[3].pronunciation
    assert [line.time for line in jyutping.lines] == [line.time for line in raw.lines]
    assert decode(encode(raw)) == raw
    old = json.loads(encode(RAW))
    del old["proofread"]
    del old["recording_id"]
    assert decode(json.dumps(old)) == RAW
    newer = replace(raw, proofread=replace(raw.proofread, revision="next"))
    assert fingerprint(raw) != fingerprint(newer)
    cache = LyricsCache(tmp_path / "cache.sqlite3")
    cache.put_annotation(raw, "cantonese", jyutping)
    assert cache.annotated(newer, "cantonese") is None


def test_proofread_identity_is_independent_of_timing_reference():
    raw = curated.curated_lyrics(TRACK)
    assert raw.recording_id == PROOFREAD
    assert raw.source == "Proofread https://music.163.com/song?id=5237870"
    candidate, = curated.curated_candidates(TRACK)
    assert candidate.reference == PROOFREAD and candidate.provider == "proofread"
    assert candidate.title == "少年吔，安啦！" and candidate.artists == ("伍佰",)
    assert lookup_recording(PROOFREAD, TRACK, Event()) == raw
    with pytest.raises(LookupFailure, match="unavailable"):
        lookup_recording("proofread:missing", TRACK, Event())


@pytest.mark.parametrize("mutation", [
    lambda a: a.update(schema_version=99),
    lambda a: a["alignment"]["rows"][3].update(spelling=""),
    lambda a: a["alignment"]["rows"][3].update(time=-1),
    lambda a: a["alignment"].update(recording_id="netease:1"),
    lambda a: a["alignment"].update(timing_source=None),
    lambda a: a["alignment"]["rows"][3].update(status="unresolved"),
])
def test_invalid_assets_fall_back_without_network_in_loader(tmp_path, monkeypatch, mutation):
    folder = tmp_path / "data/proofread"
    folder.mkdir(parents=True)
    bad = asset()
    mutation(bad)
    (folder / "bad.json").write_text(json.dumps(bad))
    monkeypatch.setattr(curated, "files", lambda _: tmp_path)
    curated._recordings.cache_clear()
    try:
        assert curated.curated_lyrics(TRACK) is None
    finally:
        curated._recordings.cache_clear()


@pytest.fixture
def worker(tmp_path):
    cache = LyricsCache(tmp_path / "cache.sqlite3")
    cache.put(cache.key(TRACK), RAW)  # A preexisting provider result must not win.
    fetch = Mock(return_value=RAW)
    selected_fetch = Mock(return_value=RAW)
    session = LyricSession(Event(), fetch=fetch, selected_fetch=selected_fetch, cache=cache,
                           choices=RecordingChoices(tmp_path / "choices.json"))
    session.pool.shutdown()
    session.pool = ControlledPool()
    session.update_track(TRACK, 1)
    yield session, fetch, selected_fetch
    session.close()


def test_session_auto_language_retry_original_and_bad_annotation_cache(worker):
    session, fetch, _ = worker
    raw = curated.curated_lyrics(TRACK)
    session.disk_cache.put_annotation(raw, "hokkien", RAW)  # Supplied spelling always wins.
    result = settle(session, [])
    assert result["selected_language"] == "hokkien"
    assert result["reason"] == "proofread transcription"
    assert result["lyrics"]["lines"][3]["pronunciation"] == raw.lines[3].pronunciation
    session.configure("auto", 1, retry=True, generation=1)
    assert settle(session, [])["lyrics"]["proofread"]
    session.configure("original", 2)
    assert all(l["pronunciation"] is None for l in settle(session, [])["lyrics"]["lines"])
    session.configure("hokkien", 3)
    assert settle(session, [])["lyrics"]["lines"][3]["pronunciation"] == raw.lines[3].pronunciation
    fetch.assert_not_called()


def test_generic_supplied_spelling_survives_loading_retry_and_language_changes(worker, monkeypatch):
    session, fetch, _ = worker
    recording = next(r for r in curated._recordings() if r.reference == PROOFREAD)
    raw = replace(recording.lyrics, proofread=replace(recording.lyrics.proofread, language="supplied"))
    monkeypatch.setattr(curated, "_recordings", lambda: (replace(recording, lyrics=raw),))
    updates = []
    result = settle(session, updates)
    assert result["selected_language"] == "supplied"
    assert any(u["status"] == "loading" and u["selected_language"] == "supplied" and u["lyrics"] is None
               for u in updates)
    assert result["lyrics"]["lines"][3]["pronunciation"] == raw.lines[3].pronunciation
    session.configure("original", 1)
    assert all(line["pronunciation"] is None for line in settle(session, [])["lyrics"]["lines"])
    session.configure("hokkien", 2)
    generated = settle(session, [])
    assert generated["selected_language"] == "hokkien"
    assert generated["lyrics"]["lines"][3]["pronunciation"] != raw.lines[3].pronunciation
    session.configure("auto", 3, retry=True, generation=1)
    refreshed = settle(session, [])
    assert refreshed["selected_language"] == "supplied"
    assert refreshed["lyrics"]["lines"][3]["pronunciation"] == raw.lines[3].pronunciation
    fetch.assert_not_called()


def test_switch_to_other_recording_and_back_recomputes_auto_language(worker):
    session, fetch, selected_fetch = worker
    assert settle(session, [])["selected_language"] == "hokkien"
    session.candidates = (Candidate(1, TRACK.title, ("Other",), "Album", TRACK.duration),)
    session.configure("auto", 1, generation=1, choice_id="netease:1", choice_request_id=0)
    result = settle(session, [])
    assert result["selected_language"] is None and result["lyrics"]["proofread"] is None
    assert session.choices.get(TRACK) == "netease:1"
    selected_fetch.assert_called_once()
    session.configure("auto", 2, generation=1, forget=True)
    result = settle(session, [])
    assert result["selected_language"] == "hokkien" and result["lyrics"]["proofread"]
    assert session.choices.get(TRACK) is None
    fetch.assert_not_called()


def test_missing_assets_use_existing_provider_and_cancelled_load_stops(worker, monkeypatch):
    session, fetch, _ = worker
    monkeypatch.setattr(curated, "_recordings", lambda: ())
    token = Cancellation(session.cancelled)
    assert session._load(TRACK, None, token, refresh=True) is RAW
    fetch.assert_called_once()
    token.set()
    with pytest.raises(LookupCancelled):
        session._load(TRACK, None, token)
    fetch.assert_called_once()


def test_explicit_original_timing_provider_is_no_longer_proofread(worker):
    session, fetch, selected_fetch = worker
    raw = session._load(TRACK, "netease:5237870", Cancellation(session.cancelled))
    assert raw is RAW and raw.proofread is None
    selected_fetch.assert_called_once()
    fetch.assert_not_called()


def test_saved_proofread_choice_survives_restart_and_automatic_clears_it(worker):
    session, fetch, selected_fetch = worker
    settle(session, [])
    session.candidates = curated.curated_candidates(TRACK) + (Candidate(1, TRACK.title, ("Other",), "Album", TRACK.duration),)
    session.configure("auto", 1, generation=1, choice_id="netease:1", choice_request_id=0)
    assert settle(session, [])["lyrics"]["proofread"] is None
    session.configure("auto", 2, generation=1, choice_id=PROOFREAD, choice_request_id=1)
    result = settle(session, [])
    assert result["lyrics"]["recording_id"] == PROOFREAD and result["selected_language"] == "hokkien"
    assert RecordingChoices(session.choices.path).get(TRACK) == PROOFREAD
    recordings = []
    session.tick(lambda _: None, recordings.append)
    assert recordings[-1]["selected_id"] == PROOFREAD and recordings[-1]["manual"]

    restored = LyricSession(Event(), fetch=Mock(side_effect=AssertionError("Unexpected network")),
                           choices=RecordingChoices(session.choices.path))
    restored.pool.shutdown()
    restored.pool = ControlledPool()
    try:
        restored.update_track(TRACK, 1)
        assert settle(restored, [])["lyrics"]["recording_id"] == PROOFREAD
        restored.configure("auto", 1, generation=1, forget=True)
        assert settle(restored, [])["lyrics"]["recording_id"] == PROOFREAD
        assert RecordingChoices(restored.choices.path).get(TRACK) is None
    finally:
        restored.close()
    selected_fetch.assert_called_once()
    fetch.assert_not_called()


def test_unavailable_proofread_switch_keeps_previous_lyrics_and_choice(worker, monkeypatch):
    session, _, selected_fetch = worker
    session.choices.set(TRACK, "netease:1")
    settle(session, [])
    session.candidates = curated.curated_candidates(TRACK)
    # Even a previously cached copy must not bypass current title/duration/resource checks.
    session.disk_cache.put(session.disk_cache.key(TRACK, PROOFREAD), curated.curated_lyrics(TRACK))
    monkeypatch.setattr(curated, "_recordings", lambda: ())
    session.configure("auto", 1, generation=1, choice_id=PROOFREAD, choice_request_id=0)
    result = settle(session, [])
    assert result["lyrics"]["source"] == RAW.source and result["lyrics"]["proofread"] is None
    assert "unavailable" in session.selection_error
    assert session.choices.get(TRACK) == "netease:1"
    selected_fetch.assert_called_once()


@pytest.mark.parametrize("offline", [False, True])
def test_local_source_is_selectable_before_online_discovery_finishes(worker, offline):
    session, _, _ = worker
    entered, release = Event(), Event()
    def discover(track, token):
        entered.set()
        assert release.wait(3), "Test did not release discovery"
        if offline:
            raise LookupFailure("Offline")
        return curated.curated_candidates(TRACK) + tuple(
            Candidate(i, TRACK.title, ("Artist",), "Album", TRACK.duration) for i in range(1, 31))
    session.discover = discover
    settle(session, [])
    session.configure("auto", 1, generation=1, discover=True)
    session.tick(lambda _: None)
    try:
        assert entered.wait(2)
        recordings = []
        session.tick(lambda _: None, recordings.append)
        assert recordings[-1]["status"] == "loading"
        assert recordings[-1]["candidates"][0]["recording_id"] == PROOFREAD
        assert recordings[-1]["selected_id"] == PROOFREAD
        session.configure("auto", 2, generation=1, choice_id=PROOFREAD, choice_request_id=1)
        assert settle(session, [])["lyrics"]["recording_id"] == PROOFREAD
    finally:
        release.set()
    future = session.discovery_pending[0]
    if offline:
        with pytest.raises(LookupFailure):
            future.result(timeout=2)
    else:
        future.result(timeout=2)
    session.tick(lambda _: None)
    assert session.candidates[0].reference == PROOFREAD
    assert len(session.candidates) == (1 if offline else 30)
    assert len({c.reference for c in session.candidates}) == len(session.candidates)
    assert session.discovery_status == ("error" if offline else "ready")


def test_stale_partial_discovery_cannot_add_another_songs_source(worker):
    session, _, _ = worker
    old_context = session.context
    token = Cancellation(session.cancelled)
    session.local_discovery.put((old_context, token, curated.curated_candidates(TRACK)))
    session.update_track(replace(TRACK, title="Other song"), 2)
    session.tick(lambda _: None)
    assert not session.candidates


def test_failed_proofread_refresh_retains_already_displayed_content(worker, monkeypatch):
    session, fetch, selected_fetch = worker
    session.choices.set(TRACK, PROOFREAD)
    before = settle(session, [])["lyrics"]
    monkeypatch.setattr(curated, "_recordings", lambda: ())
    session.configure("auto", 1, generation=1, retry=True)
    assert settle(session, [])["lyrics"] == before
    assert session.choices.get(TRACK) == PROOFREAD
    fetch.assert_not_called()
    selected_fetch.assert_not_called()
