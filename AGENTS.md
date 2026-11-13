# Agent guidance for Lyrics Pro

This file contains development guidance. Keep [README.md](README.md) focused on
what the app does, installation, everyday use, and short getting-started commands.
[docs/macos-ui.md](docs/macos-ui.md) records historical implementation checkpoints;
its old stage boundaries and repository-dependent packaging notes are not current
requirements. Verify behavior against the source before changing it.

For user-supplied proofread lyrics and spelling, follow
[the timed alignment workflow](docs/proofread-lyrics-alignment.md) to reproduce
review candidates without changing the app or its cache. Bundling a reviewed
candidate is a separate, explicitly requested integration step.

## Workflow and project map

- Prefer **fish** for terminal commands and shell examples.
- The native SwiftUI app is in `macos/Sources/LyricsPro/`; its Swift Package has
  no external dependencies and targets macOS 15+. There is no Xcode project.
- `src/lyrics_pro/` contains the Python bridge, Music integration, lyrics providers,
  pronunciation engines, cache, and terminal client.
- `MusicConnection.swift` owns the subprocess connection; `BackendLaunch.swift`
  resolves the packaged worker and sanitizes its environment.
- [docs/protocol.md](docs/protocol.md) specifies the version 2 NDJSON boundary.
  `protocol.py` parses commands and frames events; `bridge.py` dispatches them.
  Natively, `MusicProtocol.swift` / `LyricProtocol.swift` decode events and
  `WorkerCommand.swift` encodes commands; change both sides and the spec together.
  Playback presentation and lyric following have separate state models.
- `lyrics/` holds the online providers: `transport.py` (bounded curl), `lrc.py`,
  `matching.py` (recording identity), `netease.py` / `lrcapi.py` / `lrclib.py`,
  and `chain.py` (provider order, explicit recording lookup and discovery).
  `lyric_session.py` coordinates asynchronous lookup, annotation, retries, and
  recording choices through explicit intent methods; `recording_discovery.py`
  owns alternative recordings and `jobs.py` the single-flight cancellable jobs.
- `packaging/` owns the frozen worker, dependency lock, signing checks, and ZIP
  portability verification. Fish entry points are in `scripts/`.
- Tests live in `tests/` and `macos/Tests/LyricsProTests/`. Keep generated files,
  environments, caches, logs, and release binaries out of Git.

## Setup, checks, and commands

Run from the repository root:

```fish
uv sync --locked
uv run pytest
fish scripts/test-macos.fish
fish scripts/build-macos.fish
packaging/.venv/bin/python packaging/verify_portable.py dist/Lyrics-Pro-0.5.0-macOS-arm64.zip
```

Use the actual release version in the ZIP filename. Run checks appropriate to the
change; documentation-only edits need link/command review and `git diff --check`,
not application rebuilds or new tests.

- The root project supports Python 3.11+ and uses `.python-version` / `uv.lock`.
  Packaging has its own pinned Python 3.12.16 environment and lock under
  `packaging/`; do not replace the developer's `.venv` to build a release.
- When changing runtime dependencies, update both locks. Refresh the packaging
  lock with `uv lock --project packaging --python 3.12.16`.
- Python tests mock Music and network access while exercising real dictionaries.
  Preserve coverage for cancellation, stale results, fallback matching, cache
  recovery, recording selection, and terminal escape sanitization.
- Native tests use Swift Testing. The test script disables XCTest and explicitly
  loads TestingMacros when available, working around Command Line Tools discovery
  issues. Existing SwiftUI State type aliases also accommodate this toolchain.
- Use deterministic tests for transport transitions, seeks, rapid track changes,
  denied permission, and failure recovery; distinguish these from live UI checks.

## Music connection and playback invariants

- Apple Music is the player. Read/control it through the existing bounded
  `/usr/bin/osascript` calls; do not interpolate untrusted metadata into scripts.
  The app does not launch Music. The terminal client only follows playback.
- Stdout from the bridge is protocol-only NDJSON; diagnostics go to stderr.
  Preserve version validation, bounded frames, partial reads, track generations,
  connection session IDs, and request revisions that discard stale results.
- Keep scripts, network access, artwork extraction, pronunciation, and storage
  work off the UI thread. Playback polling is every 0.5 seconds; native presentation
  uses a shared local clock between snapshots.
- Controls respond optimistically while Music confirms in the background.
  Coalesce queued seeks and play/pause intent; serialize skips. Never automatically
  retry a playback command. Failures restore confirmed state without removing lyrics.
- Seeking preserves playing/paused state. Lyric clicks resume automatic following;
  timeline seeking preserves manual browsing. Disable controls for demos and when
  Music has no playable track. Discard intents for a superseded track.
- EOF, shutdown, and termination must stop the worker and reap in-flight scripts.
  Preserve process-group cleanup and bounded cancellation/reconnect behavior.
