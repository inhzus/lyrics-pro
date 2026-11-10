import json
from dataclasses import dataclass
import math
import re
import subprocess
from threading import Event
import time
from urllib.parse import urlencode

from taibun import to_simplified, to_traditional

from .models import LookupCancelled, LookupFailure, LyricLine, Lyrics, Playback
from .pronunciation import artist_key, normalize
from .diagnostics import event
from .recording_ref import recording_ref


STAMP = re.compile(r"\[(\d+):([0-5]\d)(?:[.:](\d{1,3}))?\]")
OFFSET = re.compile(r"\[offset:\s*([+-]?\d+)\]", re.IGNORECASE)


def parse_lrc(text: str) -> tuple[LyricLine, ...]:
    offsets = OFFSET.findall(text)
    offset = int(offsets[-1]) / 1000 if offsets else 0
    entries: dict[float, list[str]] = {}
    for raw in text.splitlines():
        stamps = list(STAMP.finditer(raw))
        if not stamps or raw[:stamps[0].start()].strip():
            continue
        words = raw[stamps[-1].end():].strip()
        for stamp in stamps:
            minutes, seconds, fraction = stamp.groups()
            # Positive LRC offsets advance lyrics relative to the audio clock.
            time = max(0, int(minutes) * 60 + int(seconds) +
                       (float("0." + fraction) if fraction else 0) - offset)
            group = entries.setdefault(time, [])
            if words not in group:
                group.append(words)
    return tuple(LyricLine(" / ".join(filter(None, words)), time)
                 for time, words in sorted(entries.items()))


def run_curl(command: list[str], cancelled: Event | None = None):
    if cancelled and cancelled.is_set():
        raise LookupCancelled("Lyrics request cancelled.")
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        deadline = time.monotonic() + 17
        try:
            while True:
                if cancelled and cancelled.is_set():
                    raise LookupCancelled("Lyrics request cancelled.")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, 17)
                try:
                    stdout, stderr = process.communicate(timeout=min(0.2, remaining))
                    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


def http_json(url: str, service: str, cancelled: Event | None = None, *, referer: str | None = None):
    headers = ["--referer", referer] if referer else []
    try:
        response = run_curl(
            ["/usr/bin/curl", "-4", "--compressed", "--silent", "--show-error", "--connect-timeout", "5",
             "--max-time", "15", "--max-filesize", "5000000", "--user-agent",
             "LyricsPro/0.1 (personal terminal prototype)", *headers,
             "--write-out", "\n%{http_code}", url],
            cancelled,
        )
    except subprocess.TimeoutExpired as exc:
        raise LookupFailure(f"{service} request timed out.", retryable=True) from exc
    except FileNotFoundError as exc:
        raise LookupFailure("curl is required to retrieve lyrics.") from exc
    if response.returncode:
        error = response.stderr.decode("utf-8", errors="replace") if isinstance(response.stderr, bytes) else response.stderr
        raise LookupFailure(f"{service} network request failed: " + error.strip(), retryable=True)
    output = response.stdout.encode("utf-8") if isinstance(response.stdout, str) else response.stdout
    body, _, status_bytes = output.rpartition(b"\n")
    status = status_bytes.decode("ascii", errors="replace")
    if status == "404":
        return None
    if status != "200":
        raise LookupFailure(f"{service} returned HTTP {status}.",
                            retryable=status == "429" or status.startswith("5"))
    try:
        data = json.loads(body.decode("utf-8"))
    except ValueError as exc:
        raise LookupFailure(f"{service} returned invalid JSON.", retryable=True) from exc
    if data is None:
        raise LookupFailure(f"{service} returned an invalid response.", retryable=True)
    return data


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


@dataclass(frozen=True)
class Candidate:
    song_id: int | str
    title: str
    artists: tuple[str, ...]
    album: str
    duration: float
    provider: str = "netease"

    @property
    def reference(self):
        return f"{self.provider}:{self.song_id}"


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


