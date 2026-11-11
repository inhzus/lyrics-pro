from dataclasses import dataclass


@dataclass(frozen=True)
class Playback:
    state: str
    title: str = ""
    artist: str = ""
    album: str = ""
    duration: float = 0
    position: float = 0

    @property
    def key(self) -> tuple[str, str, str, float] | None:
        if not self.title or self.state in {"closed", "stopped"}:
            return None
        return self.title, self.artist, self.album, round(self.duration, 2)


@dataclass(frozen=True)
class LyricLine:
    text: str
    time: float | None = None
    pronunciation: str | None = None


@dataclass(frozen=True)
class Proofread:
    asset_id: str
    revision: str
    language: str
    attribution: str


@dataclass(frozen=True)
class Lyrics:
    lines: tuple[LyricLine, ...]
    source: str
    synced: bool
    instrumental: bool = False
    proofread: Proofread | None = None
    recording_id: str | None = None


class LookupFailure(Exception):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class LookupCancelled(LookupFailure):
    """An intentional stop, never a reason to retry or contact a fallback."""
