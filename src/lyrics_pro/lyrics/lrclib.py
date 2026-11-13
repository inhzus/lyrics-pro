"""LRCLIB: the last fallback, validated locally by artist and duration."""

from threading import Event
from urllib.parse import urlencode

from taibun import to_simplified, to_traditional

from ..models import Candidate, LookupCancelled, LookupFailure, LyricLine, Lyrics, Playback
from .lrc import has_text, parse_lrc
from .matching import BestResult, lookup_ready, matches, other_album, valid_fields
from .transport import http_json


SEARCH_LIMIT = 20


def lrclib_request_json(endpoint: str, params: dict, cancelled: Event | None = None):
    if endpoint not in {"get", "search"}:
        raise ValueError("Unsupported LRCLIB endpoint")
    data = http_json("https://lrclib.net/api/" + endpoint + "?" + urlencode(params), "LRCLIB", cancelled)
    expected = dict if endpoint == "get" else list
    if data is not None and not isinstance(data, expected):
        raise LookupFailure("LRCLIB returned an invalid response.", retryable=True)
    return data


def lrclib_candidate(record: dict) -> Candidate | None:
    try:
        song_id, title, artist = record["id"], record["trackName"], record["artistName"]
        duration = float(record["duration"])
        album = record.get("albumName") or ""
        if (type(song_id) is not int or song_id <= 0 or not isinstance(artist, str) or not artist.strip()
                or isinstance(record["duration"], bool) or not valid_fields(title, album, duration)):
            return None
        return Candidate(song_id, title, (artist,), album, duration)
    except (KeyError, ValueError, TypeError):
        return None


def decode_lrclib(record: dict, song_id: int) -> Lyrics | None:
    source = f"LRCLIB https://lrclib.net/api/get/{song_id}"
    if record.get("instrumental") is True:
        return Lyrics((), source, False, instrumental=True)
    synced_text = record.get("syncedLyrics")
    plain_text = record.get("plainLyrics")
    if any(text is not None and not isinstance(text, str) for text in (synced_text, plain_text)):
        raise LookupFailure("LRCLIB returned invalid lyrics data.", retryable=True)
    synced = parse_lrc(synced_text or "")
    if has_text(synced):
        return Lyrics(synced, source, True)
    if plain_text and plain_text.strip():
        # LRCLIB plain lyrics carry no tags; bracketed lines such as [Chorus] are kept.
        return Lyrics(tuple(LyricLine(line.strip()) for line in plain_text.splitlines() if line.strip()),
                      source, False)
    return None


class LRCLIBProvider:
    def __init__(self, request=lrclib_request_json):
        self.request = request

    def lookup(self, track: Playback) -> Lyrics | None:
        if not lookup_ready(track):
            return None
        best = BestResult()
        seen: set[int] = set()

        def select(records):
            candidates = [(candidate, record) for record in records if isinstance(record, dict)
                          and (candidate := lrclib_candidate(record)) is not None and matches(candidate, track)]
            candidates.sort(key=lambda item: (
                other_album(item[0], track), not bool(item[1].get("syncedLyrics")),
                abs(item[0].duration - track.duration), item[0].song_id,
            ))
            for candidate, record in candidates:
                if candidate.song_id in seen:
                    continue
                seen.add(candidate.song_id)
                decoded = decode_lrclib(record, candidate.song_id)
                if best.offer(decoded):
                    return decoded
            return None

        try:
            exact = self.request("get", {
                "track_name": track.title, "artist_name": track.artist,
                "album_name": track.album, "duration": track.duration,
            })
            if exact is not None and (found := select([exact])):
                return found
            # Title-only searches allow alternate artist spellings; local
            # validation still checks the artist and recording duration.
            for title in dict.fromkeys((track.title, to_simplified(track.title), to_traditional(track.title))):
                records = self.request("search", {"track_name": title})
                if records is None:
                    continue
                if not isinstance(records, list):
                    raise LookupFailure("LRCLIB returned invalid search results.", retryable=True)
                if found := select(records[:SEARCH_LIMIT]):
                    return found
        except LookupCancelled:
            raise
        except LookupFailure:
            if best.plain:
                return best.plain
            raise
        return best.plain
