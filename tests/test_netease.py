import json
import subprocess
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import pytest

from lyrics_pro.lyrics import (
    NetEaseProvider as LyricsProvider, candidate_from_record, credits_match, decode_record,
    matches, request_json, response_items,
)
from lyrics_pro.models import LookupFailure, Playback


TRACK = Playback("playing", "浮誇", "Eason Chan", "U 87", 284)
TIMED = {"code": 200, "lrc": {"lyric": "[00:10.00]測試\n[00:20.00]第二行"}}


def song(**changes):
    return dict(id=66282, name="浮夸", artists=[{"name": "陈奕迅"}],
                album={"name": "U87"}, duration=283520) | changes


def result(key, values):
    return {"code": 200, "result": {key: values}}


def test_candidate_normalizes_both_response_shapes():
    search = candidate_from_record(song())
    album = candidate_from_record({"id": 66282, "name": "浮夸", "ar": [{"name": "陈奕迅"}],
                                   "dt": 283520}, "U87")
    assert search == album
    assert search.duration == 283.52
    assert matches(search, TRACK)
    assert matches(candidate_from_record(song(duration=286000)), TRACK)


@pytest.mark.parametrize("changes", [
    {"duration": 287000}, {"name": "浮夸 (Live)"}, {"name": "浮夸 (Remix)"},
    {"artists": [{"name": "Another singer"}]},
    {"artists": [{"name": "陈奕迅"}, {"name": "Another singer"}]},
])
def test_wrong_recordings_rejected(changes):
    assert not matches(candidate_from_record(song(**changes)), TRACK)


@pytest.mark.parametrize("changes", [
    {"duration": float("nan")}, {"duration": -1}, {"duration": None},
    {"duration": True}, {"id": "66282"}, {"id": True}, {"name": None},
    {"album": "bad"}, {"artists": []}, {"artists": [{"name": None}]},
])
def test_bad_metadata_skipped(changes):
    assert candidate_from_record(song(**changes)) is None


def test_artist_arrays_and_aliases():
    assert credits_match(("伍佰", "China Blue"), "Wu Bai & China Blue")
    assert credits_match(("陈奕迅",), "Chan, Eason")
    assert not credits_match(("陈奕迅", "Guest"), "Eason Chan")


def test_search_uses_chinese_alias_then_returns_timed_lyrics():
    calls = []

    def fetch(endpoint, params):
        calls.append((endpoint, params))
        if endpoint == "search/get":
            assert params == {"s": "浮夸 陈奕迅", "type": 1, "limit": 30, "offset": 0}
            return result("songs", [song()])
        assert endpoint == "song/lyric" and params["id"] == 66282
        return TIMED

    lyrics = LyricsProvider(fetch).lookup(TRACK)
    assert lyrics.synced and len(lyrics.lines) == 2
    assert lyrics.source == "NetEase https://music.163.com/song?id=66282"
    assert len(calls) == 2


def test_original_query_retry():
    queries = []

    def fetch(endpoint, params):
        if endpoint == "song/lyric":
            return TIMED
        queries.append(params["s"])
        return result("songs", [song()] if params["s"] == "浮誇 Eason Chan" else [])

    assert LyricsProvider(fetch).lookup(TRACK).synced
    assert queries == ["浮夸 陈奕迅", "浮誇 Eason Chan"]


def test_search_prefers_album_then_duration():
    ids = []

    def fetch(endpoint, params):
        if endpoint == "search/get":
            return result("songs", [song(id=1, duration=284000, album={"name": "Compilation"}),
                                    song(id=2, duration=285500), song(id=3, duration=284000)])
        ids.append(params["id"])
        return TIMED

    assert LyricsProvider(fetch).lookup(TRACK).synced
    assert ids == [3]


def test_tian_xia_album_lookup_rejects_live_search_result():
    track = Playback("playing", "天下無雙", "Eason Chan", "我的快樂時代", 260.706)
    calls = []

    def fetch(endpoint, params):
        calls.append((endpoint, params))
        if endpoint == "search/get" and params["type"] == 1:
            # Similar duration must not make a live version acceptable.
            return result("songs", [song(name="天下无双 (Live)", duration=260706)])
        if endpoint == "search/get":
            assert params["s"] == "我的快乐时代"
            return result("albums", [
                {"id": 1, "name": "我的快乐时代", "artist": {"name": "Cover artist"}},
                {"id": 2374013, "name": "我的快乐时代", "artist": {"name": "陈奕迅"}},
            ])
        if endpoint == "v1/album/2374013":
            return {"code": 200, "songs": [
                {"id": 26075149, "name": "天下无双", "ar": [{"name": "陈奕迅"}], "dt": 260706},
            ]}
        assert endpoint == "song/lyric" and params["id"] == 26075149
        return TIMED

    lyrics = LyricsProvider(fetch).lookup(track)
    assert lyrics.synced and "26075149" in lyrics.source
    assert len([c for c in calls if c[0] == "song/lyric"]) == 1


