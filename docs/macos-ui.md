# Native macOS UI checkpoints

## Agreed behavior

A personal Finder-launchable SwiftUI companion, inspired by the supplied Apple
Music screenshot: artwork and song metadata on the left, lyrics with a separate
pronunciation line on the right, and a dark blurred artwork background. Window
defaults to 1280 × 800, with a minimum content size of 900 × 600 and native fullscreen.

Apple Music remains the player. Lyrics Pro follows timed lyrics, allows manual
browsing, and offers Resume following. The playback-control increment adds
play/pause, previous/next, timeline seeking, and click-to-seek lyrics. Word-level
karaoke timing, AI services, and extra lyrics providers remain outside this scope.

Implement and verify **one stage at a time, then pause for user feedback**.

## Stage 1 — Visual shell

Implemented in `macos/`, built by `scripts/build-macos.fish` into
`dist/Lyrics Pro.app`. Native SwiftUI, Swift Package Manager, macOS 15+; no external
Swift packages or Xcode project. The script resolves paths relative to itself and
ad-hoc signs the app bundle.

- Original vector cover and sample lyrics, explicitly labeled as demo content.
- Static highlighted line and progress indicator; no Music access or networking.
- Selectable Cantonese, Hokkien, long/mixed text, and missing-artwork scenarios.
- Scrollable, selectable lyric text with separate pronunciation and wrapped lines.
- Repeat builds update the local app; quit the preview before rebuilding it.

Verified on this Mac (macOS 27.0.1, Apple Silicon, Swift 6.4 Command Line Tools):

- Release build and repeat build succeed; bundle signature and Info.plist validate.
- App launches through macOS application services without a terminal window.
- Default size, compact size, and native fullscreen visually inspected.
- All four demo scenarios inspected; Chinese, English, and pronunciation wrap
  without horizontal clipping. Manual scrolling and text selection work.
- The Preview menu provides compact/default size presets; exit fullscreen first.
- Rechecked sample switching, long-text scrolling, and both size presets on the
  MacBook Pro's built-in Retina display. Presets resize in place and retain the
  current display; the app is left there for review. Use this display for subsequent
  interactive checks, as requested.
- Existing Python suite: **119 passed**.

The SDK's new `State` macro lacks a plugin in this Command Line Tools installation.
A type alias explicitly uses the established `State` property wrapper instead.
The linker emits two missing Command Line Tools search-directory warnings; linking,
signing, and launching succeed. macOS 15 is the deployment target, but testing was
performed on this Mac rather than on macOS 15 itself.

**Stage 1 complete and approved.**

## Stage 2 — Live Music connection

Launch the repository's `.venv/bin/python` as a worker from the app. Exchange
newline-delimited JSON over stdin/stdout, keeping diagnostics on stderr. Reuse
half-second playback polling. Read artwork on track changes with a timeout and
session cache; fall back to a placeholder. Tag asynchronous work with track identity
and generation. Keep work off the UI thread. Add the Automation usage description
and verify permission attribution from Finder. Handle missing environment, closed
Music, permission denial, and worker failure. Quit without orphaned subprocesses.

Implemented and verified on 2026-11-10:

- Live mode is the default; the original demos remain selectable separately.
- Bundled `Backend.json` records absolute project/Python paths. No shell or local
  server is launched. Missing paths show setup instructions; Reconnect restarts the
  connection. The existing terminal entrypoint is unchanged.
- Worker polls every 0.5 seconds and extracts current-track artwork on one separate
  thread. Images are limited to 4 MiB and cached for eight tracks for the session.
  Temporary extraction files are removed after reads. Missing/error artwork uses a
  placeholder; reconnect retries it. No new network service is used.
- Protocol v1: each event has `version`, `type`, `generation`, and `track` (null or
  `[title, artist, album, roundedDuration]`). `playback` events carry the existing
  playback fields; `artwork` carries a base64 `image` or null; `status` carries
  `code` and `message`; `ready` confirms startup. Commands accept `retry` and
  `shutdown`. EOF/SIGTERM also shuts down. Stdout is JSON only; stderr is diagnostics.
