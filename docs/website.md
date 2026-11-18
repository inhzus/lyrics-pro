# Lyrics website

`site/` is an [Astro](https://astro.build) static site built from the supplied
transcriptions in `resources/lyrics-spelling/`. The home page is an artist
directory grouped by the Mandarin pinyin initial of each name (`src/lib/artists.ts`,
via `pinyin-pro`; the pinyin is only a sort key and is never displayed). Search
accepts traditional, simplified or mixed characters: the build folds titles and names
to simplified one character at a time with `opencc-js` (Taiwan → mainland, so 臺
matches 台), and the page applies the same mapping to the query with a small table of
only the characters that occur (`src/lib/search.ts`, `src/lib/fold.ts`). The rows and
that table are built into `/search.json`, which the page fetches when the search box is
first used, so the home page itself stays small. OpenCC is
build-only and never ships to the browser. Songs use
the same order everywhere: artist, then title, by romanization; artist pages with
more than 10 songs show letter dividers. Its search
box finds songs by title and artists by name or pinyin. There is a page per artist
(`/artists/wu-bai/`) and one per song under its artist (`/songs/wu-bai/tai-wan-zhi-zao/`),
named by toneless pinyin (see URLs below). The transcriptions come from
[台客鬼 Tâi Kheh Kuí](https://taikegui.wordpress.com/). It states no reuse licence,
so the index, every song page and the shared footer link back to it
(`src/lib/source.ts`). Each page shows the lyrics with
their Tâi-lô romanization, plus the credits and source notes. There are no
timestamps, so the site does not depend on timing alignment, providers or the app.

- `src/lib/catalog.ts` reads `resources/proofread-preparation/manifest.json` for
  titles, artists and duplicates; that manifest already includes the reviewed
  metadata overrides. The three exact duplicates are skipped. The build fails if a
  source was added, removed or changed since the manifest was written; rerun
  `uv run --locked python -m scripts.prepare_proofread` (or `--offline`) first.
- `src/lib/transcription.ts` keeps every nonempty source line once, in order. It
  pairs a Han line with the romanization line that follows it, aligns side-by-side
  columns when both lines have the same number of them, and separates credits and
  `Note:` lines. Its patterns mirror `scripts/prepare_proofread.py`; it never
  synthesizes text. Whitespace runs display as one space.
- The interface text is Chinese only (traditional); the site is meant for Chinese
  readers. Song titles and the Tâi-lô romanization stay as transcribed.
- Artist cards, song rows, search results and the artist/song page headers have a pin
  button (`src/components/PinButton.astro`, `src/lib/pins.ts`). Pins are stored in the
  visitor's `localStorage` under `pins` as a list of page paths (`/artists/<artist>/`,
  `/songs/<artist>/<title>/`). Pinned artists appear in a 置頂 section at the top of the home
  page; pinned songs appear in a 置頂 section at the top of their artist's page. 伍佰 and
  五月天 (`DEFAULT_PINNED_ARTISTS` in `src/lib/artists.ts`) are pinned until the
  visitor changes their pins, so they can be unpinned. Without JavaScript the home
  page shows the default pins and no buttons.
- Every page exists in traditional characters at its own path and in simplified
  characters under `/hans/` (`/hans/songs/wu-bai/tai-wan-zhi-zao/`), so search engines index
  both scripts. The page routes live under `src/pages/[...script]/` and list each path twice
  (`inBothScripts` in `src/lib/variant.ts`). `src/middleware.ts` converts the `/hans/` pages
  while they are prerendered (`src/lib/hansHtml.ts`): text, `title`, `placeholder`,
  `aria-label` and meta `content`, `lang` from `-Hant` to `-Hans`, and links to other pages
  moved under `/hans/`; scripts, styles, `code`, templates and `[data-no-convert]` stay as
  written. It uses OpenCC `tw`→`cn` per character (`simplifiedTable` in `src/lib/hans.ts`, the
  same conversion search uses), leaving out characters that are already simplified (么), so
  converting twice changes nothing.
- A 繁/简 switch at the top right of every page links to the other version of the same
  page, and works without JavaScript. A click stores the choice in `localStorage` under
  `script`; only the bare home page `/` follows it, by replacing itself with `/hans/` before
  first paint. No other page redirects, and nothing guesses from the browser language,
  since a crawler that is redirected never sees the other version. Each `/hans/` page also
  gets a `#hans` table with the simplified form of each character on the page and in the
  page scripts' interface text; `src/lib/script.ts` uses it to convert rows that scripts
  add later (search results, pin labels), and the home page adds `/search.json`'s table.
  Stored paths (pins, `/search.json` rows) stay traditional; links built in the browser
  get the prefix from `pagePath`.
- URLs: `src/lib/slug.ts` romanizes artist names and titles with `pinyin-pro` (no tones,
  `ü` as `v`), keeps Latin letters and digits, joins everything else with `-` and drops
  characters without a romanization (bopomofo, kana). Song titles drop bracketed English
  names and `feat.`/`ft.`/`with` credits (心內話 (Bottom of My Heart) → `xin-nei-hua`). A
  short reviewed `READINGS` table fixes readings it gets wrong (車 → che, 樂團 → yue tuan, …). The slugs appear only in
  URLs. `checkPaths` in `src/lib/catalog.ts` fails the build if two artists, or two songs
  of one artist, share a path or a name romanizes to nothing; add a reading to fix it.
  Correcting a title or artist changes its URL.
- Pages were first published at `/artists/<12-character SHA-256 prefix of the name>/` and
  `/songs/<manifest id>/`. The build writes `dist/_redirects` (Cloudflare Pages, 301) from
  each old path to its current one (`legacyRedirects` in `astro.config.mjs`), and
  `/moved.json` holds the same map: `src/lib/pins.ts` fetches it only when stored pins still
  use old paths, rewrites them in place once, and drops songs that no longer exist.
- A round theme button beside the 繁/简 switch cycles auto → light → dark
  (`src/lib/theme.ts`). Auto follows the system and stores nothing; light and dark are
  stored under `theme` and applied before first paint. CSS picks the icon from
  `:root[data-theme]`.
- Song pages have reading controls for showing or hiding the romanization and for
  text size. Choices are stored in the visitor's `localStorage`, and without
  JavaScript the page shows the default view.
- Fonts are self-hosted: Noto Serif TC (fontsource, split by unicode-range) for
  Chinese text and Charis SIL 7.000 for Tâi-lô. Noto Serif TC lacks simplified-only
  glyphs (爱, 简, 关), so `/hans/` pages put Noto Serif SC first. Its stylesheets are
  imported with `?url` and linked only on `/hans/` pages (`Base.astro`), so traditional
  readers never download them. The fontsource Charis subsets omit
  U+030D, U+0358 and U+030B, so SIL's official woff2 files are vendored in
  `public/fonts/` with their OFL licence. A Vite plugin in `astro.config.mjs` narrows
  each Noto `unicode-range` to the characters in the catalog and templates (plus their
  simplified forms for SC) and drops
  slices that cover none (`src/lib/fontSubset.ts`), which keeps the render-blocking CSS
  small; the font files themselves are unchanged.

## Develop

Requires Node 24 (`site/.node-version`). `site/.npmrc` pins the public npm registry
so the lock file never records a private mirror.

```fish
cd site
npm ci
npm run dev        # http://localhost:4321/ with live reload
npm test           # vitest: transcription parsing and catalog checks
npm run build      # writes site/dist/
npm run preview    # serves site/dist/
```

CI runs `npm ci`, `npm test` and `npm run build` in the `site` job.

## Cloudflare Pages

Connect the repository and use:

| Setting | Value |
|---|---|
| Framework preset | Astro |
| Root directory | `site` |
| Build command | `npm run build` |
| Build output directory | `dist` |

Cloudflare clones the whole repository, so the build can read `../resources`. It
picks up `site/.node-version` and installs from `site/package-lock.json`.
`public/_headers` caches hashed `/_astro/*` assets immutably and fonts for 30 days.
The generated `_redirects` keeps links to the original hashed and ID paths working.

Search engines may index the site. `public/robots.txt` allows every crawler and points to
`/sitemap.xml`, which the build generates with the home page, every artist and every song,
each followed by its `/hans/` version (`src/lib/sitemap.ts`); it has no `lastmod`, since the
build knows no per-page date. Every page has a self-referencing canonical and lists both
versions as `hreflang` alternates (`zh-Hant`, `zh-Hans`, and `x-default` for traditional),
in its head and in the sitemap. One `zh-Hans` version serves simplified readers everywhere,
including Singapore and Malaysia; region codes would only matter for different pages.
Cloudflare's managed robots.txt adds its content-signal block to this file. Once, after the
first deploy, verify the domain in [Google Search Console](https://search.google.com/search-console)
(a DNS TXT record in Cloudflare) and submit `https://lyrics.inhzus.io/sitemap.xml`;
[Bing Webmaster Tools](https://www.bing.com/webmasters) can import the site from Search Console.

Set the production branch to `main` and enable preview deployments for other branches.
Each push to a pull request then gets a Cloudflare Pages check and a preview URL. The
integration reacts only to pushes, so connecting it does not build open pull requests
until they receive a new commit. Build watch paths `site/*` and `resources/*` skip
builds for changes that cannot affect the site.

The site publishes copyrighted song lyrics. Whether to deploy it publicly is
your decision; the build only produces files.
