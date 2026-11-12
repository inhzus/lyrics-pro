import base64
from dataclasses import replace
from pathlib import Path
import subprocess
from threading import Event
from unittest.mock import Mock, patch

import pytest

from lyrics_pro import artwork as art
from lyrics_pro.models import Playback, LookupFailure, LookupCancelled
from lyrics_pro.music import MusicCancelled

TRACK = Playback("paused", "世界第一等 (Live)", "伍佰 & China Blue", "生命的现场 (Live)", 121)
URL = "https://is1-ssl.mzstatic.com/image/cover.jpg"
ROW = dict(trackName="世界第一等 (Live)", artistName="伍佰 & China Blue",
           collectionName="生命的現場 (Live)", trackTimeMillis=121840, artworkUrl100=URL)


@pytest.mark.parametrize("suffix", ["100x100bb.jpg", "100x100-75.jpg", "100x100.png"])
def test_large_cover_requested_before_thumbnail(suffix):
    url = URL + "/" + suffix + "?keep=this"
    with patch.object(art, "download_cover", return_value="large") as download:
        assert art.download_catalog_cover(url, Event()) == "large"
        assert download.call_count == 1
        assert download.call_args.args[0] == url.replace("/100x100", "/1000x1000")


@pytest.mark.parametrize("failure", [art.ArtworkFailure("image_http_404"),
    art.ArtworkFailure("invalid_image"), art.ArtworkFailure("image_download_failed"),
    subprocess.TimeoutExpired("curl", 17)])
def test_large_cover_failure_uses_original_thumbnail(failure):
    url = URL + "/100x100bb.jpg"
    with patch.object(art, "download_cover", side_effect=[failure, "thumbnail"]) as download:
        assert art.download_catalog_cover(url, Event()) == "thumbnail"
        assert [c.args[0] for c in download.call_args_list] == [url.replace("100x100", "1000x1000"), url]


def test_cancellation_never_starts_thumbnail_fallback():
    with patch.object(art, "download_cover", side_effect=MusicCancelled()) as download:
        with pytest.raises(MusicCancelled):
            art.download_catalog_cover(URL + "/100x100bb.jpg", Event())
        assert download.call_count == 1


def test_unknown_rendition_path_is_preserved():
    with patch.object(art, "download_cover", return_value="original") as download:
        assert art.download_catalog_cover(URL, Event()) == "original"
        assert download.call_args.args[0] == URL


@pytest.fixture(autouse=True)
def no_network():
    with patch.object(art, "http_json", side_effect=AssertionError("Unexpected network")):
        yield


def test_exact_match_simplified_traditional_and_artist_alias():
    assert art.select_cover([ROW], TRACK) == URL
    assert art.select_cover([ROW, ROW], replace(TRACK, artist="Wu Bai")) == URL


@pytest.mark.parametrize("field,value", [("trackName", "世界第一等"), ("trackName", "世界第一等 (Remix)"),
    ("artistName", "刘德华"), ("collectionName", "Compilation"), ("collectionName", ""),
    ("trackTimeMillis", 124000), ("trackTimeMillis", float("nan")), ("trackTimeMillis", True)])
def test_mismatch_rejected(field, value):
    assert art.select_cover([ROW | {field: value}], TRACK) is None


def test_ambiguity_and_query_bounds():
    with pytest.raises(art.ArtworkFailure, match="ambiguous"):
        art.select_cover([ROW, ROW | dict(artworkUrl100=URL + "?different")], TRACK)
    assert art.select_cover([{}] * 50 + [ROW], TRACK) is None


@pytest.mark.parametrize("url", ["http://is1-ssl.mzstatic.com/a", "https://mzstatic.com.evil.test/a",
    "https://example.com/a", "https://user@is1-ssl.mzstatic.com/a", "https://is1-ssl.mzstatic.com:88/a", None])
def test_untrusted_image_urls_rejected(url):
    assert not art.apple_image_url(url)


def test_catalog_storefront_fallback_and_no_match():
    with patch.object(art, "http_json", side_effect=[{"results": []}, {"results": [ROW]}]) as http, \
            patch.object(art, "download_cover", return_value="cover") as download:
        assert art.catalog_artwork(TRACK, Event()) == "cover"
        assert "country=tw" in http.call_args_list[0].args[0]
        assert "country=us" in http.call_args_list[1].args[0]
        download.assert_called_once()
    with patch.object(art, "http_json", return_value={"results": []}) as http:
        assert art.catalog_artwork(TRACK, Event()) is None
        assert http.call_count == 2
        assert art.catalog_artwork(replace(TRACK, album=""), Event()) is None
        assert http.call_count == 2


