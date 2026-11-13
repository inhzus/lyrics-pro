"""NetEase Cloud Music: the primary, verified lyric provider."""

import re
from threading import Event
from urllib.parse import urlencode

from taibun import to_simplified

from ..models import Candidate, LookupCancelled, LookupFailure, Lyrics, Playback
from ..pronunciation import native_name, normalize
from .lrc import has_text, parse_lrc, plain_lines
from .matching import (
    MAX_CANDIDATES, BestResult, credits_match, lookup_ready, matches, other_album,
    same_title_and_length, valid_fields,
)
from .transport import http_json


SONG_SEARCH_LIMIT = 30
ALBUM_SEARCH_LIMIT = 20
MAX_ALBUMS = 3
LYRIC_ATTEMPTS_PER_PHASE = 3


def request_json(endpoint: str, params: dict, cancelled: Event | None = None) -> object | None:
    # Provider URLs are fixed here; response data cannot redirect requests.
    if endpoint not in {"search/get", "song/lyric"} and not re.fullmatch(r"v1/album/[1-9]\d*", endpoint):
        raise ValueError("Unsupported NetEase endpoint")
    data = http_json("https://music.163.com/api/" + endpoint + "?" + urlencode(params),
                     "NetEase", cancelled, referer="https://music.163.com/")
    if data is None:
        return None
    if not isinstance(data, dict):
        raise LookupFailure("NetEase returned an invalid response.", retryable=True)
    code = data.get("code")
    if code == 404:
        return None
    if code != 200:
        raise LookupFailure(f"NetEase returned API code {code}.",
                            retryable=code is None or code == 429 or
                            (isinstance(code, int) and 500 <= code < 600))
    return data


class RecordingChoiceRequired(LookupFailure):
    def __init__(self, candidates):
        super().__init__("Choose a recording in Lyrics Pro to confirm the lyric match.")
        self.candidates = tuple(candidates)


def artist_names(record: dict) -> tuple[str, ...]:
    artists = record.get("artists", record.get("ar"))
    if artists is None:
        artists = [record.get("artist")]
    if not isinstance(artists, list):
        return ()
    names = tuple(a["name"] for a in artists
                  if isinstance(a, dict) and isinstance(a.get("name"), str) and a["name"].strip())
    return names if len(names) == len(artists) else ()


def candidate_from_record(record: dict, album: str = "") -> Candidate | None:
    try:
        song_id = record["id"]
        title = record["name"]
        artists = artist_names(record)
        album_info = record.get("album", record.get("al")) or {}
        album_name = album_info.get("name", album)
        milliseconds = record.get("duration", record.get("dt"))
        duration = float(milliseconds) / 1000
        if (type(song_id) is not int or song_id <= 0 or not artists or isinstance(milliseconds, bool)
                or not valid_fields(title, album_name, duration)):
            return None
        return Candidate(song_id, title, artists, album_name, duration)
    except (KeyError, ValueError, TypeError, AttributeError):
        return None


def recording_candidates(records, track, *, include_verified=False, limit=MAX_CANDIDATES):
    """Rank recordings without treating title/duration as artist identity."""
    relevance = {}
    for index, record in enumerate(records):
        song_id = record.get("id")
        if type(song_id) is int:
            relevance.setdefault(song_id, index)
    candidates = {c.song_id: c for record in records
                  if (c := candidate_from_record(record)) is not None
                  and same_title_and_length(c, track)
                  and (include_verified or not credits_match(c.artists, track.artist))}
    return sorted(candidates.values(), key=lambda c: (
        not credits_match(c.artists, track.artist),
        other_album(c, track), relevance[c.song_id],
        abs(c.duration - track.duration), c.song_id,
    ))[:limit]


def decode_record(record: dict, song_id: int) -> Lyrics | None:
    source = f"NetEase https://music.163.com/song?id={song_id}"
    if record.get("nolyric") is True:
        return Lyrics((), source, False, instrumental=True)
    if record.get("uncollected") is True:
        return None
    lrc = record.get("lrc")
    if lrc is None:
        lrc = {}
    if not isinstance(lrc, dict) or not isinstance(lrc.get("lyric", ""), str):
        raise LookupFailure("NetEase returned invalid lyrics data.", retryable=True)
    text = lrc.get("lyric", "")
    synced = parse_lrc(text)
    if has_text(synced):
        return Lyrics(synced, source, True)
    plain = plain_lines(text)
    return Lyrics(plain, source, False) if plain else None


def response_items(response: dict | None, key: str, *, search: bool = False) -> list[dict]:
    if response is None:
        return []
    if not isinstance(response, dict):
        raise LookupFailure("NetEase returned invalid metadata.", retryable=True)
    container = response.get("result") if search else response
    if container is None:
        container = {}
    if not isinstance(container, dict):
        raise LookupFailure("NetEase returned invalid search results.", retryable=True)
    items = container.get(key)
    if items is None:
        items = []
    if not isinstance(items, list):
        raise LookupFailure("NetEase returned invalid metadata entries.", retryable=True)
    return [item for item in items if isinstance(item, dict)]


