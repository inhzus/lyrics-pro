"""Public LrcAPI search; recording metadata is validated locally."""

from urllib.parse import urlencode

from taibun import to_simplified

from ..models import Candidate, LookupFailure, Lyrics
from ..pronunciation import normalize
from ..recording_ref import recording_ref
from .lrc import has_text, parse_lrc, plain_lines
from .matching import (
    DURATION_TOLERANCE, MAX_CANDIDATES, credits_match, other_album, same_title_and_length, valid_fields,
)
from .transport import check_cancelled, http_json


MAX_LYRIC_CHARACTERS = 500000


class LrcAPIProvider:
    def __init__(self, request=None, *, cancelled=None):
        self.cancelled = cancelled
        self.request = request or (lambda params: http_json(
            "https://api.lrc.cx/jsonapi?" + urlencode(params), "LrcAPI", cancelled))

    @staticmethod
    def params(track):
        return {"title": track.title, "artist": track.artist, "album": track.album}

    def records(self, track):
        """Yield (candidate, record) pairs whose title and duration match."""
        seen = set()
        for title in dict.fromkeys((track.title, to_simplified(track.title))):
            check_cancelled(self.cancelled)
            records = self.request(self.params(track) | {"title": title})
            if records is None:
                continue
            if not isinstance(records, list):
                raise LookupFailure("LrcAPI returned invalid search results.", retryable=True)
            for record in records[:MAX_CANDIDATES]:
                candidate = self.candidate(record)
                if candidate and candidate.reference not in seen and same_title_and_length(candidate, track):
                    seen.add(candidate.reference)
                    yield candidate, record

    @staticmethod
    def candidate(record):
        if not isinstance(record, dict):
            return None
        identifier = record.get("id")
        if type(identifier) is int:
            identifier = str(identifier)
        title, artist, album, duration = (record.get(k) for k in ("title", "artist", "album", "duration"))
        if (not isinstance(identifier, str) or not recording_ref("lrcapi:" + identifier)
                or not isinstance(artist, str) or not artist.strip()
                or type(duration) not in (int, float) or not valid_fields(title, album, duration)):
            return None
        return Candidate(identifier, title, (artist,), album, duration, "lrcapi")

    @staticmethod
    def decode(candidate, record, track):
        text = record.get("lrc", record.get("lyrics"))
        if text is None or text == "":
            return None
        if not isinstance(text, str) or len(text) > MAX_LYRIC_CHARACTERS:
            raise LookupFailure("LrcAPI returned invalid lyrics data.", retryable=True)
        source = ("LrcAPI https://api.lrc.cx/jsonapi?" + urlencode(LrcAPIProvider.params(track))
                  + "#" + candidate.song_id)
        lines = parse_lrc(text)
        if has_text(lines):
            # Timestamps beyond the recording belong to another version.
            if any(line.time > track.duration + DURATION_TOLERANCE for line in lines):
                return None
            return Lyrics(lines, source, True)
        if "<tt" in text or "<html" in text:
            return None
        plain = plain_lines(text.removeprefix("[!text]"))
        return Lyrics(plain, source, False) if plain else None

    def alternatives(self, track):
        return tuple(c for c, _ in self.records(track))[:MAX_CANDIDATES]

    def lyrics_for(self, identifier, track):
        for candidate, record in self.records(track):
            if candidate.song_id == identifier:
                return self.decode(candidate, record, track)
        return None

    def lookup(self, track):
        plain = None
        records = sorted(self.records(track), key=lambda item: (
            not credits_match(item[0].artists, track.artist),
            other_album(item[0], track), abs(item[0].duration - track.duration)))
        for candidate, record in records:
            # Unresolved artist names need an exact nonempty album match.
            if not (credits_match(candidate.artists, track.artist)
                    or (normalize(track.album) and not other_album(candidate, track))):
                continue
            result = self.decode(candidate, record, track)
            if result and result.synced:
                return result
            plain = plain or result
        return plain
