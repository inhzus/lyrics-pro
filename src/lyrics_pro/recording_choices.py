"""Explicit, per-recording choices. Never learn artist-wide aliases from a song."""

import json
import os
from pathlib import Path
import tempfile


class RecordingChoices:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path.home() / "Library/Application Support/Lyrics Pro/recording-choices.json"
        self.values = {}
        try:
            if self.path.stat().st_size <= 1_000_000:
                data = json.loads(self.path.read_text())
                if isinstance(data, dict):
                    self.values = {k: v for k, v in list(data.items())[-256:]
                                   if isinstance(k, str) and type(v) is int and v > 0}
        except (OSError, ValueError):
            pass

    @staticmethod
    def key(track):
        return json.dumps(track.key, ensure_ascii=False, separators=(",", ":"))

    def get(self, track):
        return self.values.get(self.key(track)) if track else None

    def set(self, track, song_id):
        values = dict(self.values)
        key = self.key(track)
        values.pop(key, None)
        if song_id is not None:
            if type(song_id) is not int or song_id <= 0:
                raise ValueError("Invalid recording ID")
            values[key] = song_id
        values = dict(list(values.items())[-256:])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             delete=False) as stream:
                temporary = stream.name
                json.dump(values, stream, ensure_ascii=False)
            os.replace(temporary, self.path)
            self.values = values
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
