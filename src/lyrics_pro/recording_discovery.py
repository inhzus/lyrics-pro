"""Alternative recordings offered for manual selection."""

from collections import OrderedDict
from functools import partial
from queue import Empty, Queue

from .curated import curated_candidates
from .lyrics import discover_recordings
from .lyrics.matching import MAX_CANDIDATES
from .jobs import JobSlot
from .models import LookupCancelled


CACHE_LIMIT = 16


def merge_candidates(local, online):
    unique = {}
    for candidate in (*local, *online):
        unique.setdefault(candidate.reference, candidate)
    return tuple(unique.values())[:MAX_CANDIDATES]


class RecordingDiscovery:
    """Proofread candidates publish first while online discovery continues."""

    def __init__(self, cancelled, discover=discover_recordings):
        self.discover = discover
        self.slot = JobSlot("recordings", cancelled)
        # Partial results from the worker thread: (context, token, candidates).
        self.local = Queue()
        self.cache = OrderedDict()
        self.candidates = ()
        self.status = "idle"
        self.error = ""
        self.requested = False

    def reset(self, track):
        self.slot.cancel()
        self.candidates = self.cache.get(track.key, ()) if track else ()
        self.status = "ready" if track and track.key in self.cache else "idle"
        self.requested = False
        self.error = ""

    def offers(self, reference) -> bool:
        return reference in {c.reference for c in self.candidates}

    def tick(self, context, track):
        # Generation and cancellation checks also cover partial discovery results.
        while True:
            try:
                local_context, token, local = self.local.get_nowait()
            except Empty:
                break
            if local_context == context and not token.is_set():
                self.candidates = merge_candidates(local, self.candidates)
        if (job := self.slot.take_done()) and job.current(context):
            try:
                self.candidates = job.future.result()
                self.cache[context[0]] = self.candidates
                self.cache.move_to_end(context[0])
                while len(self.cache) > CACHE_LIMIT:
                    self.cache.popitem(last=False)
                self.status, self.error = "ready", ""
            except LookupCancelled:
                pass
            except Exception as error:
                self.status, self.error = "error", str(error)
        if self.requested and context and not self.slot.busy:
            self.requested = False
            if self.status != "ready":
                self.status, self.error = "loading", ""
                self.slot.start("discover", context, partial(self._run, track, context))

    def _run(self, track, context, token):
        local = curated_candidates(track, token)
        token.check()
        if local:
            self.local.put((context, token, local))
        online = self.discover(track, token)
        token.check()
        return merge_candidates(local, online)