- Track generations reject stale A→B→A artwork. Native connection session IDs reject
  output from replaced workers. Pipe reads deliver partial chunks immediately rather
  than waiting to fill a buffer. Artwork does not block metadata polling.
- GUI quit/window close waits for bounded worker shutdown off the main thread.
  Worker scripts are cancelled and reaped; group cleanup covers unexpected crashes.
- **137 Python tests and 7 Swift Testing tests passed.** Run Swift tests with
  `swift test --package-path macos --configuration release --disable-xctest` because
  this Command Line Tools installation has Swift Testing but not XCTest.
- Live check: `No Fear in My Heart` / `朴树` / `猎户星座`, paused at 67.95 seconds of
  386.81 seconds. UI displayed matching metadata, `1:07 / 6:26`, and actual artwork.
  Pause stayed stable. Seek, resume, stopped/closed, denied-permission recovery, and
  rapid track switches were exercised with deterministic tests, without changing the
  user's Music playback during validation.
- System Settings → Privacy & Security → Automation showed **Lyrics Pro → Music on**,
  confirming app attribution. No privacy settings were modified by the agent.
- Actual GUI quit left no worker; an injected worker crash cleared stale UI and
  showed Reconnect. Reconnect restored one worker and the actual cover. The crashed
  process group was gone. Interactive review uses the MacBook Pro built-in display.

**Stage 2 complete and approved.**

## Stage 3 — Lyrics and pronunciation

Connect the existing NetEase → LRCLIB pipeline, ToJyutping, and Taibun. Preserve
matching, retries, and stale-result protection. Worker commands: language, retry,
shutdown. Events: playback, artwork, lyrics, status. Add a remembered Auto /
Cantonese / Hokkien / Original only picker (Auto default). Cache raw lyrics by
track and annotations by track plus language. Show source, loading, unavailable,
instrumental, unsynchronized, and error states. Add retry without restarting.

Pause after live songs and mocked failure cases pass, including the existing CLI suite.

Implemented and verified on 2026-11-10:

- Live lyrics and pronunciation are displayed in a manually scrollable list. The
  native picker persists Auto, Cantonese, Hokkien, or Original only in UserDefaults.
  Auto clearly identifies artist-based guesses; unknown artists retain original
  lyrics. The provider's original text, timestamps, and source are preserved.
- Local ToJyutping and Taibun run on one lyric worker thread, separate from artwork
  extraction and Music polling. No new provider or AI service was added. The existing
  terminal CLI, alias matching, duration checks, and fallback order are unchanged.
- A bounded session cache holds 16 raw tracks and 32 annotated track/language pairs.
  Language changes reuse raw lookups already in progress. Track changes cancel old
  requests; generation plus native request revision rejects stale results, including
  A→B→A and rapid language reversals. A failed pronunciation engine still permits
  switching to Original only without another network lookup.
- Loading, ready, untimed, instrumental, no match, and failed lookup states are
  distinct. Retry lyrics invalidates the current track's caches without restarting
  Music polling. Transient failures retry up to three rounds with 2/4-second delays.
  Network work cancels on track changes and app shutdown. Responses are size-limited.
- Protocol v1 adds `lyrics` events carrying a `lyric` object: `request_id`, requested
  `language`, nullable `selected_language`, `reason`, `status`, `message`, and nullable
  `lyrics` (lines, source, synced, instrumental). Commands `language` and `retry_lyrics`
  carry language and increasing request ID; retry also carries the viewed generation.
  The preferred language is passed to the worker on launch. Native pipe writes run
  off the main thread and safely handle a worker exiting during a command.
- **153 Python tests and 12 Swift Testing tests passed**, including CLI regressions,
  real local pronunciation, async lifecycle, cache bounds, preference persistence,
  and mocked unavailable/instrumental/plain/error behavior. Release build, signature,
  and plist checks passed.