def credits_match(artists: tuple[str, ...], artist: str) -> bool:
    target = artist_key(artist)
    return bool(artists and target) and (
        artist_key(" & ".join(artists)) == target
        or {artist_key(name) for name in artists} == {target}
    )


def candidate_from_record(record: dict, album: str = "") -> Candidate | None:
    try:
        song_id = record["id"]
        title = record["name"]
        artists = artist_names(record)
        album_info = record.get("album", record.get("al")) or {}
        album_name = album_info.get("name", album)
        milliseconds = record.get("duration", record.get("dt"))
        duration = float(milliseconds) / 1000
        if (type(song_id) is not int or song_id <= 0 or not isinstance(title, str)
                or not title.strip() or not artists or not isinstance(album_name, str)
                or isinstance(milliseconds, bool) or not math.isfinite(duration) or duration <= 0):
            return None
        return Candidate(song_id, title, artists, album_name, duration)
    except (KeyError, ValueError, TypeError, AttributeError):
        return None


def matches(candidate: Candidate, track: Playback) -> bool:
    return (
        abs(candidate.duration - track.duration) <= 2
        and normalize(candidate.title) == normalize(track.title)
        and credits_match(candidate.artists, track.artist)
    )


def recording_candidates(records, track, *, include_verified=False, limit=30):
    """Rank recordings without treating title/duration as artist identity."""
    relevance = {}
    for index, record in enumerate(records):
        song_id = record.get("id")
        if type(song_id) is int:
            relevance.setdefault(song_id, index)
    candidates = {c.song_id: c for record in records
                  if (c := candidate_from_record(record)) is not None
                  and normalize(c.title) == normalize(track.title)
                  and abs(c.duration - track.duration) <= 2
                  and (include_verified or not credits_match(c.artists, track.artist))}
    return sorted(candidates.values(), key=lambda c: (
        not credits_match(c.artists, track.artist),
        normalize(c.album) != normalize(track.album), relevance[c.song_id],
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
    if synced and any(line.text for line in synced):
        return Lyrics(synced, source, True)
    # Metadata tags and empty timestamped entries aren't plain lyrics.
    plain = tuple(LyricLine(line.strip()) for line in text.splitlines()
                  if line.strip() and not re.fullmatch(r"(?:\[[^\]]*\]\s*)+", line.strip()))
    if plain:
        return Lyrics(plain, source, False)
    return None


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


class NetEaseProvider:
    def __init__(self, request=request_json):
        self.request = request

    def lyrics_for(self, song_id):
        record = self.request("song/lyric", {"id": song_id, "lv": -1, "kv": -1, "tv": -1, "rv": -1})
        return decode_record(record, song_id) if record else None

    def alternatives(self, track):
        records = []
        artist = {"eason": "陈奕迅", "wubai": "伍佰"}.get(artist_key(track.artist), track.artist)
        queries = dict.fromkeys((f"{to_simplified(track.title)} {to_simplified(artist)}",
                                f"{track.title} {track.artist}", to_simplified(track.title)))
        for query in queries:
            response = self.request("search/get", {"s": query, "type": 1, "limit": 30, "offset": 0})
            records.extend(response_items(response, "songs", search=True)[:30])
        return tuple(recording_candidates(records, track, include_verified=True))

    def lookup(self, track: Playback) -> Lyrics | None:
        if not track.title.strip() or not track.artist.strip() or not math.isfinite(track.duration) or track.duration <= 0:
            return None
        seen_ids: set[int] = set()
        plain = None
        suggestions = []

        def try_candidates(records: list[dict], budget: int, album: str = ""):
            nonlocal plain
            candidates = [candidate for record in records
                          if (candidate := candidate_from_record(record, album)) is not None
                          and matches(candidate, track)]
            candidates.sort(key=lambda candidate: (
                normalize(candidate.album) != normalize(track.album),
                abs(candidate.duration - track.duration), candidate.song_id,
            ))
            for candidate in candidates:
                if budget <= 0:
                    break
                if candidate.song_id in seen_ids:
                    continue
                seen_ids.add(candidate.song_id)
                budget -= 1
                record = self.request("song/lyric", {
                    "id": candidate.song_id, "lv": -1, "kv": -1, "tv": -1, "rv": -1,
                })
                if record is None:
                    continue
                if not isinstance(record, dict):
                    raise LookupFailure("NetEase returned invalid lyrics data.", retryable=True)
                decoded = decode_record(record, candidate.song_id)
                if decoded and (decoded.synced or decoded.instrumental):
                    return decoded, budget
                if decoded and plain is None:
                    plain = decoded
            return None, budget

        try:
            chinese_artist = {"eason": "陈奕迅", "wubai": "伍佰"}.get(artist_key(track.artist), track.artist)
            queries = dict.fromkeys((
                f"{to_simplified(track.title)} {to_simplified(chinese_artist)}",
                f"{track.title} {track.artist}",
            ))
            song_budget = 3
            deferred: list[dict] = []
            for query in queries:
                if song_budget <= 0:
                    break
                response = self.request("search/get", {"s": query, "type": 1, "limit": 30, "offset": 0})
                records = response_items(response, "songs", search=True)[:30]
                suggestions.extend(records)
                preferred = []
                for record in records:
                    candidate = candidate_from_record(record)
                    if candidate is None or not matches(candidate, track):
                        continue
                    if track.album.strip() and normalize(candidate.album) != normalize(track.album):
                        deferred.append(record)
                    else:
                        preferred.append(record)
                found, song_budget = try_candidates(preferred, song_budget)
                if found:
                    return found

            # Studio recordings can be absent from song search while still
            # present in the album, as verified with 天下無雙.
            if track.album.strip():
                album_ids: set[int] = set()
                budget = 3
                for query in dict.fromkeys((to_simplified(track.album), track.album)):
                    if len(album_ids) >= 3 or budget <= 0:
                        break
                    response = self.request("search/get", {"s": query, "type": 10, "limit": 20, "offset": 0})
                    for album in response_items(response, "albums", search=True)[:20]:
                        if len(album_ids) >= 3 or budget <= 0:
                            break
                        album_id, name = album.get("id"), album.get("name")
                        if (type(album_id) is not int or album_id <= 0 or album_id in album_ids
                                or not isinstance(name, str) or normalize(name) != normalize(track.album)
                                or not credits_match(artist_names(album), track.artist)):
                            continue
                        album_ids.add(album_id)
                        response = self.request(f"v1/album/{album_id}", {})
                        found, budget = try_candidates(response_items(response, "songs"), budget, name)
                        if found:
                            return found
            # A compilation with similar duration is a fallback, not a reason
            # to skip looking for the requested album's original recording.
            found, _ = try_candidates(deferred, song_budget)
            if found:
                return found
            if not plain:
                # A title-only query recovers artists whose romanized name is
                # unknown to the search service. These remain unverified matches.
                response = self.request("search/get", {
                    "s": to_simplified(track.title), "type": 1, "limit": 30, "offset": 0,
                })
                suggestions.extend(response_items(response, "songs", search=True)[:30])
        except LookupCancelled:
            raise
        except LookupFailure:
            if plain:
                return plain
            if choices := recording_candidates(suggestions, track):
                raise RecordingChoiceRequired(choices)
            raise
        if not plain and (choices := recording_candidates(suggestions, track)):
            raise RecordingChoiceRequired(choices)
        return plain


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
        if (type(song_id) is not int or song_id <= 0 or not isinstance(title, str)
                or not title.strip() or not isinstance(artist, str) or not artist.strip()
                or not isinstance(album, str) or isinstance(record["duration"], bool)
                or not math.isfinite(duration) or duration <= 0):
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
    if synced and any(line.text for line in synced):
        return Lyrics(synced, source, True)
    if plain_text and plain_text.strip():
        return Lyrics(tuple(LyricLine(line.strip()) for line in plain_text.splitlines() if line.strip()),
                      source, False)
    return None


class LRCLIBProvider:
    def __init__(self, request=lrclib_request_json):
        self.request = request

    def lookup(self, track: Playback) -> Lyrics | None:
        if not track.title.strip() or not track.artist.strip() or not math.isfinite(track.duration) or track.duration <= 0:
            return None
        plain = None
        seen: set[int] = set()

        def select(records):
            nonlocal plain
            candidates = [(candidate, record) for record in records if isinstance(record, dict)
                          and (candidate := lrclib_candidate(record)) is not None and matches(candidate, track)]
            candidates.sort(key=lambda item: (
                normalize(item[0].album) != normalize(track.album),
                not bool(item[1].get("syncedLyrics")),
                abs(item[0].duration - track.duration), item[0].song_id,
            ))
            for candidate, record in candidates:
                if candidate.song_id in seen:
                    continue
                seen.add(candidate.song_id)
                decoded = decode_lrclib(record, candidate.song_id)
                if decoded and (decoded.synced or decoded.instrumental):
                    return decoded
                if decoded and plain is None:
                    plain = decoded
            return None

        try:
            exact = self.request("get", {
                "track_name": track.title, "artist_name": track.artist,
                "album_name": track.album, "duration": track.duration,
            })
            if exact is not None:
                found = select([exact])
                if found:
                    return found
            # Title-only searches allow alternate artist spellings; local
            # validation still checks the artist and recording duration.
            for title in dict.fromkeys((track.title, to_simplified(track.title), to_traditional(track.title))):
                records = self.request("search", {"track_name": title})
                if records is None:
                    continue
                if not isinstance(records, list):
                    raise LookupFailure("LRCLIB returned invalid search results.", retryable=True)
                found = select(records[:20])
                if found:
                    return found
        except LookupCancelled:
            raise
        except LookupFailure:
            if plain:
                return plain
            raise
        return plain


class LrcAPIProvider:
    """Public LrcAPI search; recording metadata is validated locally."""

    def __init__(self, request=None, *, cancelled=None):
        self.cancelled = cancelled
        self.request = request or (lambda params: http_json(
            "https://api.lrc.cx/jsonapi?" + urlencode(params), "LrcAPI", cancelled))

    @staticmethod
    def params(track):
        return {"title": track.title, "artist": track.artist, "album": track.album}

    def records(self, track):
        seen = set()
        for title in dict.fromkeys((track.title, to_simplified(track.title))):
            if self.cancelled and self.cancelled.is_set():
                raise LookupCancelled("Lyrics request cancelled.")
            records = self.request(self.params(track) | {"title": title})
            if records is None:
                continue
            if not isinstance(records, list):
                raise LookupFailure("LrcAPI returned invalid search results.", retryable=True)
            for record in records[:30]:
                candidate = self.candidate(record)
                if (candidate and candidate.reference not in seen
                        and normalize(candidate.title) == normalize(track.title)
                        and abs(candidate.duration - track.duration) <= 2):
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
                or not all(isinstance(s, str) for s in (title, artist, album))
                or not title.strip() or not artist.strip() or type(duration) not in (int, float)
                or not math.isfinite(duration) or duration <= 0):
            return None
        return Candidate(identifier, title, (artist,), album, duration, "lrcapi")

    @staticmethod
    def decode(candidate, record, track):
        text = record.get("lrc", record.get("lyrics"))
        if text is None or text == "":
            return None
        if not isinstance(text, str) or len(text) > 500000:
            raise LookupFailure("LrcAPI returned invalid lyrics data.", retryable=True)
        source = "LrcAPI https://api.lrc.cx/jsonapi?" + urlencode(LrcAPIProvider.params(track)) + "#" + candidate.song_id
        lines = parse_lrc(text)
        if lines and any(line.text for line in lines):
            if any(line.time > track.duration + 2 for line in lines):
                return None
            return Lyrics(lines, source, True)
        if "<tt" in text or "<html" in text:
            return None
        text = text.removeprefix("[!text]")
        plain = tuple(LyricLine(line.strip()) for line in text.splitlines()
                      if line.strip() and not re.fullmatch(r"(?:\[[^\]]*\]\s*)+", line.strip()))
        return Lyrics(plain, source, False) if plain else None

    def alternatives(self, track):
        return tuple(c for c, _ in self.records(track))[:30]

    def lyrics_for(self, identifier, track):
        for candidate, record in self.records(track):
            if candidate.song_id == identifier:
                return self.decode(candidate, record, track)
        return None

    def lookup(self, track):
        plain = None
        records = sorted(self.records(track), key=lambda item: (
            not credits_match(item[0].artists, track.artist),
            normalize(item[0].album) != normalize(track.album), abs(item[0].duration - track.duration)))
        for candidate, record in records:
            if not (credits_match(candidate.artists, track.artist)
                    or (normalize(track.album) and normalize(candidate.album) == normalize(track.album))):
                continue
            result = self.decode(candidate, record, track)
            if result and result.synced:
                return result
            plain = plain or result
        return plain


class LyricsProvider:
    """NetEase first, then LrcAPI and LRCLIB when they can improve the result."""

    def __init__(self, primary=None, fallback=None, *, lrcapi=None, cancelled: Event | None = None):
        self.cancelled = cancelled
        self.primary = primary if primary is not None else NetEaseProvider(
            lambda endpoint, params: request_json(endpoint, params, cancelled))
        self.fallback = fallback if fallback is not None else LRCLIBProvider(
            lambda endpoint, params: lrclib_request_json(endpoint, params, cancelled))
        self.lrcapi = lrcapi if lrcapi is not None else LrcAPIProvider(cancelled=cancelled)

    def check_cancelled(self):
        if self.cancelled is not None and self.cancelled.is_set():
            raise LookupCancelled("Lyrics request cancelled.")

    def lookup(self, track: Playback) -> Lyrics | None:
        primary = None
        errors = []
        choices = None
        self.check_cancelled()
        started = time.monotonic()
        event("provider_start", provider="NetEase", title=track.title, artist=track.artist)
        try:
            primary = self.primary.lookup(track)
        except LookupCancelled:
            raise
        except RecordingChoiceRequired as exc:
            choices = exc
            event("unverified_candidates", provider="NetEase", count=len(exc.candidates))
        except LookupFailure as exc:
            errors.append(exc)
            event("provider_error", provider="NetEase", error=str(exc))
        event("provider_end", provider="NetEase", seconds=round(time.monotonic() - started, 3),
              result="timed" if primary and primary.synced else "plain" if primary else "missing",
              errors=len(errors))
        self.check_cancelled()
        if primary and (primary.synced or primary.instrumental):
            return primary
        fallback = None
        for name, provider in (("LrcAPI", self.lrcapi), ("LRCLIB", self.fallback)):
            self.check_cancelled()
            started = time.monotonic()
            event("provider_start", provider=name, title=track.title, artist=track.artist)
            try:
                result = provider.lookup(track)
            except LookupCancelled:
                raise
            except LookupFailure as exc:
                errors.append(exc)
                event("provider_error", provider=name, error=str(exc))
                result = None
            self.check_cancelled()
            event("provider_end", provider=name, seconds=round(time.monotonic() - started, 3),
                  result="timed" if result and result.synced else "plain" if result else "missing")
            if result and (result.synced or (result.instrumental and not (primary or fallback))):
                return result
            fallback = fallback or result
        if primary:
            return primary
        if fallback:
            return fallback
        if choices:
            # Verified providers have had their chance. Try a bounded set of
            # unverified matches, without persisting an artist or recording alias.
            for candidate in choices.candidates[:3]:
                self.check_cancelled()
                try:
                    result = self.primary.lyrics_for(candidate.song_id)
                    if result:
                        return result
                except LookupCancelled:
                    raise
                except LookupFailure as exc:
                    errors.append(exc)
        if errors:
            raise LookupFailure("; ".join(str(error) for error in errors),
                                retryable=any(error.retryable for error in errors)) from errors[-1]
        return None
