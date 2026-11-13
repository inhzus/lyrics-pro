import pytest

from lyrics_pro.models import LyricLine, Lyrics
from lyrics_pro.pronunciation import Romanizer, artist_key, native_name


@pytest.mark.parametrize("text", ["令神仙鱼归天要怪谁", "令神仙魚歸天要怪誰"])
def test_reported_line_has_complete_readings_in_both_scripts(text):
    assert Romanizer().line(text, "cantonese") == "ling6 san4 sin1 jyu2 gwai1 tin1 jiu3 gwaai3 seoi4"


def test_full_line_context_selects_different_readings():
    assert Romanizer().line("要求開會 我會唱歌", "cantonese") == "jiu1 kau4 hoi1 wui2 ngo5 wui5 coeng3 go1"


@pytest.mark.parametrize("text,expected", [
    ("你好，Hello 123！", "nei5 hou2，Hello 123！"),
    ("Hello你好123", "Hello nei5 hou2 123"),
    ("（你好）", "（nei5 hou2）"),
    ("你好  Hello\t123！", "nei5 hou2  Hello\t123！"),
    ("", ""),
    ("Hello 123! 🎵", "Hello 123! 🎵"),
])
def test_mixed_text_and_punctuation_are_preserved(text, expected):
    assert Romanizer().line(text, "cantonese") == expected


def test_unknown_character_does_not_hide_surrounding_readings():
    assert Romanizer().line("你𰻞好", "cantonese") == "nei5 [𰻞: ?] hou2"


def test_annotation_preserves_original_lyrics_timing_and_source():
    text = "令神仙鱼归天要怪谁"
    original = Lyrics((LyricLine(text, 21.6),), "NetEase", True)
    annotated = Romanizer().annotate(original, "cantonese")
    assert annotated.source == original.source
    assert annotated.synced == original.synced
    assert annotated.lines[0].text == text
    assert annotated.lines[0].time == 21.6
    assert annotated.lines[0].pronunciation == "ling6 san4 sin1 jyu2 gwai1 tin1 jiu3 gwaai3 seoi4"
    assert original.lines[0].pronunciation is None


def test_hokkien_still_uses_tailo():
    assert Romanizer().line("我欲學唱歌", "hokkien") == "gua2 beh4 oh8 tshiunn3-kua1"


def test_artist_groups_keep_preference_keys_and_expose_native_names():
    # Saved song preferences are keyed by artist_key, so these values must stay stable.
    assert {artist_key(name) for name in ("Eason Chan", "陳奕迅", "陈奕迅", "Chan, Eason")} == {"eason"}
    assert {artist_key(name) for name in ("Wu Bai & China Blue", "伍佰", "China Blue")} == {"wubai"}
    assert artist_key("Unknown Artist") == "unknownartist"
    assert native_name("Eason Chan") == "陳奕迅" and native_name("Wu Bai") == "伍佰"
    assert native_name("Unknown Artist") is None

