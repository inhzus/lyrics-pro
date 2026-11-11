"""Nonblocking lyric lookup/annotation lifecycle for the native companion."""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import json
import re
from queue import Queue, Empty
from threading import Event
import time

from .lyrics import LyricsProvider, NetEaseProvider, LrcAPIProvider, request_json, decode_record
from .models import LookupCancelled, LookupFailure
from .pronunciation import Romanizer, choose_language, supplied_annotation
from .curated import curated_lyrics, curated_candidates
from .recording_choices import RecordingChoices
from .recording_ref import recording_ref, source_ref
from .lyrics_cache import LyricsCache
from .diagnostics import event


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


def lookup_recording(reference, track, cancelled):
    provider, identifier = reference.split(":", 1)
    if provider == "proofread":
        result = curated_lyrics(track, reference, cancelled)
        if result is None:
            raise LookupFailure("This proofread source is unavailable or does not match this song.")
        return result
    if provider == "lrcapi":
        return LrcAPIProvider(cancelled=cancelled).lyrics_for(identifier, track)
    if provider != "netease":
        raise LookupFailure("Unsupported lyric source.")
    record = request_json("song/lyric", {"id": identifier, "lv": -1, "kv": -1, "tv": -1, "rv": -1}, cancelled)
    return decode_record(record, int(identifier)) if record else None


def discover_recordings(track, cancelled):
    candidates, errors = [], []
    for provider in (NetEaseProvider(lambda endpoint, params: request_json(endpoint, params, cancelled)),
                     LrcAPIProvider(cancelled=cancelled)):
        try:
            candidates.extend(provider.alternatives(track))
        except LookupCancelled:
            raise
        except LookupFailure as error:
            errors.append(error)
            event("discovery_error", provider=type(provider).__name__, error=str(error))
    if not candidates and errors:
        raise errors[-1]
    # Reserve space for both providers when NetEase returns its full quota.
    netease = [c for c in candidates if c.provider == "netease"]
    lrcapi = [c for c in candidates if c.provider == "lrcapi"]
    return tuple(netease[:max(15, 30 - len(lrcapi))] + lrcapi[:max(15, 30 - len(netease))])[:30]


