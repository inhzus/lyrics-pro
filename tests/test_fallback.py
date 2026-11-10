from threading import Event
from unittest.mock import Mock

import pytest

from lyrics_pro.lyrics import LyricsProvider, NetEaseProvider, LRCLIBProvider
from lyrics_pro.models import LookupCancelled, LookupFailure, LyricLine, Lyrics, Playback


TRACK = Playback("playing", "浮誇", "Eason Chan", "U87", 284)
NE_TIMED = Lyrics((LyricLine("primary", 10),), "NetEase", True)
NE_PLAIN = Lyrics((LyricLine("primary"),), "NetEase", False)
NE_INSTRUMENTAL = Lyrics((), "NetEase", False, instrumental=True)
LR_TIMED = Lyrics((LyricLine("fallback", 10),), "LRCLIB", True)
LR_PLAIN = Lyrics((LyricLine("fallback"),), "LRCLIB", False)
LR_INSTRUMENTAL = Lyrics((), "LRCLIB", False, instrumental=True)


def stub(result):
    provider = Mock()
    if isinstance(result, Exception):
        provider.lookup.side_effect = result
    else:
        provider.lookup.return_value = result
    return provider


@pytest.mark.parametrize("primary", [NE_TIMED, NE_INSTRUMENTAL])
def test_primary_complete_result_never_contacts_fallback(primary):
    secondary = stub(LR_TIMED)
    assert LyricsProvider(stub(primary), secondary).lookup(TRACK) is primary
    secondary.lookup.assert_not_called()


@pytest.mark.parametrize("primary", [None, NE_PLAIN, LookupFailure("NetEase timed out", retryable=True),
                                    LookupFailure("NetEase forbidden")])
def test_fallback_runs_in_same_round_and_returns_timed_lyrics(primary):
    first, second = stub(primary), stub(LR_TIMED)
    assert LyricsProvider(first, second).lookup(TRACK) is LR_TIMED
    first.lookup.assert_called_once_with(TRACK)
    second.lookup.assert_called_once_with(TRACK)


@pytest.mark.parametrize("secondary", [None, LR_PLAIN, LR_INSTRUMENTAL,
                                      LookupFailure("fallback timed out", retryable=True)])
def test_primary_plain_lyrics_survive_inferior_or_failed_fallback(secondary):
    assert LyricsProvider(stub(NE_PLAIN), stub(secondary)).lookup(TRACK) is NE_PLAIN


@pytest.mark.parametrize("secondary", [LR_PLAIN, LR_INSTRUMENTAL])
def test_fallback_result_survives_primary_failure(secondary):
    assert LyricsProvider(stub(LookupFailure("primary failed")), stub(secondary)).lookup(TRACK) is secondary


def test_both_missing_returns_none():
    assert LyricsProvider(stub(None), stub(None)).lookup(TRACK) is None


@pytest.mark.parametrize("primary,secondary,retryable", [
    (LookupFailure("NetEase failed", retryable=True), None, True),
    (None, LookupFailure("LRCLIB failed", retryable=True), True),
    (LookupFailure("NetEase denied"), LookupFailure("LRCLIB failed", retryable=True), True),
    (LookupFailure("NetEase denied"), None, False),
    (LookupFailure("NetEase denied"), LookupFailure("LRCLIB denied"), False),
])
def test_unusable_results_preserve_errors_and_retryability(primary, secondary, retryable):
    with pytest.raises(LookupFailure) as error:
        LyricsProvider(stub(primary), stub(secondary)).lookup(TRACK)
    assert error.value.retryable == retryable
    for item in (primary, secondary):
        if isinstance(item, LookupFailure):
            assert str(item) in str(error.value)


def test_cancel_before_lookup_prevents_both_requests():
    event = Event()
    event.set()
    primary, secondary = stub(None), stub(LR_TIMED)
    with pytest.raises(LookupCancelled):
        LyricsProvider(primary, secondary, cancelled=event).lookup(TRACK)
    primary.lookup.assert_not_called()
    secondary.lookup.assert_not_called()


def test_primary_cancellation_never_starts_fallback():
    secondary = stub(LR_TIMED)
    with pytest.raises(LookupCancelled):
        LyricsProvider(stub(LookupCancelled("stopped")), secondary).lookup(TRACK)
    secondary.lookup.assert_not_called()


def test_cancel_between_providers_never_starts_fallback():
    event = Event()
    primary, secondary = stub(None), stub(LR_TIMED)
    primary.lookup.side_effect = lambda track: event.set()
    with pytest.raises(LookupCancelled):
        LyricsProvider(primary, secondary, cancelled=event).lookup(TRACK)
    secondary.lookup.assert_not_called()


def test_fallback_cancellation_is_not_hidden_by_plain_lyrics():
    with pytest.raises(LookupCancelled):
        LyricsProvider(stub(NE_PLAIN), stub(LookupCancelled("stopped"))).lookup(TRACK)


@pytest.mark.parametrize("provider_type", [NetEaseProvider, LRCLIBProvider])
def test_provider_cancellation_not_swallowed_after_plain_result(provider_type):
    calls = 0

    def request(endpoint, params):
        nonlocal calls
        calls += 1
        if provider_type is LRCLIBProvider:
            if calls == 1:
                return {"id": 1, "trackName": "浮夸", "artistName": "陈奕迅", "albumName": "U87",
                        "duration": 284, "plainLyrics": "plain"}
        else:
            if calls == 1:
                return {"result": {"songs": [{"id": 1, "name": "浮夸", "artists": [{"name": "陈奕迅"}],
                                              "album": {"name": "U87"}, "duration": 284000}]}}
            if calls == 2:
                return {"lrc": {"lyric": "plain"}}
        raise LookupCancelled("stopped")

    with pytest.raises(LookupCancelled):
        provider_type(request).lookup(TRACK)