- Artwork is fetched on track changes, capped at 4 MiB and eight cached tracks.
  Extraction files are temporary; invalid/missing artwork uses the placeholder.
  Prefer local Music artwork, then Apple iTunes catalog search (Taiwan, then US;
  these are lookup defaults, not the user's account region). Require normalized
  title/version, artist, album and duration within two seconds; reject ambiguous
  covers. Download only HTTPS Apple CDN images, with bounded cancellable curl.
  Prefer 1000x1000 renditions for recognized Apple thumbnail URL formats; fall
  back to the original catalog URL if unavailable. Preserve the 4 MiB limit.
  Cache images in memory only; missing results expire after 60 seconds on revisit.
  Retry transient failures at 2/8 seconds, never definitive misses or permission
  denial. Header Retry also retries missing/invalid artwork. Cancel superseded
  attempts and reject stale generations/revisions. Decode images off the UI thread.

## Lyrics, matching, and pronunciation

- Supplied collection preparation is an offline workflow documented in
  [docs/proofread-collection.md](docs/proofread-collection.md). Run
  `uv run --locked python -m scripts.prepare_proofread`; do not run alignment in
  the playback worker. Preserve raw transcriptions and accepted assets. Bundle
  only exact, complete, unambiguous results; keep approximate results for review.
- The explicitly reviewed Wu Bai integration lives in
  `resources/lyrics-spelling/wubai-reviewed/`. Reproduce/check with
  `uv run --locked python -m scripts.prepare_wubai --check`; `--integrate` writes
  its validated assets. Preserve frozen source hashes, explicit phrase boundaries,
  documented source-backed repairs and unresolved timing notes. Never rerun fuzzy
  matching to replace these decisions. The original automatic survey remains
  separate; `verify_proofread_collection` audits both catalogs.
- Proofread assets can designate `supplied` spelling for mixed/unknown languages.
  This is an effective default language, not an additional menu choice. Respect
  explicit language overrides. Validate NetEase, LrcAPI and LRCLIB timing provenance.

- Keep the provider order **NetEase → LrcAPI → LRCLIB**. A verified timed NetEase
  result or explicit instrumental result finishes lookup. A later timed fallback
  can improve an earlier plain result; otherwise retain usable plain lyrics.
- Requests use system `/usr/bin/curl`, bounded timeouts, and cancellation.
  Transient failures get at most three lookup rounds with backoff. Explicit retry
  starts a fresh attempt; cancellation must not start another provider.
- Match normalized title, artist credits, duration within two seconds, and album
  preference. Preserve distinctions between studio/live/remix versions. Search
  simplified/original metadata; inspect matching albums before settling for a
  compilation. LrcAPI unresolved artist names require an exact nonempty album match.
- Keep searches bounded: NetEase song queries examine up to 30 songs, album queries
  up to 20 albums, at most three matching album lookups, and three lyric candidates
  per phase. LRCLIB title searches examine at most 20 results. Deduplicate song IDs.
- If verified lookup fails, automatic selection may try up to three ranked NetEase
  candidates. Do not turn automatic choices into learned artist aliases.
- Recording discovery combines at most 30 NetEase/LrcAPI candidates. Keep references
  provider-qualified and accept legacy numeric NetEase IDs when reading saved data.
  Preserve generation/revision checks; only a successful switch saves a choice.
  Failed switches retain the previous lyrics and selection.
- Pronunciation is local: ToJyutping processes the full original line for context;
  Taibun uses southern Taiwanese Tâi-lô, tone numbers, and no sandhi. Preserve
  simplified/traditional handling, Latin text, punctuation, and unknown Han markers.
- Pronunciation precedence is song override, selected proofread resource, then
  global default (initially Cantonese). There is no Auto or artist-based guessing.
  Song overrides allow Cantonese/Hokkien/Original; Use Default clears the override.
  Global Original still permits inherited proofread spelling; song Original hides it.
  Keep global settings in the existing native preference store; migrate Auto or
  invalid values to Cantonese. The terminal uses only its explicit --language
  option (default Cantonese), without reading or writing GUI song preferences.
  Save song intent independently of lookup/annotation success, on a serial worker.
  Reject stale song mutations by track/generation/revision, but acknowledge their
  revision so native lyric updates cannot get stuck after a track switch.
  Do not fabricate lyrics, timestamps, or readings. Requests send metadata, not audio.
- `curated.py` resolves pre-aligned assets under `src/lyrics_pro/data/proofread/`
  before cache/network access. Match normalized title and duration within two
  seconds; artist/album are provenance, not gates. Each resource has a separate
  `proofread:<asset-id>` identity. Automatic prefers it; every explicit online
  selection (including its timing source) uses online lyrics. Publish local
  candidates before online discovery finishes, keeping them first and the combined
  list capped at 30. Use `Lyrics.recording_id` for identity when present; the timing
  link is attribution only. Collapse whitespace runs to one ordinary space in
  displayed text/spelling, keeping source transcripts intact. Keep supplied spelling
  for its language, hide it for Original, and use the requested engine for other
  language overrides.
  Bump the asset revision when changing content; preserve timing inputs and review
  notes under `resources/lyrics-spelling/`. Never run alignment during playback.
  Optional asset `title_aliases` are explicitly reviewed catalog spellings/version
  names; they retain the same duration gate. Never strip live/remix qualifiers
  globally. Check overlap across primary titles and aliases before bundling.

## Persistence and diagnostics

All user data lives under `~/Library/Application Support/Lyrics Pro/`:

- `lyrics-cache.sqlite3`: successful raw lyrics and annotations shared with the CLI.
  Bound it to 1,000 recordings and approximately 100 MiB of payload; evict least
  recently used entries. Key annotations by content, language, and engine version.
- `recording-choices.json`: at most 256 exact-track choices, written atomically.
  Store only successful manual selections; Automatic clears a saved override after
  successful automatic lookup.
- `preferences.sqlite3`: `song_languages` uses normalized title plus canonical artist
  identity, excluding album/duration/provider and preserving Live/Remix titles.
  Versioned SQLite with transactional writes, at most 1,000 persisted overrides and
  1 MiB of preference payload. Import legacy `song-languages.json` once in a transaction,
  retain the JSON as a backup, and never reimport after Use Default clears a choice.
  Keep preferences separate from the evictable lyrics cache. Capacity/save failures
  retain session intent and show a menu warning; do not evict saved choices. Re-resolve after every
  selected lyric-source change. Preserve visible lyrics and browsing while annotating.
- `Logs/app.log`: native events plus worker stderr. `Logs/cli.log`: terminal events.
  Each rotates at 2 MiB with four backups. Include useful metadata/timings, never
  full lyric bodies, artwork, or credentials.

Do not persist failures as missing lyrics. Retry bypasses memory/disk caches, but
a failed refresh retains usable lyrics. Storage corruption/unavailability is
nonfatal. Cache I/O stays on workers; native logging uses its serial queue.

## UI behavior and live verification

- Show the lyric source/timing label at the bottom left and retry in the top
  header. Let lyrics fill the body beneath it, keeping artwork placement and font
  sizes stable. Do not restore the old live metadata caption or music-note icon.
- Follow normal timed rows at 45% of the lyric viewport height; align rows taller
  than the viewport to the top. Keep sufficient first/last-row scroll padding.
- Keep timed highlighting tied to the shared playback clock. Manual browsing
  pauses scrolling, not highlighting; Resume following or a new song restores
  following. Blank timestamps clear the highlight during musical gaps.
- Preserve browsing across language changes and lyric refreshes. Keep current
  lyrics visible during refresh/recording switches. Untimed lyrics remain readable.
- Recording and pronunciation controls belong at the bottom right. The recording
  popover opens upward, is compact, and shows at most five rows before scrolling.
  Rows retain title, artists, album, duration, and source; use tooltips as needed.
- The current lyric is brightest; hovering a clickable line gives a softer
  highlight. The play/pause icon communicates playback state without extra text.
- Background colors come from artwork, crossfade, and animate only when appropriate
  for playback/window visibility. Honor Reduce Motion for background and scrolling.
- For interactive checks in this workspace, use the rightmost monitor when
  available. Preserve the user's playback state unless exercising controls, and
  restore it afterwards. Reopen the built app before claiming to have tested a new
  binary. Confirm the app version and bundled worker rather than an older process.
- Check cached and fresh lyrics, artwork, highlighting, popover behavior, reconnect,
  and clean shutdown when affected. Report unavailable separate-Mac, minimum-OS,
  or first-launch permission checks explicitly instead of claiming them passed.

## Packaging and releases

- Current downloadable builds target **arm64, macOS 15+**, with ad-hoc signing.
  Developer ID/notarization, Intel, older macOS, and automatic updates are deferred.
- Build through `scripts/build-macos.fish`. The app starts a PyInstaller directory
  bundle at `Contents/Helpers/LyricsBackend.app/Contents/MacOS/lyrics-pro-worker`.
  Resolve it relative to the outer app; never restore absolute checkout/venv paths.
- Include ToJyutping's trie, all Taibun dictionaries, msgpack's native extension,
  package version metadata, and project/dependency license notices.
- Preserve macOS helper-app code/resource separation for signing. Sign libraries,
  then helper, then outer app. Remove development-toolchain runtime search paths;
  verify architectures, minimum OS versions, linked libraries, and nested signatures.
- The build runs an offline self-check and produces an app plus ZIP with installation
  instructions and the MIT license. Staging/previous builds stay under `.build/`.
- Verify the actual ZIP with `packaging/verify_portable.py`: it extracts/renames the
  app into a path with spaces, denies repository/external Python/network/Apple Events
  access, and makes the bundle read-only. It checks pronunciation, metadata, SQLite,
  log rotation, startup, NDJSON readiness, shutdown, and restart.
- The isolation test does not replace first-launch/Gatekeeper validation on another
  Mac. Preserve the downloaded-app approval and Automation instructions.
- For releases, align the app version in `macos/Support/Info.plist`, source tag, ZIP
  name, and release notes. Publish the ZIP and SHA-256 checksum as release assets,
  not Git-tracked binaries. Documentation-only updates do not require a new release.
