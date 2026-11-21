# Lyrics Pro

Sing along with Apple Music using synchronized lyrics and local Cantonese Jyutping
or Taiwanese Hokkien Tâi-lô pronunciation.

**[Download for macOS](https://github.com/inhzus/lyrics-pro/releases/latest)** ·
Apple Silicon (M1 or newer) · macOS 15+ ·
**[Read lyrics online](https://lyrics.inhzus.io)** (Taiwanese songs with Tâi-lô, no app needed)

![Lyrics Pro showing a Wu Bai live recording with album artwork, synchronized lyrics, and Tâi-lô pronunciation](docs/images/lyrics-pro.jpg)

## Features

- Lyrics that highlight and scroll with the music, colored by the album cover.
- Album artwork from Music, or the Apple catalog when Music has none.
- Local, dictionary-based pronunciation: no AI service, account, or API key.
- Play/pause, previous/next, timeline seeking, and click-to-seek lyric lines.
- Alternative recordings, offline cached lyrics, and 66 bundled proofread songs.

## Install

Requires an Apple Silicon Mac (M1 or newer) with macOS 15 or later.

**With Homebrew:**

```fish
brew install --cask inhzus/tap/lyrics-pro   # update later with: brew upgrade --cask lyrics-pro
```

**Or download it:** get the ZIP from
[Releases](https://github.com/inhzus/lyrics-pro/releases/latest), unzip it, and drag
**Lyrics Pro.app** into **Applications**. The app is not notarized, so the first time
macOS may block it: try to open it, then choose **System Settings → Privacy &
Security → Open Anyway**. To update, replace the app; your settings and saved lyrics
are kept.

Then open Lyrics Pro, play a song in Apple Music, and click **OK** when macOS asks
whether Lyrics Pro may control Music. If you declined, turn it on under **System
Settings → Privacy & Security → Automation** and choose **Lyrics Pro → Reconnect to
Music**. More help: [installation details](packaging/Install.txt).

## Use

The footer holds two menus: **Source** and pronunciation (bottom right).

- **Pronunciation:** choose Cantonese, Hokkien, or Original (no pronunciation).
  - **Global Default** applies to every song (initially Cantonese).
  - **This Song** overrides it for one song, on any album; **Use Default** removes
    the override.
  - Proofread songs show their own supplied spelling unless you pick another
    language for them.
- **Source:** if the lyrics don't match, pick another recording. **Automatic**
  prefers a bundled proofread version when the title and duration match, then
  online lyrics. Your pick is remembered for the song.
- **Follow along:** click a timed line to jump there. Scroll to browse freely, then
  click **Resume following**.
- **Settings (⌘,):** show Chinese as provided, Simplified, or Traditional; change the
  text size (also ⌘= / ⌘−); shift the timing if lyrics drift; keep the window on top;
  or clear cached lyrics and saved choices.
- **No lyrics?** Click retry at the top right, or **Lyrics Pro → Reconnect to Music**.
  Logs are under **Help → Open Logs Folder**.

Lyrics come from NetEase Cloud Music, with LrcAPI and LRCLIB fallbacks; coverage and
timing vary by recording, and uncached lyrics need an internet connection. Only song
metadata is sent, never audio. Hokkien uses southern Taiwanese Tâi-lô.

## Build from source

On an Apple Silicon Mac with macOS 15+, install Apple's Command Line Tools
(Swift 6 or newer), [uv](https://docs.astral.sh/uv/), and fish, then:

```fish
fish scripts/build-macos.fish   # portable app and ZIP in dist/
open "dist/Lyrics Pro.app"
```

Development, testing, and packaging guidance is in [AGENTS.md](AGENTS.md).

## Terminal client

From a checkout, with Apple Music and `uv`:

```fish
uv sync --locked
uv run lyrics-pro --language cantonese   # or hokkien; default cantonese
```

It follows playback and prints lyrics (control playback in Music; Ctrl-C exits) and
does not use the app's saved song preferences.

## License and acknowledgements

[MIT License](LICENSE) · Copyright 2026 inhzus. Pronunciation uses
[ToJyutping](https://github.com/CanCLID/ToJyutping) and
[Taibun](https://github.com/andreihar/taibun); third-party notices are included in
the app. Transcriptions keep their [supplied credits](packaging/Proofread-content.txt)
and the website links each page to its source; song text and transcription are not
covered by the MIT license.
