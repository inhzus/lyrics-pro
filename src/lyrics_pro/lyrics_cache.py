"""Best-effort, bounded SQLite cache shared by the native and terminal clients."""
from dataclasses import asdict
import hashlib
from importlib.metadata import version, PackageNotFoundError
import json
from pathlib import Path
import sqlite3
import time

from .diagnostics import SUPPORT, event
from .models import Lyrics, LyricLine, Proofread
from .recording_ref import recording_ref


def encode(lyrics):
    return json.dumps(asdict(lyrics), ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def decode(payload):
    import math
    obj = json.loads(payload)
    if (not isinstance(obj, dict) or not isinstance(obj.get("source"), str)
            or type(obj.get("synced")) is not bool or type(obj.get("instrumental")) is not bool
            or not isinstance(obj.get("lines"), list) or len(obj["lines"]) > 10000):
        raise ValueError("Invalid cached lyrics")
    lines = []
    for line in obj["lines"]:
        text, stamp, pronunciation = line["text"], line.get("time"), line.get("pronunciation")
        if (not isinstance(text, str) or pronunciation is not None and not isinstance(pronunciation, str)
                or stamp is not None and (type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp < 0)
                or obj["synced"] and stamp is None):
            raise ValueError("Invalid cached line")
        lines.append(LyricLine(text, stamp, pronunciation))
    if sum(len(x.text) for x in lines) > 500000 or not lines and not obj["instrumental"]:
        raise ValueError("Invalid cache size")
    proofread = obj.get("proofread")
    if proofread is not None:
        if (not isinstance(proofread, dict)
                or any(not isinstance(proofread.get(k), str) or not proofread[k]
                       for k in ("asset_id", "revision", "language", "attribution"))
                or proofread["language"] not in ("hokkien", "cantonese")):
            raise ValueError("Invalid proofread metadata")
        proofread = Proofread(**{k: proofread[k] for k in ("asset_id", "revision", "language", "attribution")})
    reference = obj.get("recording_id")
    if reference is not None and (not isinstance(reference, str) or recording_ref(reference) is None):
        raise ValueError("Invalid cached recording reference")
    return Lyrics(tuple(lines), obj["source"], obj["synced"], obj["instrumental"], proofread, reference)


def fingerprint(lyrics):
    return hashlib.sha256(encode(lyrics).encode()).hexdigest()


def annotation_version(language):
    package = {"cantonese": "ToJyutping", "hokkien": "taibun"}.get(language)
    try:
        installed = version(package) if package else "original"
    except PackageNotFoundError:
        installed = "missing"
    return f"1:{package}:{installed}"


class LyricsCache:
    def __init__(self, path=None, *, max_entries=1000, max_bytes=100 * 1024 * 1024):
        self.path = Path(path) if path else SUPPORT / "lyrics-cache.sqlite3"
        self.max_entries, self.max_bytes = max_entries, max_bytes

    @staticmethod
    def key(track, reference=None):
        return hashlib.sha256(json.dumps([track.key, reference or "automatic"],
                                        ensure_ascii=False).encode()).hexdigest()

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=0.5)
        try:
            if db.execute("PRAGMA user_version").fetchone()[0] not in (0, 1):
                raise ValueError("Unsupported cache version")
            db.execute("PRAGMA auto_vacuum=INCREMENTAL")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS recordings
                  (key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
                   bytes INTEGER NOT NULL, accessed REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS annotations
                  (fingerprint TEXT, language TEXT, version TEXT, payload TEXT NOT NULL, bytes INTEGER NOT NULL,
                   PRIMARY KEY(fingerprint, language, version));
                PRAGMA user_version=1;
            """)
            return db
        except Exception:
            db.close()
            raise

    def _run(self, operation):
        db = None
        try:
            db = self._connect()
            with db:
                return operation(db)
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, OverflowError) as error:
            event("cache_error", error=type(error).__name__)
            return None
        finally:
            if db is not None:
                db.close()

    def get(self, key):
        def read(db):
            row = db.execute("SELECT payload FROM recordings WHERE key=?", (key,)).fetchone()
            if row is None:
                return None
            value = decode(row[0])
            db.execute("UPDATE recordings SET accessed=? WHERE key=?", (time.time(), key))
            return value
        result = self._run(read)
        event("cache_hit" if result else "cache_miss", key=key[:12])
        return result

    def put(self, key, lyrics):
        if lyrics is None or not lyrics.lines and not lyrics.instrumental:
            return
        def write(db):
            payload = encode(lyrics)
            decode(payload)
            size = len(payload.encode())
            if size > min(self.max_bytes, 6 * 1024 * 1024):
                return
            db.execute("INSERT OR REPLACE INTO recordings VALUES (?, ?, ?, ?, ?)",
                       (key, fingerprint(lyrics), payload, size, time.time()))
            self._prune(db)
            event("cache_store", key=key[:12], bytes=size)
        self._run(write)

    def annotated(self, raw, language):
        def read(db):
            row = db.execute("SELECT payload FROM annotations WHERE fingerprint=? AND language=? AND version=?",
                             (fingerprint(raw), language, annotation_version(language))).fetchone()
            return decode(row[0]) if row else None
        return self._run(read)

    def put_annotation(self, raw, language, annotated):
        def write(db):
            digest = fingerprint(raw)
            if not db.execute("SELECT 1 FROM recordings WHERE fingerprint=? LIMIT 1", (digest,)).fetchone():
                return
            payload = encode(annotated)
            decode(payload)
            size = len(payload.encode())
            if size > min(self.max_bytes, 6 * 1024 * 1024):
                return
            db.execute("INSERT OR REPLACE INTO annotations VALUES (?, ?, ?, ?, ?)",
                       (digest, language, annotation_version(language), payload, size))
            self._prune(db)
        self._run(write)

    def _prune(self, db):
        def cleanup():
            db.execute("DELETE FROM annotations WHERE fingerprint NOT IN (SELECT fingerprint FROM recordings)")
        cleanup()
        while True:
            count, size = db.execute("SELECT count(*), coalesce(sum(bytes),0) FROM recordings").fetchone()
            size += db.execute("SELECT coalesce(sum(bytes),0) FROM annotations").fetchone()[0]
            if count <= self.max_entries and size <= self.max_bytes:
                break
            db.execute("DELETE FROM recordings WHERE key=(SELECT key FROM recordings ORDER BY accessed LIMIT 1)")
            cleanup()
        db.execute("PRAGMA incremental_vacuum(128)")
