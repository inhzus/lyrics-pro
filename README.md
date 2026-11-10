# Lyrics Pro

A personal macOS terminal companion for Music: print the active lyric line with
Cantonese Jyutping or Taiwanese Hokkien Tâi-lô. Pronunciation runs locally using
ToJyutping and Taibun. NetEase Cloud Music is the primary lyrics service, with
LrcAPI and LRCLIB as fallbacks. No AI service, login, or API key is used. The NetEase
integration uses unofficial website endpoints, which can change.

## macOS app — portable personal build

A native SwiftUI companion is available alongside the terminal app. It shows live
Music metadata, playback time, artwork, lyrics, and local pronunciation. Build with Apple's
Command Line Tools (Swift 6 or newer), `uv`, and fish on an Apple Silicon Mac:

```fish
fish scripts/build-macos.fish
open "dist/Lyrics Pro.app"
```

The app requires **Apple Silicon and macOS 15 or newer**. Share
`dist/Lyrics-Pro-0.5.0-macOS-arm64.zip`; recipients unzip it and drag Lyrics Pro.app
into Applications. Python, `uv`, Homebrew, the repository, and developer tools are
**not needed at runtime**. The app can be moved or renamed in Finder.

The build uses a separate, locked Python 3.12 environment in `packaging/.venv`
and leaves the development `.venv` unchanged. It bundles Python, ToJyutping and
Taibun dictionaries, msgpack, package metadata, and licenses in a background helper
app using PyInstaller. The native UI launches that helper by a bundle-relative path.
No local HTTP server or terminal window is needed. System `curl` and `osascript`
are accessed by absolute macOS paths.

Live mode follows Music every half second, including pause/resume and external
seeks. Playback changes only when you use a control; the app does not launch Music.
Artwork is read on track
changes, limited to 4 MiB per image, and cached for at most eight tracks in memory.
Missing, oversized, or unreadable artwork uses a placeholder. The worker uses
temporary files only while extracting artwork and removes them afterwards.

Lyrics use the NetEase → LrcAPI → LRCLIB pipeline. The pronunciation picker remembers
**Auto / Cantonese · Jyutping / Hokkien · Tâi-lô / Original only** across launches.
Auto uses the artist-based guesses described below; it is not language detection.
Unknown artists show original lyrics until you choose a language. Pronunciation runs
locally, with no AI service or API key. English-only lines do not repeat underneath.

Timed lyrics highlight the current line and smoothly center it as Music advances.
Original text is highlighted in white, with pronunciation in teal. Manual scrolling
pauses automatic movement while the highlight continues; **Resume following** returns
to the current line. A new song restores automatic following. Pauses and seeks in
Music update the view; untimed lyrics remain a normal scrollable list. Reduce Motion
disables scrolling and highlight animations. Explicit blank timestamps clear the
highlight during musical gaps.

Use the previous, play/pause, and next buttons below the timeline to control Apple
Music. Previous goes directly to the previous song. Click or drag the timeline to
seek; dragging previews the time and sends one request on release. Seeking preserves
playing/paused state. Clicking a nonblank timed lyric seeks to that timestamp and
immediately resumes automatic following; timeline seeking preserves manual browsing. Timed rows
offer **Copy lyric** in their context menu; untimed text remains selectable.

Play/pause, timeline, and lyric clicks respond immediately while Music confirms the
action in the background. Lyrics remain readable and scrollable. A shared local clock
keeps the timeline and highlighting moving between Music snapshots. Repeated seeks
keep only the latest unsent destination; rapid play/pause clicks settle on the final
requested state. Next/Previous accept one skip at a time without dimming the player.

Controls are disabled in demos or when Music has no playing/paused track. Requests
and visual previews for an old track are discarded when the song changes. After one
second a small Updating Music indicator appears; failures restore confirmed playback
and show a message without removing lyrics. Commands are never automatically retried.

Browse the complete lyrics with the trackpad or scroll bar. Source links and
timed/untimed labels appear above the lyrics. The circular retry button fetches the current
song again without restarting the Music connection. Loading, no match, instrumental,
and error states have separate messages. Transient failures receive three lookup
attempts; Try again resets them. Changing language reuses raw lyrics already fetched.
Raw lyrics and pronunciation also persist in a bounded SQLite cache under
`~/Library/Application Support/Lyrics Pro/lyrics-cache.sqlite3`, shared with the terminal
client. Successful cached results work after restart and offline; errors and missing
results are not persisted. The cache holds up to 1,000 recordings and approximately
100 MiB of payload, evicting least-recently-used entries. Pronunciation is keyed by
content, language, and engine version. Retry bypasses memory and disk caches;
failed refreshes retain usable cached lyrics. Track and language changes discard stale results.
Language changes and lyric retries preserve manual browsing and restore the browsed
row where possible. The bottom-right pronunciation capsule has a checked menu of full
language names. Hovering a clickable lyric softly highlights its lyrics and pronunciation;
the playing line stays brightest. The progress bar shows elapsed time and duration; the play/pause button
communicates playback state without a separate Playing/Paused label. The header
shows connection issues only.