- Real provider probes: Eason Chan's **浮誇** returned 51 timed rows from NetEase
  (47 nonempty pronunciation rows); Wu Bai & China Blue's **空襲警報** returned 35
  timed rows with Hokkien pronunciation through the new lyric session. These were
  read-only provider checks, without selecting different songs in Music.
- GUI check on the built-in Retina display: the current **Banana Co / Radiohead**
  recording loaded timed NetEase lyrics and actual artwork, remaining paused at
  `0:20 / 2:21`. Cantonese and Hokkien overrides produced readings for Chinese credit
  text; Original only removed them. Default/compact wrapping and manual scrolling
  were checked. Hokkien selection survived quit/relaunch. Retry restored the same
  lyric source without disrupting metadata; GUI quit left no lyric worker.
- During review, Music changed to **断肠诗 / 伍佰 & China Blue / 树枝孤鸟**. The app
  picked up the new track, cover, advancing playback time, and timed NetEase lyrics
  automatically. Auto selected Hokkien and displayed local Tâi-lô beneath the text.
  Taibun's unresolved characters remain visible as `[字: ?]`. Auto was restored for
  review, and the Window menu confirmed the app was on the built-in Retina display.
- Automatic highlighting/scrolling remains Stage 4. No playback commands or
  click-to-seek controls were added. Local dictionary readings remain guidance;
  the app does not claim to reproduce a singer's exact pronunciation.

**Stage 3 complete. Stage 4 also incorporates the requested header refinements.**

## Stage 4 — Following and manual browsing

Highlight the latest timestamp at or before playback position. Smoothly center a
new active line, not every poll. User scrolling pauses centering while highlighting
continues; Resume following or changing songs restores it. Follow seeks in Music,
freeze on pause, and render untimed lyrics as a normal list. Highlight whole lines.

Pause after seeks, repeated timestamps, gaps, track switches, and manual browsing
are verified without unwanted scroll jumps.

Implemented on 2026-11-10:

- Playing/Paused is non-interactive text centered beneath the progress bar between
  the timestamps, with no duplicate in the header. The timeline's accessibility
  description includes this state. Connection-error labels remain in the header.
  The pronunciation control is a translucent
  capsule with an icon, short mode name, chevron, hover/focus feedback, and checked
  language choices. Reconnect moved to the Lyrics Pro application menu; demos moved
  to Preview → Display. Existing language preferences are retained.
- A pure Swift timeline uses the latest timestamp at or before Music's position,
  with binary search and deterministic handling of duplicate timestamps. Blank
  timed rows clear highlighting; no timing is fabricated for untimed lyrics.
  Original text and pronunciation retain their content and layout when highlighted.
- A separate following state preserves manual browsing through language changes,
  retry, and resizing. Native scroll phases distinguish user input from automatic
  animation. Resume following recenters the current row; new tracks and reconnects
  reset to following. Repeated half-second snapshots do not retrigger scrolling.
- Active rows use bright white text and teal pronunciation; surrounding rows remain
  readable. Scrolling takes 0.3 seconds, with immediate initial positioning and no
  animation under Reduce Motion. First/last rows have centering space; tall measured
  rows align to their top. Text remains selectable and does not seek playback.
- **153 Python tests and 20 Swift tests passed.** The eight new following tests cover
  boundaries, gaps, repeated/unsorted timestamps, untimed data, late arrival, pauses,
  forward/backward seeks, manual/resume transitions, reloads, and track generations.
- Swift Testing's automatic plugin discovery failed in this Command Line Tools
  installation. `fish scripts/test-macos.fish` resolves the active toolchain and
  explicitly loads its TestingMacros plugin when available. Tests then pass;
  the pre-existing missing linker search-directory warnings remain harmless.
- Live review on the MacBook Pro built-in Retina display verified initial positioning
  during **蝴蝶 / David Tao**, automatic transition to **光之翼 / 王菲**, advancing
  selected rows and scrolling, manual browsing without snap-back, and Resume
  following. **再見二丁目 / Miriam Yeung** verified continuing following with LRCLIB
  lyrics, a later paused state at `2:59`, language changes, retry, and compact layout.
  No Music playback commands were issued during these checks.
