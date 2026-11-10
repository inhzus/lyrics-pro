"""Read only the current Music track's artwork; never query another service."""

import base64
from pathlib import Path
import tempfile
from threading import Event

from .models import Playback
from .music import run_script


MAX_ARTWORK_BYTES = 4 * 1024 * 1024

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


def read_artwork(track: Playback, cancelled: Event) -> str | None:
    """Return base64 of bounded image bytes, or None for missing/stale artwork."""
    with tempfile.TemporaryDirectory(prefix="lyrics-pro-artwork-") as directory:
        target = Path(directory) / "cover"
        result = run_script(
            ["/usr/bin/osascript", "-e", ARTWORK_SCRIPT, track.title, track.artist, track.album,
             str(track.duration), str(target)], timeout=5, cancelled=cancelled,
        )
        if result.returncode:
            raise RuntimeError("Music artwork is temporarily unavailable.")
        if result.stdout.strip() != "ok" or not target.exists():
            return None
        if not 0 < target.stat().st_size <= MAX_ARTWORK_BYTES:
            return None
        return base64.b64encode(target.read_bytes()).decode("ascii")