def search_queries(track: Playback) -> tuple[str, ...]:
    # NetEase search may know romanized Apple Music credits only by their native name.
    artist = native_name(track.artist) or track.artist
    return tuple(dict.fromkeys((f"{to_simplified(track.title)} {to_simplified(artist)}",
                                f"{track.title} {track.artist}")))


class NetEaseProvider:
    def __init__(self, request=request_json):
        self.request = request

    def search_songs(self, query: str) -> list[dict]:
        response = self.request("search/get", {"s": query, "type": 1, "limit": SONG_SEARCH_LIMIT, "offset": 0})
        return response_items(response, "songs", search=True)[:SONG_SEARCH_LIMIT]

    def search_albums(self, query: str) -> list[dict]:
        response = self.request("search/get", {"s": query, "type": 10, "limit": ALBUM_SEARCH_LIMIT, "offset": 0})
        return response_items(response, "albums", search=True)[:ALBUM_SEARCH_LIMIT]

    def lyric_record(self, song_id) -> dict | None:
        record = self.request("song/lyric", {"id": song_id, "lv": -1, "kv": -1, "tv": -1, "rv": -1})
        if record is not None and not isinstance(record, dict):
            raise LookupFailure("NetEase returned invalid lyrics data.", retryable=True)
        return record

    def lyrics_for(self, song_id):
        record = self.lyric_record(song_id)
        return decode_record(record, song_id) if record else None

    def alternatives(self, track):
        records = []
        for query in dict.fromkeys((*search_queries(track), to_simplified(track.title))):
            records.extend(self.search_songs(query))
        return tuple(recording_candidates(records, track, include_verified=True))

    def lookup(self, track: Playback) -> Lyrics | None:
        if not lookup_ready(track):
            return None
        return _Lookup(self, track).run()


class _Lookup:
    """One verified lookup: song search, then album tracks, then compilations."""

    def __init__(self, provider: NetEaseProvider, track: Playback):
        self.provider = provider
        self.track = track
        self.seen: set[int] = set()
        self.best = BestResult()
        self.suggestions: list[dict] = []

    def run(self) -> Lyrics | None:
        try:
            found = self.search_phases()
            if found:
                return found
            if not self.best.plain:
                # A title-only query recovers artists whose romanized name is
                # unknown to the search service. These remain unverified matches.
                self.suggestions.extend(self.provider.search_songs(to_simplified(self.track.title)))
        except LookupCancelled:
            raise
        except LookupFailure:
            if self.best.plain:
                return self.best.plain
            self.require_choice()
            raise
        if not self.best.plain:
            self.require_choice()
        return self.best.plain

    def require_choice(self):
        if choices := recording_candidates(self.suggestions, self.track):
            raise RecordingChoiceRequired(choices)

    def search_phases(self) -> Lyrics | None:
        budget = LYRIC_ATTEMPTS_PER_PHASE
        deferred: list[dict] = []
        for query in search_queries(self.track):
            if budget <= 0:
                break
            records = self.provider.search_songs(query)
            self.suggestions.extend(records)
            preferred = []
            for record in records:
                candidate = candidate_from_record(record)
                if candidate is None or not matches(candidate, self.track):
                    continue
                if self.track.album.strip() and other_album(candidate, self.track):
                    deferred.append(record)
                else:
                    preferred.append(record)
            found, budget = self.try_records(preferred, budget)
            if found:
                return found
        # Studio recordings can be absent from song search while still
        # present in the album, as verified with 天下無雙.
        if self.track.album.strip() and (found := self.album_phase()):
            return found
        # A compilation with similar duration is a fallback, not a reason
        # to skip looking for the requested album's original recording.
        found, _ = self.try_records(deferred, budget)
        return found

    def album_phase(self) -> Lyrics | None:
        album_ids: set[int] = set()
        budget = LYRIC_ATTEMPTS_PER_PHASE
        for query in dict.fromkeys((to_simplified(self.track.album), self.track.album)):
            for album in self.provider.search_albums(query):
                if len(album_ids) >= MAX_ALBUMS or budget <= 0:
                    return None
                album_id, name = album.get("id"), album.get("name")
                if (type(album_id) is not int or album_id <= 0 or album_id in album_ids
                        or not isinstance(name, str) or normalize(name) != normalize(self.track.album)
                        or not credits_match(artist_names(album), self.track.artist)):
                    continue
                album_ids.add(album_id)
                response = self.provider.request(f"v1/album/{album_id}", {})
                found, budget = self.try_records(response_items(response, "songs"), budget, name)
                if found:
                    return found
        return None

    def try_records(self, records: list[dict], budget: int, album: str = ""):
        candidates = sorted(
            (c for record in records
             if (c := candidate_from_record(record, album)) is not None and matches(c, self.track)),
            key=lambda c: (other_album(c, self.track), abs(c.duration - self.track.duration), c.song_id))
        for candidate in candidates:
            if budget <= 0:
                break
            if candidate.song_id in self.seen:
                continue
            self.seen.add(candidate.song_id)
            budget -= 1
            record = self.provider.lyric_record(candidate.song_id)
            if record is None:
                continue
            decoded = decode_record(record, candidate.song_id)
            if self.best.offer(decoded):
                return decoded, budget
        return None, budget