- Manual browsing survived Original → Cantonese conversion and a real lyric retry;
  the retry restored the same scroll position. The corrected language menu remained
  open while playback advanced and displayed its selection checkmark. Native status
  labels were inspected in both Playing and Paused states.
- Final release build, bundle signature, and plist checks passed. The relocated
  Reconnect command restored the current paused song with one worker; Preview lists
  Live Music and all four demos. During the last default-size adjustment, computer
  inspection began returning `cgWindowNotFound`, including after rebinding/resetting
  the inspection session. The app and its worker remained running. Earlier built-in
  display checks passed, but the final window placement could not be reverified.

**Stage 4 complete; pause for feedback before Stage 5 polish and distribution.**

## Playback-control increment — 0.4.1

The user expanded the scope after Stage 4 to control Apple Music from this app.

- Previous, play/pause, and next sit beneath the timeline; the muted state label
  remains between timestamps. The timeline supports click/drag and native keyboard
  and accessibility adjustment. Dragging previews locally and commits on release.
- Timed, nonblank lyric rows seek and resume following after acknowledgement.
  Untimed text stays selectable; timed rows offer Copy lyric. Timeline seeks retain
  browsing mode, and seeks preserve Music's playing/paused state.
- Protocol v1 adds `playback_control` commands (`command_id`, `action`, `generation`,
  `track`, optional `position`) and `control_result` events (`command_id`, `ok`,
  optional `code`/`message`). Lyrics request revisions remain independent.
  The worker serializes commands and refreshes playback before acknowledging them.
  It checks generation and track identity; the fixed JXA script checks the live
  identity again immediately before acting. Duplicate IDs and stale requests cannot
  repeat an action. Commands are never automatically retried.
- Controls disable while pending or disconnected and cannot operate in demos.
  Four-second script timeouts and a ten-second UI acknowledgement timeout release
  pending state. Control errors appear below the buttons without clearing lyrics.
- Live testing found Music rounds seek positions to single precision. Lyric seeks
  land 20 ms inside the line, avoiding a paused highlight on the previous row.
  Music also restarts on Previous when past the beginning, so the script sets the
  position to zero before issuing Previous to select the previous song in one click.
- **173 Python and 26 Swift tests passed.** Release build, signature verification,
  and plist validation passed. Live checks on the built-in display confirmed
  play/pause, timeline dragging, lyric seeking while paused, corrected lyric
  highlighting, Next, and one-click Previous from mid-track. Default and compact
  layouts were inspected. No pronunciation preference was changed.
- UI inspection temporarily failed with `cgWindowNotFound` after relaunch, then
  recovered. Physical scroll/drag checks on the final display layout encountered
  `windowNotFoundAtPosition`; final manual-browse-to-seek interaction was therefore
  not reverified end-to-end. Following state and command acknowledgement behavior
  are covered by Swift tests; the existing Stage 4 manual-scroll behavior is retained.

## Responsive controls — 0.4.2

- Playback commands run on a separate serial executor; the bridge continues polling
  and processing lyrics while Apple Music handles an action. Playback events include
  `completed_control_id`, captured before sampling, so an older read cannot confirm
  or undo a newer request. Results remain serialized on the bridge's main loop.
- A pure presentation/intent state machine separates confirmed Music snapshots from
  immediate play/pause and seek feedback. One monotonic clock drives timeline time
  and lyric highlighting at 10 Hz while playing; paused time stays fixed.
- One command is in flight. Unsent seeks and play/pause intents each retain only the
  latest choice, ordered by the user's latest action. Next/Previous accept one skip
  until the track changes, fails, or times out. Other controls and lyric browsing
  remain available, and a pending command no longer dims the player.