def test_local_success_skips_catalog_and_missing_uses_it():
    with patch.object(art, "read_local_artwork", return_value="aW1hZ2U="):
        assert art.read_artwork(TRACK, Event()) == "aW1hZ2U="
    with patch.object(art, "read_local_artwork", return_value=None), \
            patch.object(art, "catalog_artwork", return_value="aW1hZ2U=") as catalog:
        assert art.read_artwork(TRACK, Event()) == "aW1hZ2U="
        catalog.assert_called_once()


def test_retry_backoff_is_bounded_and_cancellable():
    token = Mock()
    token.wait.return_value = token.is_set.return_value = False
    with patch.object(art, "read_local_artwork", return_value=None), \
            patch.object(art, "catalog_artwork", side_effect=art.ArtworkFailure("network", retryable=True)) as catalog:
        assert art.read_artwork(TRACK, token) is None
        assert catalog.call_count == 3
        assert [c.args[0] for c in token.wait.call_args_list] == [0, 2, 8]
        token.wait.reset_mock()
        token.wait.side_effect = [False, True]
        with pytest.raises(MusicCancelled):
            art.read_artwork(TRACK, token)


def test_permission_denial_and_definitive_miss_do_not_retry():
    with patch.object(art, "read_local_artwork", side_effect=art.ArtworkFailure("permission_denied")) as local:
        assert art.read_artwork(TRACK, Event()) is None
        local.assert_called_once()
    with patch.object(art, "read_local_artwork", return_value=None), \
            patch.object(art, "catalog_artwork", return_value=None) as catalog:
        assert art.read_artwork(TRACK, Event()) is None
        catalog.assert_called_once()


def test_stale_local_request_and_cancelled_network_never_fall_through():
    with patch.object(art, "run_script", return_value=subprocess.CompletedProcess([], 0, "stale", "")):
        with pytest.raises(MusicCancelled):
            art.read_artwork(TRACK, Event())
    with patch.object(art, "http_json", side_effect=LookupCancelled("stop")):
        with pytest.raises(MusicCancelled):
            art.catalog_artwork(TRACK, Event())
    with patch.object(art, "http_json", side_effect=LookupFailure("timeout", retryable=True)):
        with pytest.raises(art.ArtworkFailure) as error:
            art.catalog_artwork(TRACK, Event())
        assert error.value.retryable


def test_download_is_bounded_without_redirects_and_cleans_up():
    paths = []
    def curl(args, **kwargs):
        assert "--location" not in args and "--max-filesize" in args
        assert kwargs["timeout"] == 17
        path = Path(args[args.index("--output") + 1])
        paths.append(path)
        path.write_bytes(b"image")
        return subprocess.CompletedProcess(args, 0, "200", "")
    with patch.object(art, "run_script", side_effect=curl), patch.object(art, "valid_image", return_value=True):
        assert art.download_cover(URL, Event()) == base64.b64encode(b"image").decode()
    assert not paths[0].exists()


@pytest.mark.parametrize("code,status,retryable", [(63,"200",False), (28,"000",True),
    (0,"302",False), (0,"404",False), (0,"429",True), (0,"503",True)])
def test_download_failure_classification(code, status, retryable):
    with patch.object(art, "run_script", return_value=subprocess.CompletedProcess([], code, status, "")):
        with pytest.raises(art.ArtworkFailure) as error:
            art.download_cover(URL, Event())
        assert error.value.retryable == retryable


def test_invalid_and_oversized_image_validation(tmp_path):
    path = tmp_path / "cover"
    path.write_bytes(b"not an image")
    with patch.object(art, "run_script", return_value=subprocess.CompletedProcess([], 0, "pixelWidth: <nil>", "")):
        assert not art.valid_image(path, Event())
    with path.open("wb") as f:
        f.truncate(art.MAX_ARTWORK_BYTES + 1)
    with patch.object(art, "run_script", side_effect=AssertionError("Oversized image must not be decoded")):
        assert not art.valid_image(path, Event())
