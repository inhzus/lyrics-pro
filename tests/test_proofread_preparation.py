"""Offline tests: no live providers, Music access, or synthesized pronunciation."""
import json
from pathlib import Path
from threading import Event

import pytest

from scripts import prepare_proofread as prep
from scripts.proofread_alignment import align
from lyrics_pro.curated import _decode_asset
from lyrics_pro.models import LookupCancelled, LookupFailure
from lyrics_pro.pronunciation import resolve_language, supplied_annotation
from lyrics_pro.recording_ref import source_ref


def inputs(blocks, texts):
    manual = dict(recording_id="netease:1", source="Test supplied input", blocks=[
        dict(id=str(i), text=text, spelling=reading) for i, (text, reading) in enumerate(blocks)])
    timed = dict(recording_id="netease:1", source="NetEase https://music.163.com/song?id=1",
                 lines=[dict(time=i * 5, text=text, kind="gap" if not text else "lyric") for i, text in enumerate(texts)])
    return manual, timed


def test_parser_preserves_accents_columns_and_credits():
    raw = "作詞：甲 台語拼音：乙\n\n心內話\t\t無人聽\nSim-lāi-uē    bô lâng thiann\n"
    parsed = prep.parse_transcription(raw)
    assert not parsed["reasons"]
    assert parsed["credits"][0]["line"] == 1
    block = parsed["blocks"][0]
    assert block["text"] == "心內話\t\t無人聽"
    assert block["parts"] == [dict(text="心內話", spelling="Sim-lāi-uē"), dict(text="無人聽", spelling="bô lâng thiann")]
    assert block["source_lines"] == [3, 4]


@pytest.mark.parametrize("header", ["詞曲：某人 台羅拼音：某人", "作詞 某人 ： 作曲 佚名 ： 台語拼音：某人"])
def test_combined_and_named_credit_headers_remain_attributed(header):
    parsed = prep.parse_transcription(header + "\n甲\ná")
    assert not parsed["reasons"]
    assert parsed["credits"] == [dict(line=1, text=header)]
    assert parsed["blocks"][0]["source_lines"] == [2, 3]


@pytest.mark.parametrize("text,reason", [
    ("甲\na\n甲\nb", "conflicting_spellings_for_repeated_text"),
    ("甲\na\n乙", "unpaired_line:3"),
    ("hello\nworld", "ambiguous_pair:1,2"),
    ("甲\na\nNote: live version", "source_note_requires_review:3"),
])
def test_parser_does_not_silently_discard_ambiguous_content(text, reason):
    assert reason in prep.parse_transcription(text)["reasons"]


def test_mismatched_columns_stay_whole():
    block = prep.parse_transcription("甲    乙\na b")["blocks"][0]
    assert "parts" not in block
    manual, timed = inputs([(block["text"], block["spelling"])], ["甲", "乙"])
    assert not prep.promotable(prep.strict_alignment(manual, timed), 20)


@pytest.mark.parametrize("name,title", [
    ("15 － 何時再見夢中人-伍佰", "何時再見夢中人"),
    ("無聲的所在-03-無聲的所在-伍佰", "無聲的所在"),
    ("9453-玖壹壹", "9453"), ("8+9-玖壹壹", "8+9"),
])
def test_track_prefixes_do_not_remove_numeric_titles(name, title):
    assert prep.metadata(name)[0] == title
    assert not prep.metadata(name)[2]


def test_artist_prefixes_are_flagged_before_lookup():
    title, artist, reasons = prep.metadata("法蘭黛樂團 (Frandé) – 桂花巷-法蘭黛樂團")
    assert title == "法蘭黛樂團 (Frandé) – 桂花巷" and artist == "法蘭黛樂團"
    assert reasons == ["artist_prefix_in_title_requires_override"]


def test_reviewed_metadata_override_changes_query_without_editing_source(tmp_path, monkeypatch):
    path = tmp_path / "歌手 (Artist) – 歌-歌手"
    path.write_text("甲\na")
    before = path.read_bytes()
    calls = []
    monkeypatch.setattr(prep, "discover", lambda title, artist, _: calls.append((title, artist)) or ([], [], []))
    result = prep.process(path, tmp_path / "out", prep.Snapshots(tmp_path / "snapshots"),
                          override={"title": "歌", "artist": "歌手 & 另一人"})
    assert calls == [("歌", "歌手 & 另一人")]
    assert result["metadata_override"] == {"title": "歌", "artist": "歌手 & 另一人"}
    assert path.read_bytes() == before