- Lyric clicks immediately seek visually and resume following; slider seeking keeps
  browsing mode. Track changes and demo switches discard old-track previews and
  queued actions. Disconnect clears all intent state. Failures restore confirmed
  values without overriding newer intents, and a ten-second deadline bounds pending
  confirmation. Commands are never automatically retried.
- After one second, a small Updating Music indicator provides feedback. Script and
  shutdown cancellation remain bounded. No lyric timing offset or provider changes
  are included in this increment.
- **175 Python tests and 31 Swift tests passed**, including blocked command polling,
  cancellation, pre-completion sample revisions, rapid play/pause, repeated seeks,
  stale confirmations, timeout/failure recovery, track transitions, and skip guards.
- Release build, signature verification, and plist validation passed. Live review
  on the MacBook Pro built-in display during **止战之殇 / 周杰伦** confirmed immediate
  Pause/Play feedback with enabled controls, paused lyric seeking without dimming,
  manual browsing followed by a lyric click restoring following, timeline seeking
  retaining browsing mode, and drag-to-seek. Compact and default layouts were both
  inspected; playback was resumed and the app left at default size on that display.
  Raising the app window before physical scrolling allowed the previously blocked
  manual-browsing interaction to be verified end-to-end.

## Footer and lyric hover polish

- Removed the separate Playing/Paused timeline label and the live bottom-right
  browsing hint. The pronunciation capsule now occupies the bottom-right footer,
  with its existing menu and saved language. Demo labeling is unchanged.
- Seekable lyric rows gain a 6% white rounded background and brighter inactive
  text on hover. The active lyric remains brightest. Fixed row padding and reduced
  inter-row spacing keep hover from changing layout; Reduce Motion disables the
  120 ms transition. Disabled, untimed, and blank rows do not advertise seeking.
- All 31 Swift tests passed; release build and signature verification passed.
  Compact and default layouts and the relocated menu were inspected live. The app
  was placed on the rightmost DELL P2725QE. Full hover/seek interaction review was
  blocked when the current song's lyric loading failed with a UTF-8 decoding error
  and subsequent network timeouts; no lyric-provider behavior was changed.

## Recording confirmation — 0.4.3

- Removed the duplicated pronunciation heading above the lyric source.
- Unverified artist matches now yield up to five recording suggestions after the
  normal verified NetEase/LRCLIB lookup. Search uses title and artist, followed by
  a bounded title-only query. Suggestions require a normalized title match and
  duration within two seconds; exact album matches and artist-query relevance
  rank ahead of title-only coincidences. These are never automatic artist aliases.
- The native chooser displays Apple Music metadata alongside each candidate's
  artist, album, source, and duration. Confirmation is guarded by track generation,
  lyric request revision, and membership in the offered candidate list.
- Choices persist for the exact track in a bounded local JSON store (256 entries,
  atomic replacement). A Forget recording choice button removes the mapping and
  repeats normal lookup. A saved choice bypasses future matching for that track.
- Curl output stays as bytes until exit/HTTP checks pass. Invalid UTF-8/JSON now
  becomes a retryable lookup failure, allowing normal fallback handling.
- 184 Python and 32 Swift tests passed. A live NetEase lookup for 故鄉 / Lo Ta-You
  returned 罗大佑's recording (5284269) as a suggestion without a hardcoded alias;
  other singers with similar durations remained suggestions requiring confirmation.

## Automatic recording picker — 0.4.4

- Verified NetEase and LRCLIB matches retain priority. When neither succeeds,
  lookup tries up to three ranked NetEase candidates with the same normalized
  title and duration within two seconds. Artist, album, and search relevance
  inform ranking without creating artist aliases.
- A Recording capsule beside pronunciation opens a compact 300-point picker.
  It retains title, artist, album, duration, source, and selection state, with
  full metadata in tooltips. At most five 64-point rows appear at once; remaining
  recordings scroll. A current source absent from the alternatives stays visible
  as a separate row. Discovery is bounded to 30 candidates and cached per track.
