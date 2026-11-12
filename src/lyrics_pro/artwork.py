"""Local Music artwork with a strictly matched Apple catalog fallback."""

import base64
import math
from pathlib import Path
import re
import subprocess
import tempfile
from threading import Event
import time
from urllib.parse import urlencode, urlsplit

from .diagnostics import event
from .lyrics import http_json
from .models import Playback, LookupFailure, LookupCancelled
from .music import run_script, MusicCancelled
from .pronunciation import normalize, artist_key


MAX_ARTWORK_BYTES = 4 * 1024 * 1024


class ArtworkFailure(Exception):
    def __init__(self, category, *, retryable=False):
        super().__init__(category)
        self.retryable = retryable


def check_cancelled(cancelled):
    if cancelled.is_set():
        raise MusicCancelled()


def valid_image(path, cancelled):
    """Inspect image headers off the UI thread using macOS's bundled decoder."""
    if not path.exists() or not 0 < path.stat().st_size <= MAX_ARTWORK_BYTES:
        return False
    result = run_script(["/usr/bin/sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
                        timeout=5, cancelled=cancelled)
    dimensions = re.findall(r"pixel(?:Width|Height):\s*(\d+)", result.stdout)
    return result.returncode == 0 and len(dimensions) == 2 and all(0 < int(n) <= 8192 for n in dimensions)


def apple_image_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return False
    try:
        url = urlsplit(value)
        return (url.scheme == "https" and url.hostname is not None
                and url.hostname.endswith(".mzstatic.com") and url.port in (None, 443)
                and not url.username and not url.password and not url.fragment)
    except ValueError:
        return False


def select_cover(records, track):
    """Accept only one unambiguous cover for the exact album and recording."""
    urls = set()
    for row in records[:50]:
        if not isinstance(row, dict):
            continue
        fields = [row.get(k) for k in ("trackName", "artistName", "collectionName")]
        duration = row.get("trackTimeMillis")
        if (not all(isinstance(v, str) and normalize(v) for v in fields)
                or type(duration) not in (float, int) or not math.isfinite(duration)):
            continue
        title, artist, album = fields
        if (normalize(title) == normalize(track.title) and artist_key(artist) == artist_key(track.artist)
                and normalize(album) == normalize(track.album) and abs(duration / 1000 - track.duration) <= 2
                and apple_image_url(row.get("artworkUrl100"))):
            urls.add(row["artworkUrl100"])
    if len(urls) > 1:
        raise ArtworkFailure("ambiguous_catalog_match")
    return next(iter(urls)) if urls else None


def download_catalog_cover(url, cancelled):
    """Request a larger rendition only for recognized Apple thumbnail paths."""
    if not apple_image_url(url):
        raise ArtworkFailure("invalid_artwork_url")
    parsed = urlsplit(url)
    path = re.sub(r"/100x100((?:bb|-\d+)?\.(?:jpg|jpeg|png))$", r"/1000x1000\1", parsed.path)
    large_url = parsed._replace(path=path).geturl()
    if large_url != url:
        check_cancelled(cancelled)
        try:
            return download_cover(large_url, cancelled)
        except (ArtworkFailure, subprocess.TimeoutExpired):
            event("artwork_thumbnail_fallback", reason="large_rendition_unavailable")
    check_cancelled(cancelled)
    return download_cover(url, cancelled)


def catalog_artwork(track, cancelled):
    if (not all(normalize(v) for v in (track.title, track.artist, track.album))
            or not math.isfinite(track.duration) or track.duration <= 0):
        return None
    for country in ("tw", "us"):
        check_cancelled(cancelled)
        query = urlencode(dict(term=f"{track.title} {track.artist}", entity="song", country=country, limit=50))
        try:
            response = http_json("https://itunes.apple.com/search?" + query, "Apple artwork", cancelled)
        except LookupCancelled as exc:
            raise MusicCancelled() from exc
        except LookupFailure as exc:
            raise ArtworkFailure("catalog_request_failed", retryable=exc.retryable) from exc
        if not isinstance(response, dict) or not isinstance(response.get("results"), list):
            raise ArtworkFailure("invalid_catalog_response", retryable=True)
        url = select_cover(response["results"], track)
        if url:
            return download_catalog_cover(url, cancelled)
    return None


def download_cover(url, cancelled):
    if not apple_image_url(url):
        raise ArtworkFailure("invalid_artwork_url")
    with tempfile.TemporaryDirectory(prefix="lyrics-pro-artwork-") as directory:
        path = Path(directory) / "cover"
        # Do not follow redirects: only the validated Apple CDN host is contacted.
        result = run_script(["/usr/bin/curl", "-4", "--silent", "--show-error", "--proto", "=https",
                             "--connect-timeout", "5", "--max-time", "15", "--max-filesize",
                             str(MAX_ARTWORK_BYTES), "--output", str(path), "--write-out", "%{http_code}", url],
                            timeout=17, cancelled=cancelled)
        if result.returncode:
            raise ArtworkFailure("image_download_failed", retryable=result.returncode in (5, 6, 7, 18, 28, 52, 55, 56))
        status = result.stdout.strip()
        if status != "200":
            raise ArtworkFailure("image_http_" + status, retryable=status == "429" or status.startswith("5"))
        if not valid_image(path, cancelled):
            raise ArtworkFailure("invalid_image")
        return base64.b64encode(path.read_bytes()).decode("ascii")

# All metadata and paths are arguments, never interpolated into script source.
# Check metadata before and after retrieval to reject a track switch during a read.
ARTWORK_SCRIPT = r'''
on matchesTrack(t, args)
    tell application "Music"
        return (name of t = item 1 of args) and (artist of t = item 2 of args) and (album of t = item 3 of args) and ((duration of t) > ((item 4 of args as real) - 0.05)) and ((duration of t) < ((item 4 of args as real) + 0.05))
    end tell
end matchesTrack

on run args
    if application "Music" is not running then return "stale"
    tell application "Music"
        if player state is stopped then return "stale"
        set t to current track
    end tell
    if not matchesTrack(t, args) then return "stale"
    tell application "Music"
        if (count of artworks of t) is 0 then return "missing"
        set pictureData to raw data of artwork 1 of t
        set current to current track
    end tell
    if not matchesTrack(current, args) then return "stale"
    set outputFile to open for access (POSIX file (item 5 of args)) with write permission
    try
        set eof outputFile to 0
        write pictureData to outputFile
        close access outputFile
    on error errorMessage number errorNumber
        close access outputFile
        error errorMessage number errorNumber
    end try
    return "ok"
end run
'''


def read_local_artwork(track: Playback, cancelled: Event) -> str | None:
    """Return base64 of bounded image bytes, or None for missing/stale artwork."""
    with tempfile.TemporaryDirectory(prefix="lyrics-pro-artwork-") as directory:
        target = Path(directory) / "cover"
        result = run_script(
            ["/usr/bin/osascript", "-e", ARTWORK_SCRIPT, track.title, track.artist, track.album,
             str(track.duration), str(target)], timeout=5, cancelled=cancelled,
        )
        if result.returncode:
            if "-1743" in result.stderr or "not authorized" in result.stderr.lower():
                raise ArtworkFailure("permission_denied")
            raise ArtworkFailure("local_extraction_failed", retryable=True)
        if result.stdout.strip() == "stale":
            raise MusicCancelled()
        if result.stdout.strip() != "ok" or not target.exists():
            return None
        if not valid_image(target, cancelled):
            return None
        return base64.b64encode(target.read_bytes()).decode("ascii")


def read_artwork(track: Playback, cancelled: Event) -> str | None:
    started = time.monotonic()
    for attempt, delay in enumerate((0, 2, 8), 1):
        if cancelled.wait(delay):
            raise MusicCancelled()
        local_failure = None
        try:
            try:
                image = read_local_artwork(track, cancelled)
            except ArtworkFailure as exc:
                if str(exc) == "permission_denied":
                    raise
                local_failure, image = exc, None
            except subprocess.TimeoutExpired:
                local_failure, image = ArtworkFailure("local_timeout", retryable=True), None
            source = "music"
            if image is None:
                event("artwork_local_missing", category=str(local_failure) if local_failure else "missing", attempt=attempt)
                image, source = catalog_artwork(track, cancelled), "apple_catalog"
            check_cancelled(cancelled)
            if image is None and local_failure is not None:
                raise local_failure
            event("artwork_result", source=source, outcome="success" if image else "missing",
                  bytes=len(base64.b64decode(image)) if image else 0, seconds=round(time.monotonic()-started, 3))
            return image
        except (ArtworkFailure, subprocess.TimeoutExpired) as exc:
            retryable = isinstance(exc, subprocess.TimeoutExpired) or exc.retryable
            event("artwork_failure", category="timeout" if isinstance(exc, subprocess.TimeoutExpired) else str(exc),
                  attempt=attempt, retryable=retryable, seconds=round(time.monotonic()-started, 3))
            if not retryable or attempt == 3:
                return None
    return None
