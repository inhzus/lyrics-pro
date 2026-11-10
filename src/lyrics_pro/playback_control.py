"""Bounded Apple Music playback commands; no shell or interpolated scripts."""

import json
import math
import subprocess

from .music import MusicError, run_script


ACTIONS = {"play", "pause", "next", "previous", "seek"}

SCRIPT = r'''
function run(argv) {
    const request = JSON.parse(argv[0]);
    const app = Application("Music");
    function failure(code, message) { return JSON.stringify({ok: false, code, message}); }
    if (!app.running()) return failure("unavailable", "Open Music and choose a song first.");
    const state = app.playerState();
    if (state !== "playing" && state !== "paused")
        return failure("unavailable", "Choose a playing or paused song in Music first.");
    const track = app.currentTrack();
    const expected = request.track;
    if (track.name() !== expected[0] || track.artist() !== expected[1] ||
        track.album() !== expected[2] || Math.abs(track.duration() - expected[3]) > 0.02)
        return failure("stale_track", "The song changed. Try the control again.");
    switch (request.action) {
        case "play": app.play(); break;
        case "pause": app.pause(); break;
        case "next": app.nextTrack(); break;
        case "previous":
            // Music can treat previousTrack as restart when past the beginning.
            // Reset first so one user action consistently selects the previous song.
            app.playerPosition = 0;
            app.previousTrack();
            break;
        case "seek":
            const duration = track.duration();
            if (!Number.isFinite(duration) || duration <= 0)
                return failure("unseekable", "This track does not have a seekable duration.");
            app.playerPosition = Math.min(duration, Math.max(0, request.position));
            break;
        default: return failure("invalid_command", "Unsupported playback control.");
    }
    return JSON.stringify({ok: true});
}
'''


def valid_command(message):
    track = message.get("track")
    return (
        message.get("command") == "playback_control"
        and message.get("action") in ACTIONS
        and type(message.get("command_id")) is int and message["command_id"] > 0
        and type(message.get("generation")) is int and message["generation"] >= 0
        and isinstance(track, list) and len(track) == 4
        and all(isinstance(value, str) for value in track[:3]) and bool(track[0])
        and type(track[3]) in (int, float) and math.isfinite(track[3]) and track[3] >= 0
        and (message["action"] != "seek" or (
            type(message.get("position")) in (int, float) and math.isfinite(message["position"])))
    )


def control_playback(message, *, cancelled=None):
    if not valid_command(message):
        raise MusicError("Invalid playback request.", code="invalid_command")
    try:
        result = run_script(["/usr/bin/osascript", "-l", "JavaScript", "-e", SCRIPT,
                             json.dumps(message, ensure_ascii=False, allow_nan=False)],
                            timeout=4, cancelled=cancelled)
    except subprocess.TimeoutExpired as exc:
        raise MusicError("Music did not confirm the control. Check playback before trying again.",
                         code="control_timeout") from exc
    except FileNotFoundError as exc:
        raise MusicError("Apple Music scripting is unavailable.") from exc
    if result.returncode:
        denied = "-1743" in result.stderr or "not authorized" in result.stderr.lower()
        raise MusicError("Enable Music access for Lyrics Pro in System Settings > Privacy & Security > Automation."
                         if denied else "Music could not complete the playback control. Try again.",
                         code="permission_denied" if denied else "control_failed")
    try:
        response = json.loads(result.stdout)
        if type(response.get("ok")) is not bool:
            raise ValueError("Missing result")
    except (ValueError, AttributeError) as exc:
        raise MusicError("Music returned an invalid control result.", code="control_failed") from exc
    if not response["ok"]:
        raise MusicError(response.get("message", "Music could not complete the control."),
                         code=response.get("code", "control_failed"))