- The native popover anchors above the capsule, re-anchors when asynchronous
  content changes or the window moves/resizes, and limits list height to the
  space above the button. It no longer grows down beyond the display edge.
- Discovery and recording changes run in the background while current lyrics
  remain usable. Only successful manual loads persist an exact-track choice;
  Automatic restores matching and clears that choice after success. Track and
  request guards reject stale results, and rapid changes honor the latest choice.
- 189 Python and 33 Swift tests passed. Release build, signature verification,
  and plist validation passed. Live lookup automatically resolved 故鄉 / Lo Ta-You
  to NetEase recording 5284269 with 32 timed lines. On 我不难过 / 孙燕姿, seven
  alternatives were available; scrolling, selecting another album, and restoring
  Automatic were verified. The compact picker was inspected above its button
  with nine alternatives for 曖昧 / Faye Wong on the rightmost DELL P2725QE.
  Keyboard focus initially reaches Automatic; arrow navigation could not be
  verified because automated key input dismissed the transient popover.

## Artwork-colored motion — 0.4.5

- Replaced the enlarged blurred cover with a dedicated full-window background.
  ImageIO downsamples artwork to 32 pixels before four alpha-weighted regional
  averages are calculated off the main thread. Saturation and brightness are
  bounded, including very dark saturated artwork and transparent images.
- Four overlapping radial gradients drift on 30–51-second cycles beneath a dark
  overlay, stronger toward the lyrics. Colors crossfade over 1.2 seconds. Teal
  accents and the album-cover presentation remain unchanged.
- A separate 30 Hz timeline animates only while playing and the window is visible.
  Its monotonic clock freezes on pause, minimization, hiding, or full occlusion,
  then resumes from the same position. Reduce Motion uses a static composition
  and immediate palette changes. No artwork sampling happens on animation ticks.
- The previous palette remains while the next artwork loads. Missing/invalid
  artwork and disconnect use a neutral palette. Track/artwork task identity and
  cancellation prevent superseded palette requests from updating the view.
- All 38 Swift tests passed, including image decoding/fallbacks, brightness bounds,
  regional hue preservation, cancelled requests, and freeze/resume timing. Live
  review covered the paused 曖昧 cover, compact/default layouts, animated demo
  colors, and the missing-artwork fallback. Reduce Motion and occlusion are wired
  to system signals; their full system-level behavior was not manually exercised.

## Sources, persistence, and identity — 0.4.6

- Automatic lookup now uses NetEase, LrcAPI, then LRCLIB. Later timed results may
  improve earlier plain lyrics. LrcAPI searches its public JSON endpoint and checks
  normalized title and duration within two seconds; unresolved artist names also
  require matching album metadata. No artist-wide aliases are learned.
- The compact upward Recording picker includes NetEase and LrcAPI alternatives,
  capped at 30 total with five visible rows. Provider-qualified recording IDs avoid
  collisions. Existing numeric saved choices load as NetEase references and are
  written in the new format on the next save. Current LRCLIB results remain pinned.
- Successful raw lyrics and versioned pronunciation persist in Application Support
  using SQLite. Reads/writes run on workers; the bounded cache holds at most 1,000
  recording entries and about 100 MiB of payload. Retry bypasses both cache layers;
  failed refreshes keep a previous successful result. Corrupt or unavailable storage
  becomes a cache miss rather than a playback failure. The terminal shares the cache.
- Native diagnostics and worker stderr go to Application Support/Logs/app.log;
  terminal diagnostics use cli.log. Each rotates at 2 MiB with four backups. Entries
  are bounded and omit lyrics, artwork, credentials, and playback polling. Help's
  Open Logs Folder command reveals this directory.
- An original teal music-note/lyric-lines icon is drawn by scripts/render-icon.swift.
  The build renders all iconset sizes, packages AppIcon.icns, sets the bundle icon,
  and signs the resulting app.
