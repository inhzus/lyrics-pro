"""Recording identity checks shared by providers."""

import math

from ..models import Candidate, Lyrics, Playback
from ..pronunciation import artist_key, normalize


DURATION_TOLERANCE = 2
MAX_CANDIDATES = 30


def valid_fields(title, album, duration: float) -> bool:
    return (isinstance(title, str) and bool(title.strip()) and isinstance(album, str)
            and math.isfinite(duration) and duration > 0)


def lookup_ready(track: Playback) -> bool:
    return (bool(track.title.strip()) and bool(track.artist.strip())
            and math.isfinite(track.duration) and track.duration > 0)


def same_title_and_length(candidate: Candidate, track: Playback) -> bool:
    return (normalize(candidate.title) == normalize(track.title)
            and abs(candidate.duration - track.duration) <= DURATION_TOLERANCE)


def credits_match(artists: tuple[str, ...], artist: str) -> bool:
    target = artist_key(artist)
    return bool(artists and target) and (
        artist_key(" & ".join(artists)) == target
        or {artist_key(name) for name in artists} == {target}
    )


def matches(candidate: Candidate, track: Playback) -> bool:
    return same_title_and_length(candidate, track) and credits_match(candidate.artists, track.artist)


def other_album(candidate: Candidate, track: Playback) -> bool:
    return normalize(candidate.album) != normalize(track.album)


class BestResult:
    """Keep the first plain result while waiting for a timed or instrumental one."""

    def __init__(self):
        self.plain: Lyrics | None = None

    def offer(self, lyrics: Lyrics | None) -> bool:
        if lyrics and (lyrics.synced or lyrics.instrumental):
            return True
        if lyrics and self.plain is None:
            self.plain = lyrics
        return False
