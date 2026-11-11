"""Regression checks for the reviewed resource integration, offline only."""
import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from lyrics_pro import curated
from lyrics_pro.models import Playback
from lyrics_pro.pronunciation import Romanizer, choose_language
from scripts.prepare_wubai import ROOT, audit, make_asset, read_review


def song(title):
    catalog = json.loads((ROOT / "manifest.json").read_text())
    entry = next(e for e in catalog["songs"] if e["title"] == title)
    return read_review(ROOT / entry["id"])


def test_entire_reviewed_collection_is_reproducible_and_matches_runtime():
    ready = audit()
    assert len(ready) == 51
    catalog = json.loads((ROOT / "manifest.json").read_text())
    assert len(catalog["songs"]) == 53
    assert [e["title"] for e in catalog["songs"] if e["status"] == "needs timing"] == ["恨世生"]
    curated._recordings.cache_clear()
    for entry in catalog["songs"]:
        if entry["status"] != "ready":
            continue
        review, manual, timed = read_review(ROOT / entry["id"])
        asset = make_asset(review, manual, timed)
        track = Playback("paused", asset["title"], "Unrecognized artist", "Compilation", asset["duration"])
        lyrics = curated.curated_lyrics(track)
        assert lyrics and lyrics.recording_id == "proofread:" + entry["id"]
        assert [line.time for line in lyrics.lines] == [row["time"] for row in timed["lines"]]
        assert choose_language("Unknown", "auto", lyrics)[0] == "hokkien"
        assert Romanizer().annotate(lyrics, "hokkien") is lyrics
        for alias in asset["title_aliases"]:
            assert curated.curated_lyrics(replace(track, title=alias)) == lyrics
        assert curated.curated_lyrics(replace(track, duration=asset["duration"] + 2.01)) is None
        assert curated.curated_lyrics(track, review["recording"]["reference"]) is None


def test_known_title_alias_does_not_globally_loosen_live_or_remix_matching():
    review, manual, timed = song("煞到妳")
    asset = make_asset(review, manual, timed)
    track = Playback("paused", "煞到你", "", "", asset["duration"])
    assert curated.curated_lyrics(track)
    assert curated.curated_lyrics(replace(track, title="煞到你 (Remix)")) is None
    assert curated.curated_lyrics(replace(track, title="煞到你 (Live)")) is None


@pytest.mark.parametrize("aliases", ["煞到你", None, [""], [123], [" "] * 13])
def test_invalid_aliases_are_rejected(aliases):
    review, manual, timed = song("煞到妳")
    asset = make_asset(review, manual, timed)
    asset["title_aliases"] = aliases
    with pytest.raises(ValueError, match="title aliases"):
        curated._decode_asset(json.dumps(asset))


def test_source_backed_repairs_are_required_and_original_transcript_is_untouched():
    review, manual, timed = song("台北孤兒")
    raw = Path(review["source_path"]).read_text()
    assert "提起" in raw.splitlines()[21] and " 是 " in raw.splitlines()[3]
    asset = make_asset(review, manual, timed)
    assert any("thê-khí" in r["spelling"] for r in asset["alignment"]["rows"])
    unpatched = copy.deepcopy(manual)
    unpatched["repairs"] = []
    with pytest.raises(ValueError, match="Unsupplied"):
        make_asset(review, unpatched, timed)
    changed = copy.deepcopy(manual)
    changed["blocks"][0]["spelling"] += " invented"
    with pytest.raises(ValueError, match="Unsupplied"):
        make_asset(review, changed, timed)


def test_missing_fragment_and_gap_replacement_cannot_be_bundled():
    review, manual, timed = song("飛")
    review["assignments"][0]["manual_ids"] = ["missing"]
    with pytest.raises(ValueError, match="Missing supplied fragment"):
        make_asset(review, manual, timed)
    review, manual, timed = song("飛")
    index = next(i for i, r in enumerate(timed["lines"]) if r["kind"] == "gap")
    review["assignments"][index].update(kind="lyric", manual_ids=review["assignments"][0]["manual_ids"])
    with pytest.raises(ValueError, match="musical gap"):
        make_asset(review, manual, timed)


def test_uncovered_unique_phrase_is_rejected():
    review, manual, timed = song("海上的島")
    first = next(i for i, a in enumerate(review["assignments"]) if a["kind"] == "lyric")
    review["assignments"][first]["manual_ids"] = review["assignments"][first+1]["manual_ids"]
    with pytest.raises(ValueError, match="Unassigned"):
        make_asset(review, manual, timed)


def test_timing_identity_and_review_approval_are_mandatory():
    review, manual, timed = song("飛")
    review["approved"] = False
    with pytest.raises(ValueError, match="explicit text review"):
        make_asset(review, manual, timed)
    review["approved"] = True
    timed["recording_id"] = "lrclib:1"
    with pytest.raises(ValueError, match="Timing provenance"):
        make_asset(review, manual, timed)


def test_review_hashes_prevent_using_changed_frozen_inputs(tmp_path):
    review, manual, timed = song("飛")
    for name, obj in [("review", review), ("manual", manual), ("timed", timed)]:
        (tmp_path / (name + ".json")).write_text(json.dumps(obj))
    with pytest.raises(ValueError, match="changed manual input"):
        read_review(tmp_path)


def test_repeat_variants_stay_at_their_reviewed_occurrences():
    review, manual, timed = song("快樂的等待")
    rows = make_asset(review, manual, timed)["alignment"]["rows"]
    assert "做的夢" in next(r["text"] for r in rows if r["time"] == 72.95)
    assert "酸的心" in next(r["text"] for r in rows if r["time"] == 183.98)
    review, manual, timed = song("汝是我的心肝")
    rows = make_asset(review, manual, timed)["alignment"]["rows"]
    assert rows[10]["text"].startswith("讓我")
    assert rows[24]["text"].startswith("就算海水")
    assert rows[13]["text"].startswith("嗚")


def test_original_hawaii_recording_does_not_match_wu_bai_live_durations():
    track = Playback("paused", "來去夏威夷", "Unknown", "", 204.033)
    assert curated.curated_lyrics(track)
    for duration in (91.4, 201.192):
        assert curated.curated_lyrics(replace(track, duration=duration)) is None