- Live provider-chain lookup for 忽然 / Li Zhi / 你好,鄭州 returned 12 timed LrcAPI
  lines for the 126.853-second recording in approximately 2.7 seconds. A fresh lyric
  session then loaded the raw lyrics and pronunciation from disk with network access
  disabled. All 209 Python and 41 Swift tests passed, covering source precedence, reference migration,
  cache refresh/eviction/corruption, cancellation, and log rotation.
- Final on-screen verification was blocked by computer control returning
  cgWindowNotFound for Lyrics Pro and Finder. The icon image was rendered and
  inspected directly; live Dock/Finder presentation and the updated picker still
  need inspection when the desktop is accessible.

## Portable personal distribution — 0.5.0

- `scripts/build-macos.fish` now produces a self-contained Apple Silicon app and
  `Lyrics-Pro-0.5.0-macOS-arm64.zip`, including installation instructions. The
  deployment target remains macOS 15.0. No recipient-side Python, uv, Homebrew,
  development environment, or checkout is required.
- The separate packaging project pins Python 3.12.16 and PyInstaller 6.22.3 with
  its own dependency lock. Development Python remains unchanged. A PyInstaller
  directory bundle under Contents/Helpers/LyricsBackend.app separates executable
  code and resources as required by macOS code signing. It includes ToJyutping's
  trie, all Taibun msgpack dictionaries, the native msgpack extension, version
  metadata, and license notices. No runtime extraction or interpreter download.
- The native launcher resolves its helper relative to the app and removes inherited
  Python/dyld configuration. System curl and osascript use absolute paths. The old
  absolute-path Backend.json is gone. The NDJSON protocol and Application Support
  storage remain compatible; existing cached lyrics and selections are reused.
- The build removes SwiftPM's developer-toolchain runtime search path, verifies
  all four Mach-O files target arm64 with macOS minimums no newer than 15, signs
  libraries then helper then app, and checks the complete nested signature.
  A failed build leaves the previous successful app available.
- 210 Python tests passed on both development Python 3.15 and packaging Python
  3.12; 42 Swift tests passed. The actual ZIP was extracted to a renamed path with
  spaces. Its worker passed offline pronunciation, metadata, SQLite, rolling log,
  NDJSON startup, shutdown, and restart checks while repository/external Python
  reads, app-bundle writes, network access, and Apple Events were denied.
- Live 0.5.0 launch on the rightmost DELL P2725QE displayed 粵語殘片, artwork,
  timed NetEase lyrics, and Jyutping with the bundled worker. The existing cache
  was reused and diagnostics reached Application Support/Logs/app.log. Music
  remained paused at 89.465 seconds during the initial check.
- Personal builds are ad-hoc signed, not notarized. First-launch approval and
  Automation permission on a separate Mac remain unverified; a macOS 15 machine
  is not available in this workspace. Developer ID/notarization, Intel builds,
  older macOS, and automatic updates are deferred.

## Expanded lyric viewport — 0.5.1

- Source/timing information and retry now share the top header, aligned with the
  lyric column. Reducing the body inset adds 68 points to the live lyric viewport
  while preserving artwork placement and font sizes. Normal timed rows follow at
  45% of the viewport; oversized rows still align to the top.
- Removed the live metadata caption and music-note icon from the bottom left.
  Demo attribution and bottom-right recording/pronunciation controls remain.
- All 42 Swift tests passed. The installed build was checked on the rightmost
  display at compact, default, and full-screen sizes. Live playback advanced the
  highlight and scroll position; manual browsing, Resume following, paused lyric
  seeking, and the upward recording picker worked. The long/mixed-text demo
  wrapped correctly. Original paused playback was restored at 155.924 seconds.
- Loading/error/plain protocol states and untimed following are covered by existing
  tests; error and untimed layouts were not separately exercised live. The README's
  single screenshot now shows the expanded layout. Published 0.5.0 assets remain
  unchanged.

## Remaining polish

Continue checking keyboard use, accessibility, reduced motion, and first-launch
permission recovery on recipient Macs. The historical stages above describe their
original checkpoints; repository-dependent packaging was replaced in 0.5.0.
