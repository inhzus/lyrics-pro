# Prepare the supplied song collection

The preparation tool processes the original files directly under
`resources/lyrics-spelling/`. It preserves those files. The accepted
`shao-nian-eh-an-la/` experiment is a subdirectory and is not another raw input.

The [reviewed Wu Bai collection](../resources/lyrics-spelling/wubai-reviewed/README.md)
is a separate, explicitly requested integration: 51 new adaptations plus the
previously accepted first song, with one song still awaiting reliable timing.
Its frozen phrase assignments and source-backed repairs are reproduced offline
with `uv run --locked python -m scripts.prepare_wubai --check` (audit) or
`--integrate` (recreate and bundle). The original bulk manifest remains a record
of the conservative automatic pass; the collection verifier audits both manifests.
These reviewed exceptions do not lower the automatic alignment gate.

Run from the repository root:

```fish
# Small pilot, followed by a resumable full run.
uv run --locked python -m scripts.prepare_proofread --limit 8
uv run --locked python -m scripts.prepare_proofread --promote
uv run --locked python -m scripts.verify_proofread_collection

# Revisit review/failure results; successful provider snapshots remain frozen.
uv run --locked python -m scripts.prepare_proofread --retry --promote
```

The default outputs are:

- `resources/proofread-preparation/manifest.json`: every processed input, raw
  SHA-256, title, artist, attribution, status, duplicate relationship and reasons.
- `resources/proofread-preparation/README.md`: collection summary and review list.
- Per-song directories: parsed pairs and source line numbers; candidate metadata;
  selected `proofread.json` and `timed.json`; `alignment.json`; and a listening
  preview with the timestamp beside the lyrics and spelling on the next line.
- `.build/proofread-snapshots/`: request parameters, timestamps, provider responses
  and failures. These working snapshots are ignored by Git.
- `src/lyrics_pro/data/proofread/`: only promoted app assets. Raw inputs and review
  reports are not included in the app bundle.

Interruption saves completed results. Resume checks source hashes, metadata
overrides, tool version and the hashes of the provider snapshots used by each
input. `--retry` retries previously failed requests and reprocesses review
items; it does not refresh successful snapshots. To conduct a genuinely fresh
survey, use a new `--output` and `--snapshots` directory. Existing accepted assets
are never overwritten. A changed accepted source requires a reviewed revision.

For ambiguous filename metadata, the default
`resources/proofread-metadata-overrides.json` records reviewed corrections. Its
five entries separate explicit artist prefixes from 桂花巷, 叨位是你的厝, 怪手,
雪中花 and 逆轉勝, preserving the two supplied collaboration credits;
they do not change supplied lyrics or waive parsing/identity checks. Pass `--overrides path/to/overrides.json` to
use another object mapping exact filenames to reviewed `title` and/or `artist` strings.
Overrides are recorded in the manifest and invalidate that input's saved result.
They do not create learned artist aliases or alter the transcription.

Use `--offline` when reprocessing frozen snapshots without network access. Missing
snapshots are reported as lookup failures; they never trigger a request. A new
output directory forces an independent recomputation against the same snapshots.
When changing parsing, matching or alignment behavior, increment `VERSION` in
the preparation tool so earlier results are recomputed against frozen evidence.

## Parsing and timing policy

The supplied words and spelling are authoritative. The tool identifies credit
headers, keeps line numbers, and pairs Han-containing lyric lines with following
romanization lines. Unpaired lines, Latin-only ambiguities, source notes, and
conflicting readings for repeated text require review. All source lines remain
available in the original file. This is deliberately conservative: source notes
may identify a different live arrangement.

Paired columns can be split only when both lines have the same number of explicit
wide-whitespace separators. Otherwise the supplied pair remains whole. Numeric
song titles are preserved; only explicit track prefixes and repeated-title track
numbers are stripped from filename metadata. Whitespace is collapsed for display,
not used to rewrite supplied words or diacritics.

Duration comes from provider catalog records. There is no invented playback
duration. Search order is NetEase → LrcAPI → LRCLIB. Title/version and artist must
match before a candidate can be promoted. Unresolved artist aliases remain review
items. Requests are sequential, at least one second apart, cancellable, and use
the app's bounded curl transport. Transient failures get at most three attempts.
At most three lyric candidates are inspected per provider; search result limits
are 30 NetEase, 30 LrcAPI and 20 LRCLIB results per query.

The first provider with usable verified timed results supplies the candidates.
The tool prefers a complete exact alignment, then coverage of both the supplied
transcription and online sung rows, then the fraction of exact sung rows. This
prevents a short exact fragment from outranking a fuller review candidate.
Equally supported candidates with different timing or incompatible
durations require recording review. Equivalent timing is deduplicated. No two
sources' timelines are combined.

## Alignment and promotion

The documented [single-song experiment](proofread-lyrics-alignment.md) is preserved
as `scripts/proofread_alignment.py`; a regression test reproduces the accepted
first song. Collection preparation adds a strict pass ahead of that prototype:

1. Expand explicitly paired columns without creating text or spelling.
2. Reuse passages only when they occur multiple times in the supplied content
   with consistent spelling. Keep the online repeat flow.
3. Match exact normalized text monotonically, allowing up to six adjacent supplied
   blocks in one timing row. Merges cannot cross an intervening repeated passage.
4. Retain all source timestamps, ordering, gaps and classified credit rows.
5. Require all sung rows and all supplied blocks to be accounted for. Duplicate
   timestamps, ambiguous alignments, unresolved rows and warnings block promotion.

If strict alignment fails, the original approximate prototype produces a review
candidate. **Approximate candidates never become app assets automatically.**
Reports retain both sources, source row indexes, supplied block IDs and hashes of
the actual saved input files. `audio_verified` stays false. Text equality cannot
prove correct pronunciation or detect a constant provider timing delay.

Statuses are `ready`, `duplicate`, `parsing review`, `recording review`,
`alignment review`, `no timed lyrics`, and `lookup failure`. Completion means
every input has a result, not that every song qualifies for automatic bundling.

Promoted assets use independent `proofread:<id>` references, with title and duration
matching in the app. Artist and album remain descriptive. Overlapping match windows
with an existing asset require review. The previously accepted 少年吔，安啦 asset is
preserved even though its reviewed approximate matches do not meet the new batch
gate.

New assets use the language designation `supplied`, since the collection contains
mixed languages and header labels are not sufficient language evidence. Auto shows
the supplied spelling. Original hides it; explicit Cantonese/Hokkien selects the
existing local engine. The pronunciation menu still has four choices.

This workflow neither commits changes nor publishes a release. Before a future
release, review content notices and distribution scope separately from code licensing.
