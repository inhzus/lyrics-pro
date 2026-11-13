"""Provider order, fallback policy, and explicit recording selection."""

from threading import Event
import time

from ..curated import curated_lyrics
from ..diagnostics import event
from ..models import LookupCancelled, LookupFailure, Lyrics, Playback
from .lrcapi import LrcAPIProvider
from .lrclib import LRCLIBProvider, lrclib_request_json
from .matching import MAX_CANDIDATES
from .netease import NetEaseProvider, RecordingChoiceRequired, request_json
from .transport import check_cancelled


UNVERIFIED_ATTEMPTS = 3
# Each provider keeps at least this many discovery rows when both return a full quota.
DISCOVERY_SHARE = 15


def netease(cancelled: Event | None) -> NetEaseProvider:
    return NetEaseProvider(lambda endpoint, params: request_json(endpoint, params, cancelled))


def _outcome(result: Lyrics | None) -> str:
    return "timed" if result and result.synced else "plain" if result else "missing"


class LyricsProvider:
    """NetEase first, then LrcAPI and LRCLIB when they can improve the result."""

    def __init__(self, primary=None, fallback=None, *, lrcapi=None, cancelled: Event | None = None):
        self.cancelled = cancelled
        self.primary = primary if primary is not None else netease(cancelled)
        self.fallback = fallback if fallback is not None else LRCLIBProvider(
            lambda endpoint, params: lrclib_request_json(endpoint, params, cancelled))
        self.lrcapi = lrcapi if lrcapi is not None else LrcAPIProvider(cancelled=cancelled)

    def check_cancelled(self):
        check_cancelled(self.cancelled)

    def _attempt(self, name: str, provider, track: Playback, errors: list[LookupFailure]):
        """Run one provider; return (lyrics, unverified choices)."""
        self.check_cancelled()
        started = time.monotonic()
        event("provider_start", provider=name, title=track.title, artist=track.artist)
        result = choices = None
        try:
            result = provider.lookup(track)
        except LookupCancelled:
            raise
        except RecordingChoiceRequired as exc:
            choices = exc
            event("unverified_candidates", provider=name, count=len(exc.candidates))
        except LookupFailure as exc:
            errors.append(exc)
            event("provider_error", provider=name, error=str(exc))
        event("provider_end", provider=name, seconds=round(time.monotonic() - started, 3),
              result=_outcome(result), errors=len(errors))
        self.check_cancelled()
        return result, choices

    def lookup(self, track: Playback) -> Lyrics | None:
        errors: list[LookupFailure] = []
        primary, choices = self._attempt("NetEase", self.primary, track, errors)
        if primary and (primary.synced or primary.instrumental):
            return primary
        fallback = None
        for name, provider in (("LrcAPI", self.lrcapi), ("LRCLIB", self.fallback)):
            result, _ = self._attempt(name, provider, track, errors)
            if result and (result.synced or (result.instrumental and not (primary or fallback))):
                return result
            fallback = fallback or result
        if primary or fallback:
            return primary or fallback
        if choices:
            # Verified providers have had their chance. Try a bounded set of
            # unverified matches, without persisting an artist or recording alias.
            for candidate in choices.candidates[:UNVERIFIED_ATTEMPTS]:
                self.check_cancelled()
                try:
                    if result := self.primary.lyrics_for(candidate.song_id):
                        return result
                except LookupCancelled:
                    raise
                except LookupFailure as exc:
                    errors.append(exc)
        if errors:
            raise LookupFailure("; ".join(str(error) for error in errors),
                                retryable=any(error.retryable for error in errors)) from errors[-1]
        return None


def lookup(track: Playback, cancelled: Event) -> Lyrics | None:
    return LyricsProvider(cancelled=cancelled).lookup(track)


def lookup_recording(reference: str, track: Playback, cancelled: Event) -> Lyrics | None:
    """Load one explicitly selected, provider-qualified recording."""
    provider, identifier = reference.split(":", 1)
    if provider == "proofread":
        result = curated_lyrics(track, reference, cancelled)
        if result is None:
            raise LookupFailure("This proofread source is unavailable or does not match this song.")
        return result
    if provider == "lrcapi":
        return LrcAPIProvider(cancelled=cancelled).lyrics_for(identifier, track)
    if provider == "netease":
        return netease(cancelled).lyrics_for(int(identifier))
    raise LookupFailure("Unsupported lyric source.")


def discover_recordings(track: Playback, cancelled: Event):
    """Online recordings for manual selection, NetEase rows first."""
    candidates, errors = [], []
    for provider in (netease(cancelled), LrcAPIProvider(cancelled=cancelled)):
        try:
            candidates.extend(provider.alternatives(track))
        except LookupCancelled:
            raise
        except LookupFailure as error:
            errors.append(error)
            event("discovery_error", provider=type(provider).__name__, error=str(error))
    if not candidates and errors:
        raise errors[-1]
    by_netease = [c for c in candidates if c.provider == "netease"]
    by_lrcapi = [c for c in candidates if c.provider == "lrcapi"]
    return tuple(by_netease[:max(DISCOVERY_SHARE, MAX_CANDIDATES - len(by_lrcapi))]
                 + by_lrcapi[:max(DISCOVERY_SHARE, MAX_CANDIDATES - len(by_netease))])[:MAX_CANDIDATES]