The **Recording** capsule beside pronunciation opens a compact, scrollable picker
showing at most five rows at once, with up to 30 eligible NetEase and LrcAPI alternatives.
Each row includes title, artist, album, duration, and source. Matching keeps the same
normalized title and duration within two seconds. Automatic lookup prefers **NetEase,
then LrcAPI, then LRCLIB**. A later timed result can improve an earlier plain-text result.
LrcAPI artist-name differences require matching album information as well. If the
providers cannot resolve the recording, the app automatically tries up to three ranked
NetEase candidates. Automatic choices do not create saved mappings or artist aliases.
Alternatives load in the background, and switching keeps current lyrics visible
until replacement lyrics and pronunciation are ready. Failed switches leave the
previous selection intact. Successful manual choices are remembered for the exact
Apple Music title/artist/album/duration. **Automatic** in the picker clears a manual
override after successfully loading the automatic result.
Up to 256 choices persist locally in
`~/Library/Application Support/Lyrics Pro/recording-choices.json`. Recording IDs include
their provider; existing NetEase-only choices load automatically. No AI is used. The duplicate pronunciation
label above the source has been removed; selection remains in the bottom-right footer.

Use **Lyrics Pro → Reconnect to Music** to restart the worker. **Preview → Display**
switches between Live Music and the original Stage 1 demos. Demo lyrics and progress
remain explicitly labeled and are unrelated to the currently playing song.

**Help → Open Logs Folder** opens `~/Library/Application Support/Lyrics Pro/Logs`.
The app writes `app.log`, including worker diagnostics; the terminal writes `cli.log`.
Each rolls at 2 MiB with four backups. Logs include lookup timings, track metadata,
cache activity, selections, and failures, but not lyric bodies, artwork, or credentials.
Storage failures do not prevent lyric lookup. The app icon is an original vector
drawing in `scripts/render-icon.swift`, rendered into a complete `.icns` during build.

Allow Music Automation access if macOS prompts. If denied, enable Music for Lyrics
Pro under System Settings → Privacy & Security → Automation, then choose
**Reconnect**. Transient Music-read failures retry automatically; denied permission
waits for an explicit reconnect. Closing the window or quitting the app stops its
worker and in-flight scripts. Worker crashes show a reconnect action.

The green window button enters fullscreen. The **Preview** menu provides compact
and default window sizes, preserving the current display (exit fullscreen first).
Use the rightmost monitor for interactive checks.

This personal build is ad-hoc signed and **not notarized**. A downloaded copy may
need approval through System Settings → Privacy & Security → Open Anyway after
the first attempted launch. Approve only a trusted copy; do not disable Gatekeeper.
See the included [installation instructions](packaging/Install.txt). Developer ID
signing/notarization, Intel builds, and older macOS support are deferred. The bundle
includes Apple's [Automation usage description](https://developer.apple.com/documentation/bundleresources/information-property-list/nsappleeventsusagedescription).
See [the staged UI plan](docs/macos-ui.md)
for the checkpoint and remaining work. The terminal app below still works as before.

## Run

Requires macOS, Music, `curl` (included in macOS), and `uv`. From this directory:

```fish
uv sync --locked
uv run lyrics-pro
```

Play a song in Music. Allow the terminal to control Music if macOS asks. The app
only reads playback information; it does not launch Music or change playback.

Auto mode guesses Cantonese for 陳奕迅 / Eason Chan and Hokkien for 伍佰 / Wu Bai /
China Blue. **These are artist-based guesses, not language detection:** both
artists also sing in Mandarin. Override the guess for the whole run:

```fish
uv run lyrics-pro --language cantonese
uv run lyrics-pro --language hokkien
```

Unknown artists display original lyrics only until you restart with a language
flag. Mandarin pronunciation is outside this prototype's scope.

Each new active line is appended with its timestamp and pronunciation. Music's
position is checked every half second. Pause/resume and seeks made in Music are
followed automatically; the terminal provides no scrolling controls or seeking.
Untimed lyrics print once in full. Ctrl-C cancels any in-flight network request
and exits. If local pronunciation is currently being computed, it finishes first.

## Matching and pronunciation

- Search NetEase using simplified Chinese titles and known Chinese artist aliases,
  then the original metadata if necessary. Match title and artist credits, reject
  duration differences greater than two seconds, and prefer the matching album.
  Live/remix/version names are kept distinct from studio titles.
- If song search finds no usable timed match, search the album and inspect its
  tracks. This finds studio recordings such as 天下無雙 that song search can miss.
  Check the requested album before accepting a compilation with similar duration.
  Searches are bounded to 30 songs per query, 20 albums per query, three matching
  album lookups, and three lyric candidates per phase. Song IDs are deduplicated.