class LyricSession:
    def __init__(self, cancelled, *, language="auto", fetch=lookup, romanizer=None, clock=time.monotonic,
                 choices=None, selected_fetch=lookup_recording, discover=discover_recordings, cache=None):
        self.cancelled = cancelled
        self.language = language
        self.request_id = 0
        self.fetch = fetch
        self.disk_cache = cache if cache is not None else (LyricsCache() if fetch is lookup else None)
        self.refresh_requested = False
        self.refresh_backup = None
        self.choices = choices if choices is not None else RecordingChoices()
        self.selected_fetch = selected_fetch
        self.candidates = ()
        self.discover = discover
        self.discovery_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="recordings")
        self.discovery_pending = None
        self.local_discovery = Queue()
        self.discovery_requested = False
        self.discovery_status = "idle"
        self.discovery_error = ""
        self.candidate_cache = OrderedDict()
        self.selection_intent = None
        self.selection_error = ""
        self.selection_revision = 0
        self.last_recordings = None
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
        if self.discovery_pending:
            self.discovery_pending[2].set()
        self.context, self.track = context, track if context else None
        self.refresh_requested, self.refresh_backup = False, None
        self.attempts, self.retry_at = 0, 0
        self.failure, self.last_update = None, None
        self.candidates = self.candidate_cache.get(track.key, ()) if track else ()
        self.discovery_status = "ready" if track and track.key in self.candidate_cache else "idle"
        self.discovery_requested = False
        self.discovery_error = self.selection_error = ""
        self.selection_intent = None
        self.last_recordings = None
        self.failure_kind = None
        self.finished = False

    def configure(self, language, request_id, *, retry=False, generation=None,
                  choice_id=None, forget=False, choice_request_id=None, discover=False):
        if language not in LANGUAGES or request_id <= self.request_id:
            return
        if choice_id is not None:
            choice_id = recording_ref(choice_id)
            if choice_id is None:
                return
        if choice_id is not None or forget or discover:
            if not self.context or generation != self.context[1]:
                return
            if choice_id is not None and (choice_request_id != self.request_id
                    or choice_id not in {c.reference for c in self.candidates}):
                return
            if discover:
                self.discovery_requested = True
            else:
                self._cancel()
                self.selection_intent = (request_id, None if forget else choice_id)
                event("recording_selection", recording=choice_id or "automatic", title=self.track.title)
                self.selection_error = ""
        language_changed = self.language != language
        self.language, self.request_id = language, request_id
        self.finished, self.last_update = False, None
        if self.failure_kind == "annotate":
            # A broken pronunciation engine must not prevent Original only or
            # the other engine from displaying already fetched lyrics.
            self.failure, self.failure_kind, self.retry_at = None, None, 0
        # A language change does not discard a useful raw lookup in progress.
        if language_changed and self.pending and self.pending[1] in {"annotate", "switch"}:
            self._cancel()
        if retry and self.context and generation == self.context[1]:
            self._cancel()
            key = self.context[0]
            self.refresh_requested = True
            self.refresh_backup = self.raw_cache.get(key) or self.refresh_backup
            self.raw_cache.pop(key, None)
            for cache_key in list(self.annotation_cache):
                if cache_key[0] == key:
                    del self.annotation_cache[cache_key]
            self.attempts, self.retry_at, self.failure = 0, 0, None
            self.failure_kind = None

    @staticmethod
    def _merge_candidates(local, online):
        unique = {}
        for candidate in (*local, *online):
            unique.setdefault(candidate.reference, candidate)
        return tuple(unique.values())[:30]

    def _discover_sources(self, track, context, token):
        local = curated_candidates(track, token)
        token.check()
        if local:
            self.local_discovery.put((context, token, local))
        online = self.discover(track, token)
        token.check()
        return self._merge_candidates(local, online)

    def _tick_discovery(self):
        # Publish bundled choices while the same worker continues online lookup.
        # Generation and cancellation checks also cover partial discovery results.
        while True:
            try:
                context, token, local = self.local_discovery.get_nowait()
            except Empty:
                break
            if context == self.context and not token.is_set():
                self.candidates = self._merge_candidates(local, self.candidates)
        if self.discovery_pending and self.discovery_pending[0].done():
            future, context, token = self.discovery_pending
            self.discovery_pending = None
            if context == self.context and not token.is_set():
                try:
                    self.candidates = future.result()
                    self._cache(self.candidate_cache, context[0], self.candidates, 16)
                    self.discovery_status, self.discovery_error = "ready", ""
                except LookupCancelled:
                    pass
                except Exception as error:
                    self.discovery_status, self.discovery_error = "error", str(error)
        if self.discovery_requested and self.context and self.discovery_pending is None:
            self.discovery_requested = False
            if self.discovery_status != "ready":
                token = Cancellation(self.cancelled)
                self.discovery_status, self.discovery_error = "loading", ""
                self.discovery_pending = (self.discovery_pool.submit(self._discover_sources, self.track, self.context, token),
                                          self.context, token)

    def _emit_recordings(self, emit):
        if emit is None or not self.context:
            return
        raw = self.raw_cache.get(self.context[0])
        source = raw.source if raw else ""
        payload = dict(request_id=self.request_id, status=self.discovery_status,
                       candidates=[asdict(c) | {"recording_id": c.reference} for c in self.candidates],
                       selected_id=(raw.recording_id if raw else None) or source_ref(source), source=source,
                       manual=self.choices.get(self.track) is not None,
                       switching=self.selection_intent is not None,
                       message=self.selection_error or self.discovery_error,
                       selection_revision=self.selection_revision)
        if payload != self.last_recordings:
            emit(payload)
            self.last_recordings = payload

    def _load(self, track, reference, token, refresh=False, backup=None):
        token.check()
        curated = curated_lyrics(track, reference, token)
        if curated is not None:
            return curated
        if reference is not None and reference.startswith("proofread:"):
            if refresh and backup and backup.recording_id == reference:
                event("refresh_failed_using_cache", title=track.title)
                return backup
            raise LookupFailure("This proofread source is unavailable or does not match this song.")
        key = LyricsCache.key(track, reference)
        cached = self.disk_cache.get(key) if self.disk_cache else None
        token.check()
        if cached is not None and not refresh:
            return cached
        try:
            raw = self.fetch(track, token) if reference is None else self.selected_fetch(reference, track, token)
            token.check()
        except LookupCancelled:
            raise
        except LookupFailure:
            if refresh and (cached or backup):
                event("refresh_failed_using_cache", title=track.title)
                return cached or backup
            raise
        if raw is None and refresh and (cached or backup):
            event("refresh_missing_using_cache", title=track.title)
            return cached or backup
        if raw and self.disk_cache:
            self.disk_cache.put(key, raw)
        return raw

    def _switch(self, track, song_id, language, token):
        raw = self._load(track, song_id, token, refresh=song_id is None)
        token.check()
        if raw is None or (not raw.lines and not raw.instrumental):
            raise LookupFailure("No lyrics are available for that recording. Choose another or retry.")
        if len(raw.lines) > 10000 or sum(len(x.text) for x in raw.lines) > 500000:
            raise LookupFailure("Lyrics are too large to display.")
        selected, _ = choose_language(track.artist, language, raw)
        annotated = self._annotate(raw, selected, token, refresh=song_id is None)
        if len(json.dumps(asdict(annotated), ensure_ascii=False).encode()) > 6 * 1024 * 1024:
            raise LookupFailure("Annotated lyrics are too large to display.")
        return raw, annotated

    @staticmethod
    def _cache(cache, key, value, limit):
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > limit:
            cache.popitem(last=False)

    def _annotate(self, raw, selected, token, refresh=False):
        token.check()
        supplied = supplied_annotation(raw, selected)
        if supplied is not None:
            token.check()
            return supplied
        if self.disk_cache and not refresh:
            cached = self.disk_cache.annotated(raw, selected)
            token.check()
            if cached:
                return cached
        lines = []
        for line in raw.lines:
            token.check()
            lines.append(replace(line, pronunciation=self.romanizer.line(line.text, selected)))
        token.check()
        result = replace(raw, lines=tuple(lines))
        if self.disk_cache:
            self.disk_cache.put_annotation(raw, selected, result)
        return result

    def tick(self, emit, emit_recordings=None):
        if self.cancelled.is_set():
            return
        self._tick_discovery()
        if self.pending and self.pending[0].done():
            future, kind, context, token, selected = self.pending
            self.pending = None
            if context == self.context and not token.is_set():
                try:
                    result = future.result()
                    if kind == "switch":
                        raw, annotated = result
                        intent, language = selected
                        language, _ = choose_language(self.track.artist, language, raw)
                        self.choices.set(self.track, intent[1])
                        for cache_key in list(self.annotation_cache):
                            if cache_key[0] == context[0]:
                                del self.annotation_cache[cache_key]
                        self._cache(self.raw_cache, context[0], raw, 16)
                        self._cache(self.annotation_cache, (context[0], language), annotated, 32)
                        self.selection_intent = None
                        self.selection_revision += 1
                        self.failure = self.failure_kind = None
                        self.finished = False
                        self.refresh_requested, self.refresh_backup = False, None
                    elif kind == "fetch":
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
                        self.refresh_requested, self.refresh_backup = False, None
                except LookupCancelled:
                    pass
                except LookupFailure as error:
                    if kind == "switch":
                        self._switch_failed(error)
                    else:
                        self.failure = error
                        self.failure_kind = kind
                        if kind == "fetch" and error.retryable and self.attempts < 3:
                            self.retry_at = self.clock() + 2 ** self.attempts
                        else:
                            self.retry_at = float("inf")
                except Exception as error:
                    if kind == "switch":
                        self._switch_failed(error)
                    else:
                        self.failure = LookupFailure(f"Could not prepare lyrics: {type(error).__name__}: {error}")
                        self.failure_kind = kind
                        self.retry_at = float("inf")
        if self.context is None:
            return
        key = self.context[0]
        selected, reason = choose_language(self.track.artist, self.language, self.raw_cache.get(key))

        if self.selection_intent is not None:
            if self.pending is None:
                token = Cancellation(self.cancelled)
                self.pending = (self.pool.submit(self._switch, self.track, self.selection_intent[1], self.language, token),
                                "switch", self.context, token, (self.selection_intent, self.language))
            self._emit_recordings(emit_recordings)
            return
        self._emit_recordings(emit_recordings)
        if self.finished:
            return

        def send(status, message, lyrics=None):
            payload = dict(request_id=self.request_id, language=self.language,
                           selected_language=selected, reason=reason, status=status,
                           message=message, lyrics=asdict(lyrics) if lyrics else None,
                           selection_revision=self.selection_revision)
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
                self.pending = (self.pool.submit(self._annotate, raw, selected, token, self.refresh_requested),
                                "annotate", self.context, token, selected)
        else:
            if self.failure and self.clock() < self.retry_at:
                send("loading", f"{self.failure} Retrying shortly ({self.attempts + 1}/3).")
            else:
                send("loading", "Looking up lyrics…")
                if self.pending is None and self.clock() >= self.retry_at:
                    token = Cancellation(self.cancelled)
                    self.attempts += 1
                    song_id = self.choices.get(self.track)
                    future = self.pool.submit(self._load, self.track, song_id, token,
                                              self.refresh_requested, self.refresh_backup)
                    self.pending = (future,
                                    "fetch", self.context, token, None)

    def close(self):
        self._cancel()
        if self.discovery_pending:
            self.discovery_pending[2].set()
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.discovery_pool.shutdown(wait=True, cancel_futures=True)

    def _switch_failed(self, error):
        self.selection_intent = None
        self.selection_error = str(error)
        self.finished = False
        if not self.raw_cache.get(self.context[0]):
            self.failure = LookupFailure(str(error))
            self.retry_at = float("inf")
