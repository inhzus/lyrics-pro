"""Version 2 worker protocol (docs/protocol.md): typed commands and event frames."""

from dataclasses import dataclass
import math

from .recording_ref import recording_ref
from .song_languages import LANGUAGES


VERSION = 2
MAX_COMMAND_BYTES = 65536
ACTIONS = frozenset({"play", "pause", "next", "previous", "seek"})
SONG_LANGUAGES = LANGUAGES | {"default"}
DATA_TARGETS = ("lyrics_cache", "recording_choices", "song_languages")

Track = tuple[str, str, str, float]


@dataclass(frozen=True)
class SetLanguage:
    language: str
    request_id: int


@dataclass(frozen=True)
class SetSongLanguage:
    request_id: int
    generation: int
    track: Track
    song_language: str


@dataclass(frozen=True)
class RetryLyrics:
    request_id: int
    generation: int
    retry_artwork: bool


@dataclass(frozen=True)
class ListRecordings:
    request_id: int
    generation: int


@dataclass(frozen=True)
class ChooseRecording:
    request_id: int
    generation: int
    recording_id: str
    choice_request_id: int


@dataclass(frozen=True)
class ForgetRecording:
    request_id: int
    generation: int


@dataclass(frozen=True)
class PlaybackControl:
    command_id: int
    generation: int
    track: Track
    action: str
    position: float | None = None


@dataclass(frozen=True)
class GetDataStats:
    pass


@dataclass(frozen=True)
class ClearData:
    targets: tuple[str, ...]


@dataclass(frozen=True)
class Shutdown:
    pass


LyricCommand = SetLanguage | SetSongLanguage | RetryLyrics | ListRecordings | ChooseRecording | ForgetRecording
DataCommand = GetDataStats | ClearData
Command = LyricCommand | PlaybackControl | DataCommand | Shutdown


class InvalidCommand(ValueError):
    pass


def _require(condition):
    if not condition:
        raise InvalidCommand


def _count(value, *, positive=False) -> int:
    _require(type(value) is int and value >= (1 if positive else 0))
    return value


def _number(value) -> float:
    _require(type(value) in (int, float) and math.isfinite(value))
    return value


def _choice(value, choices) -> str:
    _require(isinstance(value, str) and value in choices)
    return value


def _track(value) -> Track:
    _require(isinstance(value, dict))
    title, artist, album = (value.get(key) for key in ("title", "artist", "album"))
    _require(isinstance(title, str) and title and isinstance(artist, str) and isinstance(album, str))
    duration = _number(value.get("duration"))
    _require(duration >= 0)
    return title, artist, album, duration


def _recording(value) -> str:
    _require(isinstance(value, str) and recording_ref(value) is not None)
    return value


def _playback_control(p) -> PlaybackControl:
    action = _choice(p.get("action"), ACTIONS)
    position = _number(p.get("position")) if action == "seek" else None
    return PlaybackControl(_count(p.get("command_id"), positive=True), _count(p.get("generation")),
                           _track(p.get("track")), action, position)


def _retry_lyrics(p) -> RetryLyrics:
    retry_artwork = p.get("retry_artwork", False)
    _require(type(retry_artwork) is bool)
    return RetryLyrics(_count(p.get("request_id")), _count(p.get("generation")), retry_artwork)


def _clear_data(p) -> ClearData:
    targets = p.get("targets")
    _require(isinstance(targets, list) and targets and len(set(map(str, targets))) == len(targets)
             and all(isinstance(t, str) and t in DATA_TARGETS for t in targets))
    return ClearData(tuple(targets))


PARSERS = {
    "set_language": lambda p: SetLanguage(_choice(p.get("language"), LANGUAGES), _count(p.get("request_id"))),
    "set_song_language": lambda p: SetSongLanguage(_count(p.get("request_id")), _count(p.get("generation")),
                                                   _track(p.get("track")),
                                                   _choice(p.get("song_language"), SONG_LANGUAGES)),
    "retry_lyrics": _retry_lyrics,
    "list_recordings": lambda p: ListRecordings(_count(p.get("request_id")), _count(p.get("generation"))),
    "choose_recording": lambda p: ChooseRecording(_count(p.get("request_id")), _count(p.get("generation")),
                                                  _recording(p.get("recording_id")),
                                                  _count(p.get("choice_request_id"))),
    "forget_recording": lambda p: ForgetRecording(_count(p.get("request_id")), _count(p.get("generation"))),
    "playback_control": _playback_control,
    "get_data_stats": lambda p: GetDataStats(),
    "clear_data": _clear_data,
    "shutdown": lambda p: Shutdown(),
}


def parse_command(message) -> Command | None:
    """Return the typed command for a decoded frame, or None if it is invalid."""
    if not isinstance(message, dict) or message.get("version") != VERSION:
        return None
    parser = PARSERS.get(message.get("type"))
    payload = message.get("payload", {})
    if parser is None or not isinstance(payload, dict):
        return None
    try:
        return parser(payload)
    except InvalidCommand:
        return None


def track_object(key: Track | None) -> dict | None:
    if key is None:
        return None
    title, artist, album, duration = key
    return {"title": title, "artist": artist, "album": album, "duration": duration}


def event_frame(kind: str, generation: int, track: Track | None, payload: dict | None = None) -> dict:
    return {"version": VERSION, "type": kind, "generation": generation,
            "track": track_object(track), "payload": payload or {}}
