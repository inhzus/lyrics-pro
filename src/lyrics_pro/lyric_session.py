"""Nonblocking lyric lookup/annotation lifecycle for the native companion."""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import json
from threading import Event
import time

from .lyrics import LyricsProvider
from .models import LookupCancelled, LookupFailure
from .pronunciation import Romanizer, choose_language


LANGUAGES = {"auto", "cantonese", "hokkien", "original"}


class Cancellation:
    def __init__(self, parent):
        self.parent = parent
        self.local = Event()

    def is_set(self):
        return self.parent.is_set() or self.local.is_set()

    def set(self):
        self.local.set()

    def check(self):
        if self.is_set():
            raise LookupCancelled("Lyrics request cancelled.")


def lookup(track, cancelled):
    return LyricsProvider(cancelled=cancelled).lookup(track)


class LyricSession:
    def __init__(self, cancelled, *, language="auto", fetch=lookup, romanizer=None, clock=time.monotonic):
        self.cancelled = cancelled
        self.language = language
        self.request_id = 0
        self.fetch = fetch
        self.romanizer = romanizer or Romanizer()
        self.clock = clock
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lyrics")
        self.pending = None
        self.context = None
        self.track = None
        self.raw_cache = OrderedDict()
        self.annotation_cache = OrderedDict()
        self.attempts = 0
        self.retry_at = 0
        self.failure = None
        self.failure_kind = None
        self.finished = False
        self.last_update = None

    def _cancel(self):
        if self.pending:
            self.pending[3].set()

    def update_track(self, track, generation):
        context = (track.key, generation) if track and track.key else None
        if context == self.context:
            return
        self._cancel()
        self.context, self.track = context, track if context else None
        self.attempts, self.retry_at = 0, 0
        self.failure, self.last_update = None, None
        self.failure_kind = None
        self.finished = False

    def configure(self, language, request_id, *, retry=False, generation=None):
        if language not in LANGUAGES or request_id <= self.request_id:
            return
        self.language, self.request_id = language, request_id
        self.finished, self.last_update = False, None
        if self.failure_kind == "annotate":
            # A broken pronunciation engine must not prevent Original only or
            # the other engine from displaying already fetched lyrics.
            self.failure, self.failure_kind, self.retry_at = None, None, 0
        # A language change does not discard a useful raw lookup in progress.
        if self.pending and self.pending[1] == "annotate":
            self._cancel()
        if retry and self.context and generation == self.context[1]:
            self._cancel()
            key = self.context[0]
            self.raw_cache.pop(key, None)
            for cache_key in list(self.annotation_cache):
                if cache_key[0] == key:
                    del self.annotation_cache[cache_key]
            self.attempts, self.retry_at, self.failure = 0, 0, None
            self.failure_kind = None

    @staticmethod
    def _cache(cache, key, value, limit):
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > limit:
            cache.popitem(last=False)

    def _annotate(self, raw, selected, token):
        token.check()
        if selected is None or raw.instrumental:
            return raw
        lines = []
        for line in raw.lines:
            token.check()
            lines.append(replace(line, pronunciation=self.romanizer.line(line.text, selected)))
        token.check()
        return replace(raw, lines=tuple(lines))

    def tick(self, emit):
        if self.cancelled.is_set():
            return
        if self.pending and self.pending[0].done():
            future, kind, context, token, selected = self.pending
            self.pending = None
            if context == self.context and not token.is_set():
                try:
                    result = future.result()
                    if kind == "fetch":
                        if result and (len(result.lines) > 10000 or sum(len(x.text) for x in result.lines) > 500000):
                            raise LookupFailure("Lyrics are too large to display.")
                        # The raw LRU can evict a track before the annotation LRU.
                        # A new fetch must never reuse readings from an older result.
                        for cache_key in list(self.annotation_cache):
                            if cache_key[0] == context[0]:
                                del self.annotation_cache[cache_key]
                        self._cache(self.raw_cache, context[0], result, 16)
                        self.failure = None
                        self.failure_kind = None
                    else:
                        # Keep a response below the native protocol's 8 MiB frame limit.
                        if len(json.dumps(asdict(result), ensure_ascii=False).encode()) > 6 * 1024 * 1024:
                            raise LookupFailure("Annotated lyrics are too large to display.")
                        self._cache(self.annotation_cache, (context[0], selected), result, 32)
                except LookupCancelled:
                    pass
                except LookupFailure as error:
                    self.failure = error
                    self.failure_kind = kind
                    if kind == "fetch" and error.retryable and self.attempts < 3:
                        self.retry_at = self.clock() + 2 ** self.attempts
                    else:
                        self.retry_at = float("inf")
                except Exception as error:
                    self.failure = LookupFailure(f"Could not prepare lyrics: {type(error).__name__}: {error}")
                    self.failure_kind = kind
                    self.retry_at = float("inf")
        if self.context is None or self.finished:
            return
        key = self.context[0]
        if self.language == "original":
            selected, reason = None, "original lyrics only"
        else:
            selected, reason = choose_language(self.track.artist, self.language)

        def send(status, message, lyrics=None):
            payload = dict(request_id=self.request_id, language=self.language,
                           selected_language=selected, reason=reason, status=status,
                           message=message, lyrics=asdict(lyrics) if lyrics else None)
            if payload != self.last_update:
                emit(payload)
                self.last_update = payload

        if self.failure and self.retry_at == float("inf"):
            send("error", str(self.failure))
            self.finished = True
            return
        if key in self.raw_cache:
            raw = self.raw_cache[key]
            self.raw_cache.move_to_end(key)
            if raw is None or (not raw.lines and not raw.instrumental):
                send("unavailable", "No matching lyrics were found for this recording.")
                self.finished = True
                return
            annotated_key = (key, selected)
            if annotated_key in self.annotation_cache:
                result = self.annotation_cache[annotated_key]
                self.annotation_cache.move_to_end(annotated_key)
                status = "instrumental" if result.instrumental else ("ready" if result.synced else "plain")
                send(status, "", result)
                self.finished = True
                return
            send("loading", "Preparing pronunciation…" if selected else "Preparing lyrics…")
            if self.pending is None:
                token = Cancellation(self.cancelled)
                self.pending = (self.pool.submit(self._annotate, raw, selected, token),
                                "annotate", self.context, token, selected)
        else:
            if self.failure and self.clock() < self.retry_at:
                send("loading", f"{self.failure} Retrying shortly ({self.attempts + 1}/3).")
            else:
                send("loading", "Looking up lyrics…")
                if self.pending is None and self.clock() >= self.retry_at:
                    token = Cancellation(self.cancelled)
                    self.attempts += 1
                    self.pending = (self.pool.submit(self.fetch, self.track, token),
                                    "fetch", self.context, token, None)

    def close(self):
        self._cancel()
        self.pool.shutdown(wait=True, cancel_futures=True)
