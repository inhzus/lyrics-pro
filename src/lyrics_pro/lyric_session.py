"""Nonblocking lyric lookup/annotation lifecycle for the native companion.

The bridge calls one intent method per native command, ``update_track`` for
each playback snapshot, and ``tick`` every poll. Lookup, annotation and
recording switches run one at a time on ``lookups``; results from a superseded
track, generation, or cancelled request are discarded when collected.
"""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from functools import partial
import json
import math
import time

from .curated import curated_lyrics
from .diagnostics import event
from .jobs import Cancellation, JobSlot
from .lyrics import discover_recordings, lookup, lookup_recording
from .lyrics_cache import LyricsCache
from .models import LookupCancelled, LookupFailure, Lyrics
from .pronunciation import Romanizer, resolve_language, supplied_annotation
from .recording_choices import RecordingChoices
from .recording_discovery import RecordingDiscovery
from .recording_ref import recording_ref, source_ref
from .song_languages import LANGUAGES, SongLanguages

__all__ = ["Cancellation", "LANGUAGES", "LyricSession"]


MAX_LINES = 10000
MAX_CHARACTERS = 500000
# Keep a response below the native protocol's 8 MiB frame limit.
MAX_PAYLOAD_BYTES = 6 * 1024 * 1024
MAX_LOOKUP_ATTEMPTS = 3
UNAVAILABLE_PROOFREAD = "This proofread source is unavailable or does not match this song."


def has_content(raw: Lyrics | None) -> bool:
    return raw is not None and bool(raw.lines or raw.instrumental)


def check_display_size(raw: Lyrics):
    if len(raw.lines) > MAX_LINES or sum(len(line.text) for line in raw.lines) > MAX_CHARACTERS:
        raise LookupFailure("Lyrics are too large to display.")


def check_payload_size(annotated: Lyrics):
    if len(json.dumps(asdict(annotated), ensure_ascii=False).encode()) > MAX_PAYLOAD_BYTES:
        raise LookupFailure("Annotated lyrics are too large to display.")


def display_status(lyrics: Lyrics) -> str:
    return "instrumental" if lyrics.instrumental else ("ready" if lyrics.synced else "plain")


@dataclass(frozen=True)
class Failure:
    error: LookupFailure
    kind: str  # The job that failed: fetch, annotate, or switch.
    retry_at: float = math.inf

    @property
    def final(self) -> bool:
        return self.retry_at == math.inf


@dataclass(frozen=True)
class Selection:
    """A pending recording switch; ``None`` restores automatic lookup."""
    reference: str | None


class LyricCaches:
    """Session LRUs: raw lyrics per track and annotations per track/language."""

    RAW_LIMIT = 16
    ANNOTATION_LIMIT = 32

    def __init__(self):
        self.raw = OrderedDict()
        self.annotations = OrderedDict()

    @staticmethod
    def _put(cache, key, value, limit):
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > limit:
            cache.popitem(last=False)

    def _drop_annotations(self, track_key):
        for key in [key for key in self.annotations if key[0] == track_key]:
            del self.annotations[key]

    def store_raw(self, track_key, raw):
        # The raw LRU can evict a track before the annotation LRU.
        # New lyrics must never reuse readings from an older result.
        self._drop_annotations(track_key)
        self._put(self.raw, track_key, raw, self.RAW_LIMIT)

    def store_annotation(self, track_key, language, annotated):
        self._put(self.annotations, (track_key, language), annotated, self.ANNOTATION_LIMIT)

    def forget(self, track_key):
        """Drop a track's lyrics and readings, returning the raw lyrics."""
        self._drop_annotations(track_key)
        return self.raw.pop(track_key, None)

    def has_raw(self, track_key) -> bool:
        return track_key in self.raw

    def touch_raw(self, track_key):
        self.raw.move_to_end(track_key)
        return self.raw[track_key]

    def annotation(self, track_key, language):
        key = (track_key, language)
        if key not in self.annotations:
            return None
        self.annotations.move_to_end(key)
        return self.annotations[key]


