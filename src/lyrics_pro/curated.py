"""Offline, pre-aligned proofread recordings. Never align or generate readings here."""
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
import json
import math

from .diagnostics import event
from .lyrics_cache import decode
from .lyrics import Candidate
from .models import LookupCancelled, Lyrics
from .pronunciation import normalize
from .recording_ref import recording_ref, source_ref


@dataclass(frozen=True)
class CuratedRecording:
    title: str
    artist: str
    album: str
    duration: float
    reference: str
    lyrics: Lyrics
    title_aliases: tuple[str, ...] = ()


def _decode_asset(payload):
    obj = json.loads(payload)
    report = obj["alignment"]
    aliases = obj.get("title_aliases", [])
    if (not isinstance(aliases, list) or len(aliases) > 12
            or any(not isinstance(a, str) or not normalize(a) or len(a) > 256 for a in aliases)):
        raise ValueError("Invalid proofread title aliases")
    reference = recording_ref(report["recording_id"])
    asset_reference = recording_ref("proofread:" + obj["id"]) if isinstance(obj["id"], str) else None
    if (obj["schema_version"] != 1 or not isinstance(obj["title"], str)
            or not normalize(obj["title"]) or type(obj["duration"]) not in (int, float)
            or not math.isfinite(obj["duration"]) or obj["duration"] <= 0
            or not isinstance(obj["artist"], str) or not obj["artist"].strip()
            or not isinstance(obj["album"], str) or asset_reference is None
            or reference is None or not isinstance(report["timing_source"], str)
            or source_ref(report["timing_source"]) != reference
            or not isinstance(report["rows"], list) or not 1 <= len(report["rows"]) <= 500):
        raise ValueError("Invalid proofread recording")
    lines, previous = [], -1
    for row in report["rows"]:
        status, stamp = row["status"], row["time"]
        if (status not in ("exact", "approximate", "repeat", "gap", "credit")
                or type(stamp) not in (int, float) or not math.isfinite(stamp)
                or stamp < previous or stamp < 0 or stamp > obj["duration"]):
            raise ValueError("Invalid proofread timing")
        text, spelling = row["text"], row["spelling"]
        if not isinstance(text, str) or not isinstance(spelling, str):
            raise ValueError("Invalid proofread text or spelling")
        if status in ("exact", "approximate", "repeat"):
            if not isinstance(text, str) or not text.strip() or not isinstance(spelling, str) or not spelling.strip():
                raise ValueError("Missing supplied lyric or spelling")
        elif status == "gap" and (text or spelling):
            raise ValueError("Nonempty musical gap")
        # Source columns are transcription layout, not sung pauses. Normalize
        # presentation only; retain original wording, accents, and timing inputs.
        text, spelling = " ".join(text.split()), " ".join(spelling.split())
        lines.append(dict(text=text, time=stamp, pronunciation=spelling or None))
        previous = stamp
    source = "Proofread " + report["timing_source"].split(" ", 1)[1]
    lyrics = decode(json.dumps(dict(lines=lines, source=source, synced=True, recording_id=asset_reference,
        instrumental=False, proofread=dict(asset_id=obj["id"], revision=obj["revision"],
                                          language=obj["language"], attribution=obj["attribution"]))))
    return CuratedRecording(obj["title"], obj["artist"], obj["album"], obj["duration"], asset_reference, lyrics, tuple(aliases))


@lru_cache(maxsize=1)
def _recordings():
    results = []
    try:
        assets = sorted(files("lyrics_pro").joinpath("data", "proofread").iterdir(), key=lambda p: p.name)
        for asset in assets:
            if asset.name.endswith(".json"):
                try:
                    results.append(_decode_asset(asset.read_text(encoding="utf-8")))
                except (OSError, ValueError, TypeError, KeyError):
                    event("proofread_asset_invalid", asset=asset.name)
    except (OSError, ModuleNotFoundError):
        event("proofread_assets_unavailable")
    return tuple(results)


def _matching(track, cancelled=None):
    def check():
        if cancelled is not None and cancelled.is_set():
            raise LookupCancelled("Lyrics request cancelled.")
    check()
    if not math.isfinite(track.duration) or track.duration <= 0:
        return
    title = normalize(track.title)
    for recording in _recordings():
        check()
        titles = (recording.title, *recording.title_aliases)
        if title in {normalize(t) for t in titles} and abs(track.duration - recording.duration) <= 2:
            yield recording
    check()


def curated_candidates(track, cancelled=None):
    return tuple(Candidate(r.lyrics.proofread.asset_id, r.title, (r.artist,), r.album, r.duration, "proofread")
                 for r in _matching(track, cancelled))[:30]


def curated_lyrics(track, reference=None, cancelled=None):
    qualified = recording_ref(reference) if reference is not None else None
    if reference is not None and (qualified is None or not qualified.startswith("proofread:")):
        if cancelled is not None and cancelled.is_set():
            raise LookupCancelled("Lyrics request cancelled.")
        return None
    for recording in _matching(track, cancelled):
        if reference is None or qualified == recording.reference:
            return recording.lyrics
    return None