def test_exact_merges_preserve_source_events_and_supplied_readings():
    manual, timed = inputs([("甲", "a"), ("乙", "b"), ("丙", "c")], ["", "甲乙", "丙", ""])
    report = prep.strict_alignment(manual, timed)
    assert prep.promotable(report, 30)
    assert [r["time"] for r in report["rows"]] == [r["time"] for r in timed["lines"]]
    assert report["rows"][1]["text"] == "甲 乙"
    assert report["rows"][1]["spelling"] == "a b"


def test_explicit_three_column_split_and_repeats():
    manual, timed = inputs([("甲乙丙", "a b c"), ("歌", "kua"), ("歌", "kua")], ["甲", "乙", "丙", "歌", "歌", "歌"])
    manual["blocks"][0]["parts"] = [dict(text=t, spelling=s) for t, s in zip("甲乙丙", "abc")]
    report = prep.strict_alignment(manual, timed)
    assert prep.promotable(report, 30)
    assert report["summary"] == {"exact": 3, "repeat": 3}


def test_repeated_adjacent_pairs_can_share_one_online_timestamp():
    manual, timed = inputs([("甲", "a"), ("乙", "b"), ("甲", "a"), ("乙", "b")], ["甲乙", "甲乙", "甲乙"])
    report = prep.strict_alignment(manual, timed)
    assert prep.promotable(report, 30)
    assert report["summary"] == {"repeat": 3}
    assert all(row["text"] == "甲 乙" and row["spelling"] == "a b" for row in report["rows"])


def test_missing_manual_content_approximation_and_duplicate_stamps_block_promotion():
    for blocks, texts in [([("甲乙", "a b")], ["甲丙"]),
                          ([("甲", "a"), ("乙", "b")], ["甲"]),
                          ([("甲", "a")], ["甲", "乙"])]:
        manual, timed = inputs(blocks, texts)
        assert not prep.promotable(prep.strict_alignment(manual, timed), 20)
    manual, timed = inputs([("甲", "a"), ("乙", "b")], ["甲", "乙"])
    timed["lines"][1]["time"] = 0
    assert not prep.promotable(prep.strict_alignment(manual, timed), 20)


def test_original_accepted_experiment_is_reproducible():
    root = Path("resources/lyrics-spelling/shao-nian-eh-an-la")
    report = align(json.loads((root / "proofread.json").read_text()), json.loads((root / "timed.json").read_text()))
    accepted = json.loads(Path("src/lyrics_pro/data/proofread/shao-nian-eh-an-la.json").read_text())["alignment"]
    assert report["summary"] == accepted["summary"]
    assert report["rows"] == accepted["rows"]
    assert report["boundary_warnings"] == accepted["boundary_warnings"]


