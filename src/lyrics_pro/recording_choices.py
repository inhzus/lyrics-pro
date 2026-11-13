"""Explicit, per-recording choices. Never learn artist-wide aliases from a song."""

import json
import os
from pathlib import Path
import tempfile
from .recording_ref import recording_ref
from .diagnostics import SUPPORT


class RecordingChoices:
    def __init__(self, path=None):
        self.path = Path(path) if path else SUPPORT / "recording-choices.json"
        self.values = {}
        try:
            if self.path.stat().st_size <= 1_000_000:
                data = json.loads(self.path.read_text())
                if isinstance(data, dict):
                    self.values = {k: recording_ref(v) for k, v in list(data.items())[-256:]
                                   if isinstance(k, str) and recording_ref(v)}
        except (OSError, ValueError):
            pass

    @staticmethod
    def key(track):
        return json.dumps(track.key, ensure_ascii=False, separators=(",", ":"))

    def get(self, track):
        return self.values.get(self.key(track)) if track else None

    @property
    def count(self):
        return len(self.values)

    def set(self, track, song_id):
        values = dict(self.values)
        key = self.key(track)
        values.pop(key, None)
        if song_id is not None:
            reference = recording_ref(song_id)
            if reference is None:
                raise ValueError("Invalid recording ID")
            values[key] = reference
        self._write(dict(list(values.items())[-256:]))

    def clear(self):
        self._write({})

    def _write(self, values):
        """Replace the file atomically, then the in-memory choices."""
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