- Use NetEase timed lyrics or an explicit instrumental result immediately. If
  NetEase has no match, only plain lyrics, or a request error, try LrcAPI and then
  LRCLIB in the same lookup round. LrcAPI searches original/simplified titles,
  validates duration, and requires matching artist credits or an exact album match.
  LRCLIB uses metadata lookup followed by title searches with
  Chinese spelling variants, validates the artist and ±2-second duration limit,
  and prefers the matching album. Each title search examines at most 20 results.
- Prefer a matching timed fallback result over plain NetEase lyrics; otherwise
  retain valid NetEase plain lyrics. Plain lyrics print once. The selected source
  and link are displayed. These are the three lyric providers; timed lyrics
  can still be inaccurate for an edition.
- Cantonese uses ToJyutping on the full original line, supporting simplified and
  traditional characters with sentence context. Only unresolved Han characters
  receive unknown markers; English words, numbers, and punctuation remain intact.
- Hokkien defaults to southern Taiwanese Tâi-lô with tone numbers and no tone
  sandhi. Local dictionary output is guidance, not a transcription of a singer's
  exact pronunciation. Unavailable Han readings appear as `[字: ?]`.
- Original lyrics and timestamps are preserved. Successful lyrics, their source,
  and readings persist in the Application Support cache described above. Transient
  failures are not cached as missing lyrics.
- Network requests contain song metadata, not audio. No audio is captured.
- The installed engines and their dictionaries are used as published; no models
  or services are trained or hosted by this project.

## Troubleshooting

- **Automation denied:** enable Music for the terminal running this command under
  System Settings → Privacy & Security → Automation, then rerun. The responsible
  app may be your terminal or IDE.
- **Music closed/stopped:** open Music and play a song; the CLI keeps waiting.
- **Network failure:** requests use IPv4 because it worked in the feasibility
  check where other requests timed out. Fallback is attempted before retrying
  NetEase. If no service provides usable lyrics, transient failures receive
  at most three lookup rounds per track, with backoff. After that, restart to
  retry the same song. Ctrl-C cancels requests without starting a fallback.
- **No matching lyrics:** the song may be absent, metadata may differ, or the
  recording may fail the strict duration check. The CLI continues with the next
  song. No fabricated timestamps or lyrics are generated.

## Development

```fish
uv run pytest
fish scripts/test-macos.fish
```

Rebuild the portable app and validate the actual ZIP:

```fish
fish scripts/build-macos.fish
packaging/.venv/bin/python packaging/verify_portable.py dist/Lyrics-Pro-0.5.0-macOS-arm64.zip
```

The build checks all Mach-O architectures, deployment minimums, linked library
paths, and nested code signatures, then runs the bundled offline self-check.
The ZIP test unpacks and renames the app into a path containing spaces, denies
access to the repository and external Python installations, makes the app
read-only through a test sandbox, and disables network/Apple Events. It verifies
both pronunciation engines, SQLite, rolling logs, NDJSON startup, shutdown, and
restart without touching Music. This does not replace first-launch/Gatekeeper
validation on a separate Mac, especially one running the minimum macOS version.
Temporary build products and the previous successful app are retained under `.build/`.
The packaging lock is independent of `uv.lock`; when changing runtime dependencies,
refresh `packaging/uv.lock` too (`uv lock --project packaging --python 3.12.16`).

Tests mock Music and network access, with local pronunciation smoke checks.
Native tests use Swift Testing. The script disables XCTest and explicitly loads
the toolchain's TestingMacros plugin when present, working around its missing
automatic discovery in some Command Line Tools builds. No Swift package dependencies
are downloaded.
Tests cover fragmented pipe events, Unicode, stale artwork and lyrics, language
changes during requests, cached pronunciation, retries and cancellation, distinct
lyric states, remembered preferences, pause/seek snapshots, missing artwork, denied
permissions, timeouts, and process cleanup. Following tests cover timestamp boundaries,
gaps, duplicate timestamps, late lyric arrival, external seeks, pause, manual browsing,
resume, and preservation of browsing through lyric reloads.

Live Music reading and lyrics lookup can be checked separately without printing lyrics:

```fish
uv run python -c 'from lyrics_pro.music import read_playback; print(read_playback())'
uv run python -c 'from lyrics_pro.lyrics import LyricsProvider; from lyrics_pro.models import Playback; r = LyricsProvider().lookup(Playback("playing", "浮誇", "陳奕迅", "U 87", 284)); print({"found": r is not None, "synced": r.synced if r else False, "lines": len(r.lines) if r else 0})'
```

Sources: [NetEase community API reference](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced),
[LRCLIB API](https://lrclib.net/docs),
[ToJyutping](https://github.com/CanCLID/ToJyutping),
[Taibun](https://github.com/andreihar/taibun).
