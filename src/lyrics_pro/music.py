import json
import math
import subprocess
import time
from threading import Event

from .models import Playback


SCRIPT = r'''
const app = Application("Music");
if (!app.running()) {
    JSON.stringify({state: "closed"});
} else {
    const state = app.playerState();
    if (state === "stopped") {
        JSON.stringify({state});
    } else {
        const track = app.currentTrack();
        JSON.stringify({state, title: track.name(), artist: track.artist(),
            album: track.album(), duration: track.duration(),
            position: app.playerPosition()});
    }
}
'''


class MusicError(Exception):
    def __init__(self, message: str, code: str = "music_unavailable"):
        super().__init__(message)
        self.code = code


class MusicCancelled(Exception):
    pass


def run_script(args: list[str], *, timeout: float, cancelled: Event | None = None):
    """Bound script execution and reap its process when the GUI worker stops."""
    if cancelled is None:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if cancelled.is_set():
        raise MusicCancelled()
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + timeout
    try:
        while True:
            if cancelled.is_set():
                raise MusicCancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(args, timeout)
            try:
                stdout, stderr = process.communicate(timeout=min(0.1, remaining))
                # A script that ends after cancellation was usually stopped by it;
                # its exit status is not evidence about Music.
                if cancelled.is_set():
                    raise MusicCancelled()
                return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                continue
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


def read_playback(*, cancelled: Event | None = None, permission_owner: str = "your terminal") -> Playback:
    try:
        result = run_script(
            ["/usr/bin/osascript", "-l", "JavaScript", "-e", SCRIPT],
            timeout=4, cancelled=cancelled,
        )
    except subprocess.TimeoutExpired as exc:
        raise MusicError("Music did not respond; waiting to reconnect.") from exc
    except FileNotFoundError as exc:
        raise MusicError("osascript is unavailable. This app requires macOS.") from exc
    if result.returncode:
        if "-1743" in result.stderr or "not authorized" in result.stderr.lower():
            raise MusicError(
                f"Music Automation permission denied. Enable Music for {permission_owner} "
                "in System Settings > Privacy & Security > Automation, then retry.",
                code="permission_denied",
            )
        raise MusicError("Cannot read Music; waiting to reconnect. " + result.stderr.strip())
    try:
        data = json.loads(result.stdout)
        playback = Playback(**data)
        if playback.state not in {"closed", "stopped", "paused", "playing", "fast forwarding", "rewinding"}:
            raise ValueError("unknown player state")
        if not all(isinstance(x, str) for x in (playback.title, playback.artist, playback.album)):
            raise ValueError("invalid metadata")
        if not all(math.isfinite(x) for x in (playback.duration, playback.position)):
            raise ValueError("non-finite playback time")
        return playback
    except (ValueError, TypeError) as exc:
        raise MusicError("Music returned an invalid playback snapshot; retrying.") from exc