class LyricSession:
    def __init__(self, cancelled, *, language="cantonese", fetch=lookup, romanizer=None, clock=time.monotonic,
                 choices=None, selected_fetch=lookup_recording, discover=discover_recordings, cache=None,
                 song_languages=None):
        self.cancelled = cancelled
        self.language = language
        self.request_id = 0
        self.fetch = fetch
        self.selected_fetch = selected_fetch
        self.romanizer = romanizer or Romanizer()
        self.clock = clock
        self.disk_cache = cache if cache is not None else (LyricsCache() if fetch is lookup else None)
        self.choices = choices if choices is not None else RecordingChoices()
        self.song_languages = song_languages if song_languages is not None else SongLanguages(memory_only=fetch is not lookup)
        self.preferences_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="song-preferences")
        self.preference_saves = []  # (future, preference revision), oldest first.
        self.preference_revision = 0
        self.preference_warning = self.song_languages.warning
        self.data_jobs = []  # Storage stats/clears, oldest first, on the preferences worker.
        # After the first request, counts are re-sent whenever saved data changes.
        self.data_subscribed = False
        self.data_dirty = False
        self.selection_revision = 0
        self.lookups = JobSlot("lyrics", cancelled)
        self.recordings = RecordingDiscovery(cancelled, discover)
        self.caches = LyricCaches()
        self.context = None  # (track key, generation)
        self.track = None
        self._reset_track_state()

    def _reset_track_state(self):
        self.refresh_requested = False
        self.refresh_backup = None  # Lyrics to keep if an explicit refresh fails.
        self.attempts = 0
        self.failure: Failure | None = None
        self.selection: Selection | None = None
        self.selection_error = ""
        self.last_update = None
        self.last_recordings = None
        # True once the current lyric update is final; any intent clears it.
        self.finished = False

    def _invalidate_update(self):
        self.finished, self.last_update = False, None

    def update_track(self, track, generation):
        context = (track.key, generation) if track and track.key else None
        if context == self.context:
            return
        self.lookups.cancel()
        self.context, self.track = context, track if context else None
        self.recordings.reset(track)
        self._reset_track_state()

    # Native intents. Each carries the native lyric request revision; older
    # revisions are ignored so a late command cannot undo a newer one.

    def _accepts(self, language, request_id) -> bool:
        return language in LANGUAGES and request_id > self.request_id

    def _on_current_track(self, generation) -> bool:
        return self.context is not None and generation == self.context[1]

    def _commit(self, language, request_id, *, language_changed=None):
        if language_changed is None:
            language_changed = self.language != language
        self.language, self.request_id = language, request_id
        self._invalidate_update()
        if self.failure and self.failure.kind == "annotate":
            # A broken pronunciation engine must not prevent Original only or
            # the other engine from displaying already fetched lyrics.
            self.failure = None
        # A language change does not discard a useful raw lookup in progress.
        if language_changed and self.lookups.job and self.lookups.job.kind in {"annotate", "switch"}:
            self.lookups.cancel()

    def set_language(self, language, request_id):
        if self._accepts(language, request_id):
            self._commit(language, request_id)

    def set_song_language(self, language, request_id, song_language, *, generation, track_identity):
        if not self._accepts(language, request_id):
            return
        if (song_language not in LANGUAGES | {"default"} or not self._on_current_track(generation)
                or tuple(track_identity or ()) != self.context[0]
                or self.song_languages.key(self.track) is None):
            # A stale UI intent must not change the new song, but consuming
            # its revision lets the next snapshot synchronize that UI again.
            self.request_id = request_id
            self._invalidate_update()
            return
        values = self.song_languages.set(self.track, song_language)
        self.preference_revision += 1
        self.preference_warning = ""
        self.preference_saves.append(
            (self.preferences_pool.submit(self.song_languages.save, values), self.preference_revision))
        self._commit(language, request_id, language_changed=True)

    def retry(self, language, request_id, *, generation):
        if not self._accepts(language, request_id):
            return
        self._commit(language, request_id)
        if self._on_current_track(generation):
            self.lookups.cancel()
            self.refresh_requested = True
            self.refresh_backup = self.caches.forget(self.context[0]) or self.refresh_backup
            self.attempts, self.failure = 0, None

    def choose_recording(self, language, request_id, recording_id, *, generation, choice_request_id):
        if not self._accepts(language, request_id):
            return
        reference = recording_ref(recording_id)
        if (reference is None or not self._on_current_track(generation)
                or choice_request_id != self.request_id or not self.recordings.offers(reference)):
            return
        self._select(reference)
        self._commit(language, request_id)

    def forget_recording(self, language, request_id, *, generation):
        if self._accepts(language, request_id) and self._on_current_track(generation):
            self._select(None)
            self._commit(language, request_id)

    def list_recordings(self, language, request_id, *, generation):
        if self._accepts(language, request_id) and self._on_current_track(generation):
            self.recordings.requested = True
            self._commit(language, request_id)

    # User data. Clearing never removes visible lyrics; it affects later lookups.

    def request_data_stats(self):
        self.data_subscribed = True
        self.data_jobs.append((self.preferences_pool.submit(self._storage_stats, False), ""))

    def clear_data(self, targets):
        messages = []
        if "recording_choices" in targets:
            try:
                self.choices.clear()
            except OSError as error:
                event("data_clear_failed", target="recording_choices", category=type(error).__name__)
                messages.append("Couldn’t clear saved recording choices.")
            self.last_recordings = None  # Re-send the recording menu's "manual" flag.
        if "song_languages" in targets:
            self.song_languages.forget_all()
            self.preference_revision += 1
            self.preference_warning = ""
            # Same serial worker as saves, so an earlier save cannot resurrect cleared choices.
            self.preference_saves.append((self.preferences_pool.submit(self.song_languages.clear),
                                          self.preference_revision))
            self._invalidate_update()  # Re-resolve the current song's pronunciation.
        event("data_cleared", targets=",".join(targets))
        self.data_jobs.append((self.preferences_pool.submit(self._storage_stats, "lyrics_cache" in targets),
                               " ".join(messages)))

    def _storage_stats(self, clear_cache):
        message = ""
        if self.disk_cache and clear_cache and not self.disk_cache.clear():
            message = "Couldn’t clear the lyrics cache."
        stats = self.disk_cache.stats() if self.disk_cache else None
        if self.disk_cache and stats is None:
            message = message or "Couldn’t read the lyrics cache."
        return stats, message

    def tick_storage(self, emit_data):
        """Report finished storage work; runs even while Music cannot be read."""
        self._collect_preference_saves()
        if self.data_subscribed and self.data_dirty and not self.data_jobs:
            self.data_dirty = False
            self.data_jobs.append((self.preferences_pool.submit(self._storage_stats, False), ""))
        while self.data_jobs and self.data_jobs[0][0].done():
            future, earlier = self.data_jobs.pop(0)
            try:
                stats, message = future.result()
            except Exception as error:
                event("data_stats_failed", category=type(error).__name__)
                stats, message = None, "Couldn’t read saved data."
            emit_data(dict(lyrics_entries=stats[0] if stats else None, lyrics_bytes=stats[1] if stats else None,
                           recording_choices=self.choices.count, song_languages=self.song_languages.count,
                           message=" ".join(filter(None, (earlier, message)))))

    def _select(self, reference):
        self.lookups.cancel()
        self.selection = Selection(reference)
        self.selection_error = ""
        event("recording_selection", recording=reference or "automatic", title=self.track.title)

    # Background work. Each function receives its cancellation token after
    # its positional inputs.

    def _load(self, track, reference, token, refresh=False, backup=None):
        token.check()
        curated = curated_lyrics(track, reference, token)
        if curated is not None:
            return curated
        if reference is not None and reference.startswith("proofread:"):
            if refresh and backup and backup.recording_id == reference:
                event("refresh_failed_using_cache", title=track.title)
                return backup
            raise LookupFailure(UNAVAILABLE_PROOFREAD)
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
            self.data_dirty = True  # A plain flag; set from the lookup thread.
        return raw

    def _switch(self, track, reference, policy, token):
        automatic = reference is None
        raw = self._load(track, reference, token, refresh=automatic)
        token.check()
        if not has_content(raw):
            raise LookupFailure("No lyrics are available for that recording. Choose another or retry.")
        check_display_size(raw)
        selected, _ = resolve_language(*policy, raw)
        annotated = self._annotate(raw, selected, token, refresh=automatic)
        check_payload_size(annotated)
        return raw, annotated

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
            self.data_dirty = True
        return result

    # Polling.

    def tick(self, emit, emit_recordings=None):
        if self.cancelled.is_set():
            return
        self._collect_preference_saves()
        self.recordings.tick(self.context, self.track)
        if (job := self.lookups.take_done()) and job.current(self.context):
            self._collect(job)
        if self.context is None:
            return
        policy = (self.language, self.song_languages.get(self.track))
        if self.selection is not None:
            if not self.lookups.busy:
                reference = self.selection.reference
                self.lookups.start("switch", self.context, partial(self._switch, self.track, reference, policy),
                                   payload=(reference, policy))
            self._emit_recordings(emit_recordings)
            return
        self._emit_recordings(emit_recordings)
        if self.finished:
            return
        selected, reason = resolve_language(*policy, self.caches.raw.get(self.context[0]))
        status, message, lyrics = self._advance(selected)
        payload = dict(request_id=self.request_id, language=self.language,
                       song_language=policy[1], preference_warning=self.preference_warning,
                       selected_language=selected, reason=reason, status=status,
                       message=message, lyrics=asdict(lyrics) if lyrics else None,
                       selection_revision=self.selection_revision)
        if payload != self.last_update:
            emit(payload)
            self.last_update = payload

    def _collect_preference_saves(self):
        while self.preference_saves and self.preference_saves[0][0].done():
            future, revision = self.preference_saves.pop(0)
            try:
                future.result()
                self.data_dirty = True
            except Exception as error:
                event("song_language_save_failed", category=type(error).__name__)
                if revision == self.preference_revision:
                    self.preference_warning = "Couldn’t save song preferences. Changes apply until the app closes."
                    self.finished = False

    def _collect(self, job):
        key = self.context[0]
        try:
            result = job.future.result()
            if job.kind == "switch":
                raw, annotated = result
                reference, policy = job.payload
                language, _ = resolve_language(*policy, raw)
                self.choices.set(self.track, reference)
                self.data_dirty = True
                self.caches.store_raw(key, raw)
                self.caches.store_annotation(key, language, annotated)
                self.selection = None
                self.selection_revision += 1
                self.failure = None
                self.finished = False
                self.refresh_requested, self.refresh_backup = False, None
            elif job.kind == "fetch":
                if result:
                    check_display_size(result)
                self.caches.store_raw(key, result)
                self.failure = None
            else:
                check_payload_size(result)
                self.caches.store_annotation(key, job.payload, result)
                self.refresh_requested, self.refresh_backup = False, None
        except LookupCancelled:
            pass
        except Exception as error:
            if job.kind == "switch":
                self._switch_failed(error)
            elif not isinstance(error, LookupFailure):
                self.failure = Failure(LookupFailure(f"Could not prepare lyrics: {type(error).__name__}: {error}"),
                                       job.kind)
            elif job.kind == "fetch" and error.retryable and self.attempts < MAX_LOOKUP_ATTEMPTS:
                self.failure = Failure(error, job.kind, self.clock() + 2 ** self.attempts)
            else:
                self.failure = Failure(error, job.kind)

    def _switch_failed(self, error):
        self.selection = None
        self.selection_error = str(error)
        self.finished = False
        if not self.caches.raw.get(self.context[0]):
            self.failure = Failure(LookupFailure(str(error)), "switch")

    def _advance(self, selected):
        """Return the lyric status to publish, starting the next job if needed."""
        key = self.context[0]
        if self.failure and self.failure.final:
            self.finished = True
            return "error", str(self.failure.error), None
        if self.caches.has_raw(key):
            raw = self.caches.touch_raw(key)
            if not has_content(raw):
                self.finished = True
                return "unavailable", "No matching lyrics were found for this recording.", None
            if (annotated := self.caches.annotation(key, selected)) is not None:
                self.finished = True
                return display_status(annotated), "", annotated
            if not self.lookups.busy:
                self.lookups.start("annotate", self.context,
                                   partial(self._annotate, raw, selected, refresh=self.refresh_requested),
                                   payload=selected)
            return "loading", "Preparing pronunciation…" if selected else "Preparing lyrics…", None
        retry_at = self.failure.retry_at if self.failure else 0
        if self.failure and self.clock() < retry_at:
            return ("loading", f"{self.failure.error} Retrying shortly "
                    f"({self.attempts + 1}/{MAX_LOOKUP_ATTEMPTS}).", None)
        if not self.lookups.busy and self.clock() >= retry_at:
            self.attempts += 1
            self.lookups.start("fetch", self.context,
                               partial(self._load, self.track, self.choices.get(self.track),
                                       refresh=self.refresh_requested, backup=self.refresh_backup))
        return "loading", "Looking up lyrics…", None

    def _emit_recordings(self, emit):
        if emit is None or not self.context:
            return
        raw = self.caches.raw.get(self.context[0])
        source = raw.source if raw else ""
        payload = dict(request_id=self.request_id, status=self.recordings.status,
                       candidates=[dict(recording_id=c.reference, title=c.title, artists=list(c.artists),
                                        album=c.album, duration=c.duration) for c in self.recordings.candidates],
                       selected_id=(raw.recording_id if raw else None) or source_ref(source), source=source,
                       manual=self.choices.get(self.track) is not None,
                       switching=self.selection is not None,
                       message=self.selection_error or self.recordings.error,
                       selection_revision=self.selection_revision)
        if payload != self.last_recordings:
            emit(payload)
            self.last_recordings = payload

    def close(self):
        self.lookups.cancel()
        self.recordings.slot.cancel()
        self.lookups.shutdown()
        self.recordings.slot.shutdown()
        self.preferences_pool.shutdown(wait=True, cancel_futures=False)