def test_plain_result_retained_but_timed_album_result_preferred():
    def fetch(endpoint, params):
        if endpoint == "search/get":
            if params["type"] == 1:
                return result("songs", [song()])
            return result("albums", [{"id": 10, "name": "U87", "artist": {"name": "陈奕迅"}}])
        if endpoint.startswith("v1/album/"):
            return {"songs": [song(), song(id=2)]}
        return TIMED if params["id"] == 2 else {"lrc": {"lyric": "純文字"}}

    assert LyricsProvider(fetch).lookup(TRACK).synced


def test_album_lookup_precedes_compilation_with_similar_duration():
    ids = []

    def fetch(endpoint, params):
        if endpoint == "search/get":
            if params["type"] == 1:
                return result("songs", [song(id=1, album={"name": "Compilation"})])
            return result("albums", [{"id": 10, "name": "U87", "artist": {"name": "陈奕迅"}}])
        if endpoint.startswith("v1/album/"):
            return {"songs": [song(id=2)]}
        ids.append(params["id"])
        return TIMED

    assert LyricsProvider(fetch).lookup(TRACK).synced
    assert ids == [2]


def test_compilation_is_still_available_if_album_lookup_misses():
    def fetch(endpoint, params):
        if endpoint == "song/lyric":
            return TIMED
        return result("songs", [song(album={"name": "Compilation"})]) if params["type"] == 1 else result("albums", [])

    assert LyricsProvider(fetch).lookup(TRACK).synced


def test_plain_result_survives_optional_lookup_failure():
    def fetch(endpoint, params):
        if endpoint == "song/lyric":
            return {"lrc": {"lyric": "純文字"}}
        if params["s"] == "浮夸 陈奕迅":
            return result("songs", [song()])
        raise LookupFailure("network error", retryable=True)

    assert not LyricsProvider(fetch).lookup(TRACK).synced


def test_bounded_searches_and_deduplicated_lyric_candidates():
    calls = []

    def fetch(endpoint, params):
        calls.append((endpoint, params))
        if endpoint == "search/get" and params["type"] == 1:
            return result("songs", [song(id=n) for n in [1, 1, 2, 3, 4, 5]])
        if endpoint == "search/get":
            return result("albums", [{"id": n, "name": "U87", "artist": {"name": "陈奕迅"}}
                                      for n in range(1, 10)])
        if endpoint.startswith("v1/album/"):
            return {"songs": [song(id=1), song(id=100 + int(endpoint.split("/")[-1]))]}
        return {"uncollected": True}

    assert LyricsProvider(fetch).lookup(TRACK) is None
    assert [p["id"] for e, p in calls if e == "song/lyric"] == [1, 2, 3, 101, 102, 103]
    assert len([e for e, _ in calls if e.startswith("v1/album/")]) == 3


@pytest.mark.parametrize("record", [{}, {"uncollected": True}, {"lrc": {"lyric": ""}},
                                     {"lrc": {"lyric": "[ar:Artist]\n[00:00.00]"}}])
def test_missing_lyrics_not_instrumental(record):
    assert decode_record(record, 1) is None


def test_instrumental_and_plain_lyrics():
    assert decode_record({"nolyric": True}, 1).instrumental
    lyrics = decode_record({"lrc": {"lyric": "[ar:Artist]\n測試\n第二行"}}, 1)
    assert not lyrics.synced and [line.text for line in lyrics.lines] == ["測試", "第二行"]


@pytest.mark.parametrize("data", [{"lrc": []}, {"lrc": {"lyric": ["bad"]}}])
def test_malformed_lyrics(data):
    with pytest.raises(LookupFailure):
        decode_record(data, 1)


def test_malformed_search_results():
    with pytest.raises(LookupFailure):
        response_items({"result": {"songs": "invalid"}}, "songs", search=True)
    assert LyricsProvider(lambda *args: None).lookup(TRACK) is None


@pytest.mark.parametrize("code,retryable", [(429, True), (503, True), (301, False), (400, False), (None, True)])
def test_netease_api_error_codes(code, retryable):
    body = json.dumps({"code": code}) + "\n200"
    with patch("lyrics_pro.lyrics.transport.run_curl", return_value=subprocess.CompletedProcess([], 0, body, "")):
        with pytest.raises(LookupFailure) as error:
            request_json("search/get", {})
        assert error.value.retryable == retryable


@pytest.mark.parametrize("body", ["<html>error</html>", "[]"])
def test_invalid_http_200_responses(body):
    with patch("lyrics_pro.lyrics.transport.run_curl", return_value=subprocess.CompletedProcess([], 0, body + "\n200", "")):
        with pytest.raises(LookupFailure):
            request_json("search/get", {})


def test_only_netease_urls_and_encoded_query_parameters():
    response = subprocess.CompletedProcess([], 0, '{"code":200}\n200', "")
    with patch("lyrics_pro.lyrics.transport.run_curl", return_value=response) as curl:
        assert request_json("search/get", {"s": "伍佰 & China Blue"}) == {"code": 200}
    command = curl.call_args.args[0]
    url = urlparse(command[-1])
    assert url.scheme == "https" and url.netloc == "music.163.com"
    assert url.path == "/api/search/get"
    assert parse_qs(url.query)["s"] == ["伍佰 & China Blue"]
    assert command[command.index("--referer") + 1] == "https://music.163.com/"
    with pytest.raises(ValueError):
        request_json("https://other.example/lyrics", {})
