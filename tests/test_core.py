import json
import subprocess
import sys
from threading import Event
from unittest.mock import patch

import pytest

from lyrics_pro.cli import safe_text
from lyrics_pro.follow import Follower
from lyrics_pro.lyrics import parse_lrc, plain_lines, request_json, run_curl
from lyrics_pro.models import LookupFailure, LyricLine, Lyrics, Playback
from lyrics_pro.music import MusicError, read_playback
from lyrics_pro.pronunciation import Romanizer, choose_language


TRACK = Playback("playing", "浮誇", "陳奕迅", "U 87", 284, 12)


def test_lrc_repeats_offsets_and_duplicate_timestamps():
    lines = parse_lrc("[ar:Artist]\n[offset:-500]\n[00:10.00][00:30.5]A\n[00:10.00]B\n[00:10.00]A\n[00:12.123]\ninvalid")
    assert [(line.time, line.text) for line in lines] == [(10.5, "A / B"), (12.623, ""), (31, "A")]


def test_lrc_bad_lines_are_ignored():
    assert parse_lrc("[00:99]bad\n[album:hello]\ntext [00:10]bad") == ()


def test_plain_lines_skip_tag_only_rows_and_keep_text():
    lines = plain_lines("[ar:Artist]\n  First  \n\n[00:10.00] [00:12]\nSecond [x]\n")
    assert lines == (LyricLine("First"), LyricLine("Second [x]"))


def test_follow_pause_seek_and_mid_song_start():
    lyrics = Lyrics(tuple(LyricLine(str(t), t) for t in (10, 20, 30)), "test", True)
    follower = Follower(lyrics)
    assert follower.update(25)[0].text == "20"
    assert follower.update(25) == ()  # paused
    assert follower.update(26) == ()
    assert follower.update(35)[0].text == "30"
    assert follower.update(12)[0].text == "10"  # backwards
    assert follower.update(1) == ()  # intro
    assert follower.update(11)[0].text == "10"


def test_plain_prints_once():
    follower = Follower(Lyrics((LyricLine("A"), LyricLine("B")), "test", False))
    assert len(follower.update(20)) == 2
    assert follower.update(5) == ()


@pytest.mark.parametrize("artist,expected", [("陈奕迅", "cantonese"), ("Chan, Eason", "cantonese"),
                                             ("伍佰 & China Blue", "hokkien"), ("Wu Bai", "hokkien"),
                                             ("Unknown", None)])
def test_explicit_language_ignores_artist(artist, expected):
    assert choose_language(artist, "cantonese")[0] == "cantonese"
    assert choose_language(artist, "hokkien") == ("hokkien", "explicit override")


@pytest.mark.parametrize("status,retryable", [("429", True), ("503", True), ("403", False)])
def test_http_failure(status, retryable):
    with patch("lyrics_pro.lyrics.transport.run_curl", return_value=subprocess.CompletedProcess([], 0, "{}\n" + status, "")):
        with pytest.raises(LookupFailure) as error:
            request_json("search/get", {})
        assert error.value.retryable == retryable


def test_request_timeout_and_404():
    with patch("lyrics_pro.lyrics.transport.run_curl", side_effect=subprocess.TimeoutExpired("curl", 17)):
        with pytest.raises(LookupFailure) as error:
            request_json("search/get", {})
        assert error.value.retryable
    with patch("lyrics_pro.lyrics.transport.run_curl", return_value=subprocess.CompletedProcess([], 0, "{}\n404", "")):
        assert request_json("search/get", {}) is None


def test_cancel_terminates_inflight_process():
    cancelled = Event()
    original_popen = subprocess.Popen
    processes = []

    def launch(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        processes.append(process)
        cancelled.set()
        return process

    with patch("lyrics_pro.lyrics.transport.subprocess.Popen", side_effect=launch):
        with pytest.raises(LookupFailure, match="cancelled"):
            run_curl([sys.executable, "-c", "import time; time.sleep(30)"], cancelled)
    assert processes[0].poll() is not None


def test_music_closed_and_structured_metadata():
    for data in ({"state": "closed"}, TRACK.__dict__ | {"title": 'Title, with "quotes"\nand newline'}):
        with patch("lyrics_pro.music.subprocess.run", return_value=subprocess.CompletedProcess([], 0, json.dumps(data), "")):
            assert read_playback() == Playback(**data)


def test_music_permission_denied():
    with patch("lyrics_pro.music.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "Not authorized (-1743)")):
        with pytest.raises(MusicError, match="System Settings"):
            read_playback()


def test_romanization_local_and_unknown_reading():
    romanizer = Romanizer()
    assert "ngo5" in romanizer.line("我想學唱歌", "cantonese")
    assert "gua2" in romanizer.line("我欲學唱歌", "hokkien").lower()
    with patch("ToJyutping.get_jyutping_list", return_value=[("龘", None)]):
        assert romanizer.line("龘", "cantonese") == "[龘: ?]"
    lyrics = Lyrics((LyricLine("我", 10),), "test", True)
    result = romanizer.annotate(lyrics, "cantonese")
    assert result.lines[0].text == "我"
    assert result.lines[0].time == 10
    assert romanizer.annotate(lyrics, None) is lyrics


def test_terminal_control_characters_are_removed():
    assert "\x1b" not in safe_text("hello\x1b[2J")
    assert "\r" not in safe_text("hi\rthere")
