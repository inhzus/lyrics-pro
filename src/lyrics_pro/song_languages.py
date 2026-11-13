"""GUI song preferences, independent of albums, timing sources and lyric caches."""
import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3

from .diagnostics import SUPPORT
from .pronunciation import normalize, artist_key

LANGUAGES = {"cantonese", "hokkien", "original"}
MAX_ENTRIES = 1000
MAX_BYTES = 1024 * 1024


class SongLanguages:
    def __init__(self, path=None, *, memory_only=False):
        self.path = None if memory_only else Path(path) if path else SUPPORT / "preferences.sqlite3"
        self.values = {}
        self.persistable = {}
        self.warning = ""
        self.loaded = memory_only
        if self.path is None:
            return
        try:
            with closing(self._connect()) as db, db:
                self._prepare(db)
                self._migrate(db)
                values = dict(db.execute("SELECT song_key, language FROM song_languages"))
                self._validate(values)
            self.values = values
            self.persistable = dict(values)
            self.loaded = True
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, AttributeError):
            self.warning = "Couldn’t read saved song preferences."

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.path, timeout=0.5)

    @staticmethod
    def _prepare(db):
        db.execute("BEGIN IMMEDIATE")
        if db.execute("PRAGMA user_version").fetchone()[0] not in (0, 1):
            raise ValueError("Unsupported preferences version")
        db.execute("""CREATE TABLE IF NOT EXISTS song_languages (
            song_key TEXT PRIMARY KEY NOT NULL CHECK (
                length(song_key) = 64 AND song_key NOT GLOB '*[^0-9a-f]*'),
            language TEXT NOT NULL CHECK (language IN ('cantonese', 'hokkien', 'original'))
        )""")
        db.execute("CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY NOT NULL)")
        db.execute("PRAGMA user_version=1")

    @staticmethod
    def _validate(values):
        if (not isinstance(values, dict) or len(values) > MAX_ENTRIES
                or any(not isinstance(k, str) or len(k) != 64 or any(c not in "0123456789abcdef" for c in k)
                       or not isinstance(v, str) or v not in LANGUAGES for k, v in values.items())
                or len(json.dumps(values).encode()) > MAX_BYTES):
            raise ValueError("Invalid or oversized song preferences")

    def _migrate(self, db):
        if db.execute("SELECT 1 FROM migrations WHERE name='song-languages-json'").fetchone():
            return
        legacy = self.path.with_name("song-languages.json")
        try:
            if legacy.stat().st_size > MAX_BYTES:
                raise ValueError("Oversized preferences")
            data = json.loads(legacy.read_text())
            if data["version"] != 1:
                raise ValueError("Invalid preferences version")
            values = data["overrides"]
            self._validate(values)
        except FileNotFoundError:
            values = {}
        except (OSError, ValueError, KeyError, TypeError):
            self.warning = "Couldn’t import saved song preferences."
            return
        # Existing SQLite choices win. Keep the JSON untouched as a backup.
        db.executemany("INSERT OR IGNORE INTO song_languages VALUES (?, ?)", values.items())
        self._mark_migrated(db)

    @staticmethod
    def _mark_migrated(db):
        db.execute("INSERT OR IGNORE INTO migrations VALUES ('song-languages-json')")

    @staticmethod
    def key(track):
        if not track or not normalize(track.title) or not normalize(track.artist):
            return None
        identity = [normalize(track.title), artist_key(track.artist)]
        return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()

    def get(self, track):
        return self.values.get(self.key(track), "default")

    def set(self, track, language):
        key = self.key(track)
        if key is None or language not in LANGUAGES | {"default"}:
            raise ValueError("Invalid song preference")
        if language == "default":
            self.values.pop(key, None)
            self.persistable.pop(key, None)
        else:
            self.values[key] = language
            if key not in self.persistable and len(self.persistable) >= MAX_ENTRIES:
                # Fail this save, keeping the session override. A later edit to
                # an existing saved song must still be persistable at capacity.
                return self.persistable | {key: language}
            self.persistable[key] = language
        return dict(self.persistable)

    @property
    def count(self):
        return len(self.values)

    def forget_all(self):
        """Clear the session's overrides at once; ``clear`` persists it."""
        self.values.clear()
        self.persistable.clear()

    def clear(self):
        """Delete every saved override. The legacy JSON stays a backup that is never reimported."""
        if self.path is None:
            return
        with closing(self._connect()) as db, db:
            self._prepare(db)
            db.execute("DELETE FROM song_languages")
            self._mark_migrated(db)
        self.loaded = True

    def save(self, values):
        """Write an immutable snapshot on the session's serial preferences worker."""
        if self.path is None:
            return
        if not self.loaded:
            raise ValueError("Saved preferences could not be loaded; refusing to overwrite them")
        self._validate(values)
        with closing(self._connect()) as db, db:
            self._prepare(db)
            db.execute("DELETE FROM song_languages")
            db.executemany("INSERT INTO song_languages VALUES (?, ?)", values.items())
            self._mark_migrated(db)
