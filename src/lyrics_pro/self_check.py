"""Offline packaging check. Uses disposable storage, never Music or the network."""
from importlib.metadata import version
from pathlib import Path
import platform
import sqlite3
from tempfile import TemporaryDirectory

from .lyrics_cache import LyricsCache, annotation_version
from .models import Lyrics, LyricLine
from .pronunciation import HAN, Romanizer, normalize


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
    with TemporaryDirectory(prefix="lyrics-pro-check-") as temporary:
        cache = LyricsCache(Path(temporary) / "lyrics.sqlite3")
        raw = Lyrics((LyricLine("故鄉", 1),), "self-check", True)
        annotated = romanizer.annotate(raw, "hokkien")
        cache.put("self-check", raw)
        cache.put_annotation(raw, "hokkien", annotated)
        if cache.get("self-check") != raw or cache.annotated(raw, "hokkien") != annotated:
            raise RuntimeError("Bundled SQLite cache failed its self-check")
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
    }
