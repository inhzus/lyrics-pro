import io
import json
from queue import Queue
from threading import Event

import pytest

from lyrics_pro.bridge import read_commands
from lyrics_pro.models import Playback
from lyrics_pro.protocol import (
    ChooseRecording, ForgetRecording, ListRecordings, PlaybackControl, RetryLyrics, SetLanguage,
    SetSongLanguage, event_frame, parse_command, track_object,
)


A = Playback("paused", "A", "Artist", "Album", 200, 12)
TRACK = track_object(A.key)


def frame(kind, **payload):
    return {"version": 2, "type": kind, "payload": payload}


def read(*messages):
    queue = Queue()
    read_commands(io.StringIO("\n".join(m if isinstance(m, str) else json.dumps(m) for m in messages)),
                  queue, Event())
    return [queue.get_nowait() for _ in range(queue.qsize())]


def test_every_command_parses_to_its_typed_intent():
    assert read(
        frame("set_language", language="hokkien", request_id=2),
        frame("set_song_language", request_id=3, generation=1, track=TRACK, song_language="default"),
        frame("retry_lyrics", request_id=4, generation=1, retry_artwork=True),
        frame("list_recordings", request_id=5, generation=1),
        frame("choose_recording", request_id=6, generation=1, recording_id="lrcapi:1447841672", choice_request_id=5),
        frame("forget_recording", request_id=7, generation=1),
        frame("playback_control", command_id=1, generation=1, track=TRACK, action="seek", position=90),
        frame("playback_control", command_id=2, generation=1, track=TRACK, action="next", position=None),
    ) == [
        SetLanguage("hokkien", 2),
        SetSongLanguage(3, 1, A.key, "default"),
        RetryLyrics(4, 1, True),
        ListRecordings(5, 1),
        ChooseRecording(6, 1, "lrcapi:1447841672", 5),
        ForgetRecording(7, 1),
        PlaybackControl(1, 1, A.key, "seek", 90),
        PlaybackControl(2, 1, A.key, "next", None),
    ]


def test_retry_artwork_defaults_to_false():
    assert parse_command(frame("retry_lyrics", request_id=1, generation=0)) == RetryLyrics(1, 0, False)


@pytest.mark.parametrize("message", [
    {"version": 1, "type": "set_language", "payload": {"language": "cantonese", "request_id": 1}},
    {"type": "set_language", "payload": {"language": "cantonese", "request_id": 1}},
    {"version": 2, "type": "retry", "payload": {}},
    {"version": 2, "type": "set_language", "payload": []},
    {"version": 2, "type": "set_language", "language": "cantonese", "request_id": 1},
    [], "text", None,
])
def test_wrong_version_type_or_envelope_is_rejected(message):
    assert parse_command(message) is None


VALID = {
    "set_language": dict(language="cantonese", request_id=2),
    "set_song_language": dict(request_id=1, generation=1, track=TRACK, song_language="default"),
    "retry_lyrics": dict(request_id=1, generation=1, retry_artwork=False),
    "choose_recording": dict(request_id=2, generation=3, recording_id="netease:5284269", choice_request_id=1),
    "playback_control": dict(command_id=1, generation=1, track=TRACK, action="seek", position=90),
}


@pytest.mark.parametrize("kind,field,value", [
    ("set_language", "language", []), ("set_language", "language", "supplied"),
    ("set_language", "request_id", True), ("set_language", "request_id", -1),
    ("set_song_language", "song_language", "auto"), ("set_song_language", "song_language", []),
    ("set_song_language", "generation", True), ("set_song_language", "request_id", True),
    ("set_song_language", "track", []), ("set_song_language", "track", list(A.key)),
    ("set_song_language", "track", TRACK | {"title": ""}),
    ("retry_lyrics", "generation", None), ("retry_lyrics", "retry_artwork", 1),
    ("choose_recording", "recording_id", True), ("choose_recording", "recording_id", 5284269),
    ("choose_recording", "recording_id", "unknown:1"), ("choose_recording", "recording_id", "lrcapi:https://bad"),
    ("choose_recording", "recording_id", "netease:0"), ("choose_recording", "choice_request_id", None),
    ("choose_recording", "generation", "3"),
    ("playback_control", "position", float("nan")), ("playback_control", "position", float("inf")),
    ("playback_control", "position", True), ("playback_control", "position", None),
    ("playback_control", "command_id", True), ("playback_control", "command_id", 0),
    ("playback_control", "generation", -1), ("playback_control", "action", "delete"),
    ("playback_control", "track", TRACK | {"duration": float("inf")}),
    ("playback_control", "track", {"title": "A", "artist": "B"}),
])
def test_invalid_fields_reject_the_command(kind, field, value):
    assert parse_command(frame(kind, **VALID[kind])) is not None
    assert parse_command(frame(kind, **VALID[kind] | {field: value})) is None


def test_bad_lines_are_skipped_without_stopping():
    valid = frame("set_language", language="cantonese", request_id=2)
    assert read("garbage", "[]", '{"version":2,"type":"set_language","payload":{"request_id":1e999}}',
                valid) == [SetLanguage("cantonese", 2)]


@pytest.mark.parametrize("message", ["", json.dumps(frame("shutdown")) + "\n", "x" * 65537])
def test_parent_eof_shutdown_or_oversized_command_cancels(message):
    stopped, queue = Event(), Queue()
    read_commands(io.StringIO(message + json.dumps(frame("set_language", language="cantonese", request_id=1))
                              if message.startswith("{") else message), queue, stopped)
    assert stopped.is_set() and queue.empty()


def test_event_frames_carry_track_objects_and_payloads():
    assert event_frame("ready", 0, None) == {"version": 2, "type": "ready", "generation": 0,
                                             "track": None, "payload": {}}
    assert event_frame("artwork", 3, A.key, {"image": None})["track"] == {
        "title": "A", "artist": "Artist", "album": "Album", "duration": 200}