def test_snapshots_resume_without_network_and_honor_cancellation(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(prep.providers, "request_json", lambda *args: calls.append(args) or {"code": 200})
    store = prep.Snapshots(tmp_path)
    assert store.request("netease", "search/get", {"s": "test"}) == {"code": 200}
    assert prep.Snapshots(tmp_path).request("netease", "search/get", {"s": "test"}) == {"code": 200}
    assert len(calls) == 1
    saved = dict(root=str(tmp_path), requests=dict(store.trace))
    assert store.unchanged(saved)
    assert not prep.Snapshots(tmp_path / "different").unchanged(saved)
    assert prep.Snapshots(tmp_path, offline=True).request("netease", "search/get", {"s": "test"}) == {"code": 200}
    with pytest.raises(LookupFailure, match="offline mode forbids requests"):
        prep.Snapshots(tmp_path, offline=True).request("netease", "search/get", {"s": "uncached"})
    assert len(calls) == 1
    cancelled = Event()
    cancelled.set()
    with pytest.raises(LookupCancelled):
        prep.Snapshots(tmp_path, cancelled).request("netease", "search/get", {"s": "test"})
    snapshot = next(tmp_path.glob("*.json"))
    payload = json.loads(snapshot.read_text())
    payload["response"] = {"code": 200, "changed": True}
    prep.write_json(snapshot, payload)
    assert not store.unchanged(saved)


def test_failed_snapshots_need_explicit_retry(tmp_path, monkeypatch):
    def fail(*args):
        raise LookupFailure("unavailable", retryable=False)
    monkeypatch.setattr(prep.providers, "request_json", fail)
    with pytest.raises(LookupFailure):
        prep.Snapshots(tmp_path).request("netease", "search/get", {})
    monkeypatch.setattr(prep.providers, "request_json", lambda *args: {"code": 200})
    with pytest.raises(LookupFailure):
        prep.Snapshots(tmp_path).request("netease", "search/get", {})
    assert prep.Snapshots(tmp_path, retry=True).request("netease", "search/get", {}) == {"code": 200}


def test_catalog_discovery_does_not_guess_duration_and_bounds_lyric_requests():
    class Fake:
        def __init__(self): self.calls = []
        def request(self, provider, endpoint, params):
            self.calls.append((provider, endpoint, params))
            if endpoint == "search/get":
                return {"code": 200, "result": {"songs": [dict(id=i, name="歌", artists=[{"name": "歌手"}],
                    album={"name": "專輯"}, duration=120000) for i in range(1, 31)]}}
            assert endpoint == "song/lyric"
            return {"code": 200, "lrc": {"lyric": "[00:10.00]歌"}}
    fake = Fake()
    results, _, errors = prep.discover("歌", "歌手", fake)
    assert not errors and len(results) == 3
    assert all(c.duration == 120 for c, _ in results)
    assert len(fake.calls) == 4


def test_generic_supplied_spelling_and_lrclib_provenance():
    manual, timed = inputs([("甲", "á"), ("乙", "yi")], ["甲", "乙"])
    manual["recording_id"] = timed["recording_id"] = "lrclib:42"
    timed["source"] = "LRCLIB https://lrclib.net/api/get/42"
    report = prep.strict_alignment(manual, timed)
    asset = dict(schema_version=1, id="test", revision="1", title="歌", artist="歌手", album="", duration=20,
                 language="supplied", attribution="Supplied by user", alignment=report)
    raw = _decode_asset(json.dumps(asset)).lyrics
    assert source_ref(timed["source"]) == "lrclib:42"
    assert resolve_language("cantonese", "default", raw)[0] == "supplied"
    assert supplied_annotation(raw, "supplied") is raw
    assert supplied_annotation(raw, "hokkien") is None
    assert all(line.pronunciation is None for line in supplied_annotation(raw, None).lines)


def test_credit_classification_requires_a_label_separator():
    assert prep.CREDIT.match("作詞 : 某人")
    assert not prep.CREDIT.match("作詞的人")
    assert not prep.CREDIT.match("演唱你的歌")


def test_process_freezes_actual_input_hashes_and_flags_recording_ambiguity(tmp_path, monkeypatch):
    source = tmp_path / "歌-歌手"
    source.write_text("甲\ná\n乙\nb\n")
    _, timed = inputs([("甲", "á"), ("乙", "b")], ["甲", "乙"])
    candidate = prep.providers.Candidate(1, "歌", ("歌手",), "專輯", 30)
    choices = [(candidate, timed)]
    monkeypatch.setattr(prep, "discover", lambda *args: (choices, [], []))
    output = tmp_path / "reports"
    result = prep.process(source, output, prep.Snapshots(tmp_path / "snapshots"))
    assert result["status"] == "ready"
    directory = output / result["id"]
    report = json.loads((directory / "alignment.json").read_text())
    assert report["input_sha256"]["manual"] == prep.digest((directory / "proofread.json").read_bytes())
    assert report["input_sha256"]["timed"] == prep.digest((directory / "timed.json").read_bytes())
    shifted = dict(timed, recording_id="netease:2", lines=[dict(r, time=r["time"] + 2) for r in timed["lines"]])
    choices.append((prep.replace(candidate, song_id=2), shifted))
    assert prep.process(source, output, prep.Snapshots(tmp_path / "snapshots"))["status"] == "recording review"


def test_full_review_candidate_beats_a_short_exact_fragment(tmp_path, monkeypatch):
    source = tmp_path / "歌-歌手"
    source.write_text("甲乙丙丁\na\n戊己庚辛\nb\n壬癸子丑\nc")
    _, partial = inputs([], ["甲乙丙丁"])
    _, full = inputs([], ["甲乙丙丁", "戊己庚申", "壬癸子丑"])
    full.update(recording_id="netease:2", source="NetEase https://music.163.com/song?id=2")
    candidate = prep.providers.Candidate(1, "歌", ("歌手",), "", 30)
    monkeypatch.setattr(prep, "discover", lambda *args: ([(candidate, partial), (prep.replace(candidate, song_id=2), full)], [], []))
    result = prep.process(source, tmp_path / "out", prep.Snapshots(tmp_path / "snapshots"))
    assert result["status"] == "alignment review"
    assert result["recording_id"] == "netease:2"
    assert "approximate_rows:1" in result["reasons"]


def test_promotion_refuses_overlapping_title_duration_matches(tmp_path):
    manual, timed = inputs([("甲", "a")], ["甲"])
    asset = dict(schema_version=1, id="one", revision="1", title="歌", artist="歌手", album="", duration=30,
                 language="supplied", attribution="User", alignment=prep.strict_alignment(manual, timed))
    output, bundled = tmp_path / "reports", tmp_path / "bundled"
    result = dict(status="ready", id="one", asset_id="one")
    prep.write_json(output / "one" / "asset.json", asset)
    assert prep.promote(result, output, bundled) == result
    assert prep.promote(result, output, bundled) == result  # idempotent
    second = dict(asset, id="two", duration=33)
    prep.write_json(output / "two" / "asset.json", second)
    assert prep.promote(dict(result, id="two", asset_id="two"), output, bundled)["status"] == "recording review"
    assert len(list(bundled.glob("*.json"))) == 1


def test_main_resumes_and_reprocesses_only_changed_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(prep.signal, "signal", lambda *args: None)
    source, output = tmp_path / "sources", tmp_path / "reports"
    source.mkdir()
    first = source / "一-歌手"
    first.write_text("甲\na")
    (source / "二-歌手").write_text("乙\nb")
    calls = []
    def process(path, output, snapshots, accepted=None):
        calls.append(path.name)
        return dict(path=str(path), sha256=prep.digest(path.read_bytes()), id=path.name, title=path.name,
                    artist="歌手", attribution=[], status="no timed lyrics", reasons=[], tool_version=prep.VERSION)
    monkeypatch.setattr(prep, "process", process)
    monkeypatch.setattr("sys.argv", ["prepare", "--input", str(source), "--output", str(output)])
    assert prep.main() == 0
    assert len(calls) == 2
    assert prep.main() == 0
    assert len(calls) == 2
    first.write_text("甲\ná")
    assert prep.main() == 0
    assert len(calls) == 3 and calls[-1] == first.name


def test_collection_audit_detects_changed_source_and_unbundled_results(tmp_path, monkeypatch):
    from scripts.verify_proofread_collection import verify
    source, output, bundled = tmp_path / "sources", tmp_path / "reports", tmp_path / "bundled"
    source.mkdir()
    path = source / "歌-歌手"
    path.write_text("甲\na\n乙\nb")
    _, timed = inputs([("甲", "a"), ("乙", "b")], ["甲", "乙"])
    candidate = prep.providers.Candidate(1, "歌", ("歌手",), "", 30)
    monkeypatch.setattr(prep, "discover", lambda *args: ([(candidate, timed)], [], []))
    result = prep.process(path, output, prep.Snapshots(tmp_path / "snapshots"))
    prep.summarize(output, [result])
    with pytest.raises(FileNotFoundError):
        verify(source, output, bundled)
    prep.promote(result, output, bundled)
    assert verify(source, output, bundled)["bundled_assets"] == 1
    path.write_text("甲\nchanged\n乙\nb")
    with pytest.raises(ValueError, match="Changed source"):
        verify(source, output, bundled)


def test_requests_are_spaced_and_cancel_during_rate_wait(tmp_path, monkeypatch):
    class Clock:
        now = 20
    clock = Clock()
    class Cancel:
        stopped = False
        waits = []
        def is_set(self): return self.stopped
        def wait(self, seconds):
            self.waits.append(seconds)
            clock.now += seconds
            return self.stopped
    cancel = Cancel()
    starts = []
    monkeypatch.setattr(prep.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(prep.providers, "request_json", lambda *args: starts.append(clock.now) or {"code": 200})
    store = prep.Snapshots(tmp_path, cancel)
    store.request("netease", "search/get", {"s": "one"})
    store.request("netease", "search/get", {"s": "two"})
    assert starts == [20, 21]
    cancel.stopped = True
    with pytest.raises(LookupCancelled):
        store.request("netease", "search/get", {"s": "three"})
    assert len(starts) == 2
