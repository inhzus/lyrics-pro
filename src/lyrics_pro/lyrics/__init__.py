"""Online lyric providers: NetEase, then LrcAPI and LRCLIB fallbacks.

Module map: ``transport`` (bounded curl), ``lrc`` (parsing), ``matching``
(recording identity), one module per provider, and ``chain`` (provider order
and explicit recording selection).
"""

from ..models import Candidate
from .chain import LyricsProvider, discover_recordings, lookup, lookup_recording
from .lrc import parse_lrc, plain_lines
from .lrcapi import LrcAPIProvider
from .lrclib import LRCLIBProvider, decode_lrclib, lrclib_candidate, lrclib_request_json
from .matching import credits_match, matches
from .netease import (
    NetEaseProvider, RecordingChoiceRequired, artist_names, candidate_from_record, decode_record,
    recording_candidates, request_json, response_items,
)
from .transport import http_json, run_curl

__all__ = [
    "Candidate", "LRCLIBProvider", "LrcAPIProvider", "LyricsProvider", "NetEaseProvider",
    "RecordingChoiceRequired", "artist_names", "candidate_from_record", "credits_match",
    "decode_lrclib", "decode_record", "discover_recordings", "http_json", "lookup", "lookup_recording",
    "lrclib_candidate", "lrclib_request_json", "matches", "parse_lrc", "plain_lines",
    "recording_candidates", "request_json", "response_items", "run_curl",
]
