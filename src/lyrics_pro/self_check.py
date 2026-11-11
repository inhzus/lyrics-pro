"""Offline packaging check. Uses disposable storage, never Music or the network."""
from importlib.metadata import version
from pathlib import Path
import platform
import sqlite3
from tempfile import TemporaryDirectory

from .lyrics_cache import LyricsCache, annotation_version
from .models import Lyrics, LyricLine, Playback
from .pronunciation import HAN, Romanizer, normalize, choose_language
from .curated import curated_lyrics, curated_candidates


def self_check():
    versions = {name: version(name) for name in ("ToJyutping", "taibun", "msgpack")}
    romanizer = Romanizer()
    readings = {
        "cantonese": romanizer.line("令神仙鱼归天要怪谁", "cantonese"),
        "hokkien": romanizer.line("故鄉", "hokkien"),
    }
    if any(not text or HAN.search(text) or "?" in text for text in readings.values()):
        raise RuntimeError("Bundled pronunciation dictionaries failed their self-check")
    if normalize("故乡") != normalize("故鄉"):
        raise RuntimeError("Bundled simplified/traditional dictionary is unavailable")
    curated = curated_lyrics(Playback("paused", "少年吔，安啦！", "Different credit", "Compilation", 413.786))
    if (curated is None or len(curated.lines) != 58
            or curated.recording_id != "proofread:shao-nian-eh-an-la"
            or not curated.source.startswith("Proofread ")
            or choose_language("Different credit", "auto", curated)[0] != "hokkien"
            or romanizer.annotate(curated, "hokkien") != curated
            or curated.lines[3].pronunciation != "muá-pak ê hīn-khì m̄ tsai tùi dùi-thâu"
            or any(line.pronunciation for line in romanizer.annotate(curated, None).lines)):
        raise RuntimeError("Bundled proofread lyrics failed their self-check")
    candidates = curated_candidates(Playback("paused", "少年吔，安啦！", "", "", 413.786))
    if len(candidates) != 1 or candidates[0].reference != curated.recording_id:
        raise RuntimeError("Bundled proofread source discovery failed")
    with TemporaryDirectory(prefix="lyrics-pro-check-") as temporary:
        cache = LyricsCache(Path(temporary) / "lyrics.sqlite3")
        raw = Lyrics((LyricLine("故鄉", 1),), "self-check", True)
        annotated = romanizer.annotate(raw, "hokkien")
        cache.put("self-check", raw)
        cache.put_annotation(raw, "hokkien", annotated)
        if cache.get("self-check") != raw or cache.annotated(raw, "hokkien") != annotated:
            raise RuntimeError("Bundled SQLite cache failed its self-check")
        cache.put("proofread-check", curated)
        if cache.get("proofread-check") != curated:
            raise RuntimeError("Proofread cache round-trip failed")
        # Exercise log I/O without modifying the user's real logs or logger setup.
        from logging.handlers import RotatingFileHandler
        import logging
        handler = RotatingFileHandler(Path(temporary) / "check.log", maxBytes=128, backupCount=1)
        try:
            for _ in range(3):
                handler.emit(logging.makeLogRecord({"msg": "packaging self-check " * 4}))
        finally:
            handler.close()
        if not (Path(temporary) / "check.log.1").exists():
            raise RuntimeError("Rolling log self-check failed")
    return {
        "ok": True, "python": platform.python_version(), "architecture": platform.machine(),
        "packages": versions, "sqlite": sqlite3.sqlite_version,
        "annotation_versions": {language: annotation_version(language) for language in readings},
        "pronunciation": readings,
        "proofread_asset": curated.proofread.asset_id,
    }
