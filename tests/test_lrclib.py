import json
import subprocess
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from lyrics_pro.lyrics import LRCLIBProvider, decode_lrclib, lrclib_request_json
from lyrics_pro.models import LookupFailure, Playback


TRACK = Playback("playing", "浮誇", "Eason Chan", "U87", 284)


def record(**changes):
    return dict(id=1, trackName="浮誇", artistName="陈奕迅", albumName="U87", duration=284,
                syncedLyrics="[00:10.00]測試\n[00:20.00]下一行", plainLyrics="測試\n下一行") | changes


def test_metadata_lookup_can_return_without_search():
    def fetch(endpoint, params):
        assert endpoint == "get"
        assert params == dict(track_name="浮誇", artist_name="Eason Chan", album_name="U87", duration=284)
        return record()

    lyrics = LRCLIBProvider(fetch).lookup(TRACK)
    assert lyrics.synced and len(lyrics.lines) == 2 and lyrics.source.endswith("/1")


def test_search_matches_aliases_spelling_and_prefers_album():
    queries = []

    def fetch(endpoint, params):
        queries.append((endpoint, params))
        if endpoint == "get":
            return None
        if params["track_name"] == "浮誇":
            return []
        return [record(id=2, albumName="Compilation"), record(id=3, trackName="浮夸", duration=285)]

    lyrics = LRCLIBProvider(fetch).lookup(TRACK)
    assert lyrics.source.endswith("/3")
    assert [p["track_name"] for e, p in queries if e == "search"] == ["浮誇", "浮夸"]


@pytest.mark.parametrize("changes", [{"artistName": "Cover artist"}, {"trackName": "浮誇 (Live)"},
                                     {"trackName": "浮誇 (Remix)"}, {"duration": 287},
                                     {"duration": float("nan")}, {"duration": True}, {"id": None}])
def test_wrong_or_invalid_recording_is_rejected(changes):
    def fetch(endpoint, params):
        return record(**changes) if endpoint == "get" else [record(**changes)]
    assert LRCLIBProvider(fetch).lookup(TRACK) is None


def test_search_improves_plain_result_to_timed():
    provider = LRCLIBProvider(lambda endpoint, params: record(syncedLyrics=None)
                             if endpoint == "get" else [record(id=2)])
    assert provider.lookup(TRACK).synced


@pytest.mark.parametrize("failure", [False, True])
def test_plain_result_is_retained_when_search_cannot_improve_it(failure):
    def fetch(endpoint, params):
        if endpoint == "get":
            return record(syncedLyrics=None)
        if failure:
            raise LookupFailure("network timeout", retryable=True)
        return []
    assert not LRCLIBProvider(fetch).lookup(TRACK).synced


def test_missing_and_instrumental_are_distinct():
    assert decode_lrclib(record(instrumental=True), 1).instrumental
    assert decode_lrclib(record(syncedLyrics=None, plainLyrics=None), 1) is None


def test_invalid_lyrics_are_an_error():
    with pytest.raises(LookupFailure):
        decode_lrclib(record(syncedLyrics=["bad"]), 1)


def test_search_results_are_bounded():
    calls = []

    def fetch(endpoint, params):
        calls.append(endpoint)
        return None if endpoint == "get" else [record(id=i + 1, duration=400) for i in range(20)] + [record()]

    assert LRCLIBProvider(fetch).lookup(TRACK) is None
    assert len(calls) == 3  # exact lookup, traditional search, simplified search


def test_transport_uses_lrclib_without_netease_headers():
    response = subprocess.CompletedProcess([], 0, json.dumps(record()) + "\n200", "")
    with patch("lyrics_pro.lyrics.run_curl", return_value=response) as curl:
        assert lrclib_request_json("get", {"artist_name": "伍佰 & China Blue"}) == record()
    command = curl.call_args.args[0]
    url = urlparse(command[-1])
    assert url.netloc == "lrclib.net" and url.path == "/api/get"
    assert parse_qs(url.query)["artist_name"] == ["伍佰 & China Blue"]
    assert "--referer" not in command
    with pytest.raises(ValueError):
        lrclib_request_json("https://another.example", {})


@pytest.mark.parametrize("endpoint,body", [("get", []), ("search", {}), ("get", "bad JSON"), ("get", "null")])
def test_invalid_responses(endpoint, body):
    payload = body if isinstance(body, str) else json.dumps(body)
    response = subprocess.CompletedProcess([], 0, payload + "\n200", "")
    with patch("lyrics_pro.lyrics.run_curl", return_value=response):
        with pytest.raises(LookupFailure):
            lrclib_request_json(endpoint, {})
