# Reproduce timed, proofread lyrics and spelling

Use this guide when a user supplies manually proofread lyrics and their associated
spelling (romanization), and asks for a timed version for listening review.
This is an agent workflow and an offline prototype, not an installed app feature.

## Authority and scope

1. **The user supplies the authoritative words and spelling.** Keep them paired.
   Preserve characters, tone marks, dialect spellings, punctuation, Latin text,
   and mixed-language passages. Do not silently correct them or regenerate them
   with Taibun, ToJyutping, translation, or an AI service.
2. **One selected online recording supplies the timing and main playback flow.**
   Follow its row order, repeated sections, and blank musical-gap events.
   Use NetEase → LrcAPI → LRCLIB through the existing provider workflow.
3. Match the two sources, replace online wording with the corresponding
   proofread wording, and attach the supplied spelling. Matching normalization
   must never become output normalization.
4. Produce a timestamped candidate for the user to check by listening.
   Text similarity is not evidence of correct sung pronunciation or exact onset.

Do not modify application code, the user's cache, or Music playback to perform
this workflow. Keep inputs, extracted scripts, and outputs in a temporary or
user-selected directory outside Git. Do not publish or bundle supplied/source
content unless that distribution is separately authorized and reuse rights are
established; attribution alone is not a license.

## Inputs and recording selection

Obtain the song title, artist, album/version, and duration. Use the existing
matching rules in [lyrics.py](../src/lyrics_pro/lyrics.py); inspect candidate
identity before accepting a result. Studio/live/remix versions are not
interchangeable. Do not combine providers' timestamps or recordings in one run.
If the recording is ambiguous, resolve its identity before alignment.

Use either a fresh result from the existing provider classes or a read-only
snapshot of a previously selected result. A cache hit is not a fresh network
lookup. Record the provider-qualified reference, source URL/label, and whether
the timing was cached. Never invent timestamps if no usable timed source exists.

Prepare two UTF-8 JSON files:

- `proofread.json`: `recording_id`, optional `source` attribution, ordered `blocks`,
  and optional `backing_prefixes`.
- `timed.json`: the same `recording_id`, timing `source`, and ordered `lines`
  containing numeric `time` in seconds, `text`, and optional `kind`
  (`lyric`, `gap`, or `credit`).

Each proofread block contains a unique string `id`, `text`, and `spelling`.
Optional `parts` is an explicitly reviewed two-item list of text/spelling pairs.
It must concatenate back to the original block, ignoring whitespace only.
Do not guess how to split spelling using Chinese character counts.

Use `repeat: true` only for a supplied passage explicitly approved for reuse,
such as a chorus. Mark its supplied occurrences consistently. The first
equivalent occurrence is canonical when punctuation/spacing differs; conflicting
spellings stop the run. Other repeated verses stay in their original sequence.
This allows online chorus occurrences omitted from a compact transcription to
receive the supplied chorus words, without generating any new words.

`backing_prefixes` contains exact, reviewed prefixes present only in the online
text. The prototype excludes them from foreground matching but reports every
omission. Never strip arbitrary parentheses: they may contain sung content.

Structural example (placeholders, not test lyrics or timestamps):

~~~~text
proofread.json
{
  "recording_id": "<provider>:<selected-recording-id>",
  "source": "User-provided proofread transcription; attribution if applicable",
  "blocks": [
    {"id": "verse-01", "text": "<supplied lyric>", "spelling": "<supplied spelling>"},
    {"id": "chorus-01", "text": "<supplied chorus>", "spelling": "<supplied spelling>",
     "repeat": true}
  ],
  "backing_prefixes": []
}

timed.json
{
  "recording_id": "<same selected-recording-id>",
  "source": "<timing provider and recording URL>",
  "lines": [
    {"time": <actual numeric source timestamp>, "text": "<online lyric>", "kind": "lyric"},
    {"time": <actual numeric source timestamp>, "text": "", "kind": "gap"}
  ]
}
~~~~

The placeholder example is intentionally not executable JSON. Replace every
placeholder with supplied content or observed metadata.

## Alignment procedure

1. Preserve the raw input files. The output records SHA-256 hashes of both files.
2. For matching only, normalize Unicode, simplified/traditional characters, case,
   whitespace, and punctuation. The prototype uses the project's pinned Taibun
   character conversion, which is incomplete for some characters; unmatched
   variants remain review candidates.
3. Assign exact normalized reusable passages to their online occurrences.
   Remove those occurrences from verse alignment, retaining their original slots.
4. Align remaining proofread blocks and online foreground rows monotonically.
   Compare one block with one or two consecutive verse rows. Exact matches have
   zero edit cost; approximate matches require `SequenceMatcher` similarity
   **≥ 0.70**, then use Levenshtein edit cost with a **0.01** penalty for a
   two-row group. Skipping a block/row costs its normalized character length.
   These are the experiment's heuristics, not calibrated confidence scores.
5. On equal total costs, keep the first path deterministically and mark the verse
   alignment ambiguous. Candidate order is skip-manual, skip-online, one-row,
   two-row. All approximate and ambiguous matches require review.
6. A two-row assignment requires explicit matching `parts`; otherwise preserve
   both timestamps as unresolved. A supplied multi-part block matched to one
   online row stays intact at that row's timestamp.
7. Detect short phrases crossing source-row boundaries. Never interpolate a
   phrase onset or transfer a phrase into another proofread line to hide the
   mismatch. Preserve wording and flag both affected rows.
8. Preserve every source row in the JSON report, including gaps, credits, and
   unresolved rows. Expose unmatched manual blocks separately. Never label an
   unresolved online lyric as proofread or fill its spelling automatically.

This prototype supports one manual block to at most two timing rows. For more
complex splits, multiple manual blocks inside one timed row, non-identical chorus
variants, or reordered recordings, leave the region unresolved and obtain a
reviewed grouping/recording. Do not lower the threshold until everything matches.
The short boundary detector is a warning heuristic, not a complete aligner.

## Run outside the repository

Run these commands from the repository root, using fish. `uv run --locked`
uses the existing project environment and pinned dependency; no new dependency
or application modification is needed.

Extract the two named Python blocks below into a temporary directory:

~~~~fish
set work_dir (mktemp -d /tmp/lyrics-proofread.XXXXXX)
uv run --locked python -B -c '
import pathlib, re, sys
document = pathlib.Path("docs/proofread-lyrics-alignment.md").read_text()
for block in re.findall(r"^```python\n(.*?)^```$", document, re.M | re.S):
    name = block.splitlines()[0].removeprefix("# ").strip()
    if name in {"export_timing_cache.py", "align_proofread.py"}:
        (pathlib.Path(sys.argv[1]) / name).write_text(block, encoding="utf-8")
' "$work_dir"
~~~~

For a cached timing source, list recent entries, then select the full key after
checking its provider reference and recording identity:

~~~~fish
uv run --locked python -B "$work_dir/export_timing_cache.py"

set cache_key 'REPLACE_WITH_FULL_VERIFIED_CACHE_KEY'
set recording_id 'REPLACE_WITH_PROVIDER_QUALIFIED_RECORDING_ID'
uv run --locked python -B "$work_dir/export_timing_cache.py" \
    --key "$cache_key" --recording-id "$recording_id" \
    --output "$work_dir/timed.json"
~~~~

The exporter's supplied `recording_id` is a label, not verification. Check it
against the cache entry's source and the selected track before proceeding.
Review automatically classified credit rows; unusual metadata or sung text can
need reclassification. The exporter uses SQLite `mode=ro`, not `LyricsCache.get`,
which can update access times.

Prepare `proofread.json` from the user's supplied text in that same directory,
then run:

~~~~fish
uv run --locked python -B "$work_dir/align_proofread.py" \
    "$work_dir/proofread.json" "$work_dir/timed.json" "$work_dir/result"
open "$work_dir/result/timed-proofread.md"
~~~~

The output directory must be new; an existing review is never overwritten.
Save the temporary inputs/results elsewhere if the user wants to retain them.

### Read-only cache exporter

```python
# export_timing_cache.py
"""Export one selected cache entry without updating access times or annotations."""
import argparse
import json
from pathlib import Path
import re
import sqlite3

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--key")
parser.add_argument("--recording-id")
parser.add_argument("--output", type=Path)
args = parser.parse_args()
path = Path.home() / "Library/Application Support/Lyrics Pro/lyrics-cache.sqlite3"
with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
    if not args.key:
        for key, payload in db.execute(
                "SELECT key, payload FROM recordings ORDER BY accessed DESC LIMIT 20"):
            data = json.loads(payload)
            print(json.dumps({"key": key, "source": data["source"],
                              "synced": data["synced"], "rows": len(data["lines"])},
                             ensure_ascii=False))
    else:
        if not args.recording_id or not args.output:
            parser.error("--key requires --recording-id and --output")
        result = db.execute("SELECT payload FROM recordings WHERE key=?", (args.key,)).fetchone()
        if result is None:
            raise SystemExit("Cache key not found")
        data = json.loads(result[0])
        if not data["synced"] or data.get("instrumental"):
            raise SystemExit("Need timed, non-instrumental lyrics")
        lines = []
        for row in data["lines"]:
            text = row["text"]
            kind = ("gap" if not text.strip() else
                    "credit" if re.match(r"^(作[词詞曲]|[编編]曲|[制製]作人)\s*[:：]", text)
                    else "lyric")
            lines.append({"time": row["time"], "text": text, "kind": kind})
        output = {"recording_id": args.recording_id, "source": data["source"],
                  "cache_key": args.key, "lines": lines}
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
```

### Offline alignment prototype

The script performs no network requests, playback operations, or cache writes.
It uses supplied JSON snapshots and writes only to its new output directory.
The caps (200 blocks / 500 source rows) are prototype bounds for individual songs.

```python
# align_proofread.py
"""Offline review prototype. Does not modify Lyrics Pro or its cache."""
import argparse
from collections import Counter
from difflib import SequenceMatcher
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata

from taibun import to_traditional

THRESHOLD = 0.70  # Exploratory candidate threshold, NOT an accuracy confidence.
EPS = 1e-9


def norm(text):
    text = to_traditional(unicodedata.normalize("NFKC", text)).casefold()
    return "".join(c for c in text if c.isalnum())


def compact(text):
    return re.sub(r"\s+", "", text)


def reading_key(text):
    return "".join(c for c in unicodedata.normalize("NFC", text)
                   if not c.isspace() and not unicodedata.category(c).startswith("P"))


def similarity(a, b):
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def distance(a, b):
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def validate(manual, timed):
    if not manual.get("recording_id") or manual["recording_id"] != timed.get("recording_id"):
        raise ValueError("Both inputs must identify the same selected recording")
    blocks, rows = manual["blocks"], timed["lines"]
    if not 0 < len(blocks) <= 200 or not 0 < len(rows) <= 500:
        raise ValueError("Prototype limit: 200 proofread blocks / 500 timing rows")
    ids = set()
    for block in blocks:
        if not isinstance(block.get("id"), str) or block["id"] in ids:
            raise ValueError("Manual block IDs must be unique strings")
        ids.add(block["id"])
        for field in ("text", "spelling"):
            if not isinstance(block.get(field), str) or not block[field].strip():
                raise ValueError("Each manual block needs text and spelling")
            if len(block[field]) > 2000:
                raise ValueError("Split oversized input into reviewable blocks")
        if not norm(block["text"]):
            raise ValueError("Manual text cannot consist only of punctuation")
        parts = block.get("parts")
        if parts is not None:
            if len(parts) != 2:
                raise ValueError("This prototype supports exactly two explicit parts")
            for field in ("text", "spelling"):
                if any(not isinstance(p.get(field), str) or not p[field].strip()
                       for p in parts):
                    raise ValueError("Both parts need text and spelling")
                if compact("".join(p[field] for p in parts)) != compact(block[field]):
                    raise ValueError("Parts must preserve all supplied characters")
    last = -1
    for row in rows:
        stamp = row.get("time")
        if type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp < 0 or stamp < last:
            raise ValueError("Timestamps must be finite, nonnegative, and ordered")
        if not isinstance(row.get("text"), str):
            raise ValueError("Timing rows need text")
        if row.get("kind", "lyric") not in ("lyric", "credit", "gap"):
            raise ValueError("Invalid timing row kind")
        if row.get("kind") == "gap" and row["text"].strip():
            raise ValueError("A gap must have empty text")
        last = stamp


def align(manual, timed):
    validate(manual, timed)
    repeats, verse_blocks = {}, []
    for block in manual["blocks"]:
        key = norm(block["text"])
        if block.get("repeat", False):
            if key in repeats and reading_key(repeats[key]["spelling"]) != reading_key(block["spelling"]):
                raise ValueError("Conflicting spellings for a reusable repeat")
            repeats.setdefault(key, block)  # First supplied equivalent is canonical.
        else:
            verse_blocks.append(block)

    events, verse_rows, used_repeats = [], [], set()
    for i, source in enumerate(timed["lines"]):
        text = source["text"]
        kind = source.get("kind", "lyric") if text.strip() else "gap"
        event = dict(source_row=i, time=source["time"], online_text=text,
                     match_text=text, text=None, spelling=None, manual_id=None,
                     status="unresolved", review=[])
        if kind in ("gap", "credit"):
            event.update(text=text, spelling="", status=kind)
        elif norm(text) in repeats:
            block = repeats[norm(text)]
            event.update(text=block["text"], spelling=block["spelling"],
                         manual_id=block["id"], status="repeat", similarity=1.0)
            used_repeats.add(norm(text))
        else:
            for prefix in manual.get("backing_prefixes", []):
                if prefix and text.startswith(prefix):
                    event["match_text"] = text[len(prefix):]
                    event["review"].append("backing_vocals_omitted")
                    break
            verse_rows.append(event)
        events.append(event)

    # Monotonic dynamic programming. Keep source row order, including repeated verses.
    n, m = len(verse_blocks), len(verse_rows)
    costs = {(0, 0): 0.0}
    previous, ways = {}, {(0, 0): 1}
    for i in range(n + 1):
        for j in range(m + 1):
            if (i, j) not in costs:
                continue
            choices = []
            if i < n:
                choices.append((i + 1, j, len(norm(verse_blocks[i]["text"])),
                                ("skip_manual", i, j, 0)))
            if j < m:
                choices.append((i, j + 1, len(norm(verse_rows[j]["match_text"])),
                                ("skip_online", i, j, 1)))
            if i < n:
                a = norm(verse_blocks[i]["text"])
                for count in (1, 2):
                    if j + count > m:
                        continue
                    b = "".join(norm(r["match_text"]) for r in verse_rows[j:j + count])
                    if similarity(a, b) >= THRESHOLD:
                        choices.append((i + 1, j + count,
                                        distance(a, b) + 0.01 * (count - 1),
                                        ("match", i, j, count)))
            for ii, jj, delta, action in choices:
                state, value = (ii, jj), costs[i, j] + delta
                if value < costs.get(state, float("inf")) - EPS:
                    costs[state] = value
                    previous[state] = ((i, j), action)
                    ways[state] = ways[i, j]
                elif abs(value - costs.get(state, float("inf"))) <= EPS:
                    # Deterministic first path remains; ambiguity is not hidden.
                    ways[state] = min(2, ways[state] + ways[i, j])

    path, state = [], (n, m)
    while state != (0, 0):
        state, action = previous[state]
        path.append(action)
    path.reverse()
    unmatched_manual, boundaries = [], []
    ambiguous = ways[n, m] > 1
    for kind, i, j, count in path:
        if kind == "skip_manual":
            unmatched_manual.append(verse_blocks[i]["id"])
            continue
        if kind == "skip_online":
            verse_rows[j]["review"].append("no_manual_match")
            continue
        block = verse_blocks[i]
        rows = verse_rows[j:j + count]
        if count == 2 and not block.get("parts"):
            for row in rows:
                row["review"].append("needs_explicit_text_and_spelling_split")
                row["candidate_manual_id"] = block["id"]
            unmatched_manual.append(block["id"])
            continue
        fragments = block["parts"] if count == 2 else [block]
        for fragment, row in zip(fragments, rows):
            a, b = norm(fragment["text"]), norm(row["match_text"])
            row.update(text=fragment["text"], spelling=fragment["spelling"],
                       manual_id=block["id"], status="exact" if a == b else "approximate",
                       similarity=round(similarity(a, b), 6))
            if a != b:
                row["review"].append("approximate_text_match")
            if ambiguous:
                row["review"].append("ambiguous_sequence_alignment")

    # Detect a phrase that the manual puts at the end of the preceding row.
    for left, right in zip(events, events[1:]):
        if left["status"] not in ("exact", "approximate") or right["status"] not in ("exact", "approximate"):
            continue
        a, b = norm(left["text"]), norm(right["match_text"])
        for width in range(min(6, len(a), len(b)), 1, -1):
            if a[-width:] == b[:width] and not norm(left["match_text"]).endswith(a[-width:]):
                boundaries.append(dict(source_rows=[left["source_row"], right["source_row"]],
                                       phrase=a[-width:]))
                left["review"].append("phrase_crosses_source_boundary")
                right["review"].append("phrase_crosses_source_boundary")
                break

    assert len(events) == len(timed["lines"])
    assert [r["time"] for r in events] == [r["time"] for r in timed["lines"]]
    lyric_events = [r for r in events if r["status"] not in ("gap", "credit")]
    return {
        "recording_id": timed["recording_id"],
        "timing_source": timed.get("source"),
        "manual_source": manual.get("source"),
        "audio_verified": False,
        "candidate_threshold": THRESHOLD,
        "ambiguous_sequence_alignment": ambiguous,
        "summary": dict(Counter(r["status"] for r in events)),
        "review_row_count": sum(bool(r["review"]) for r in lyric_events),
        "unmatched_manual_ids": unmatched_manual,
        "unused_repeat_ids": [b["id"] for b in manual["blocks"]
                              if b.get("repeat") and norm(b["text"]) not in used_repeats],
        "duplicate_timestamp_values": [t for t, c in Counter(r["time"] for r in events).items() if c > 1],
        "boundary_warnings": boundaries,
        "rows": events,
    }


def timestamp(seconds):
    ticks = round(seconds * 100)
    minutes, remainder = divmod(ticks, 6000)
    sec, centisec = divmod(remainder, 100)
    return f"{minutes:02d}:{sec:02d}.{centisec:02d}"


def markdown(report):
    out = ["# Timed proofread lyrics — candidate",
           "", "Not audio-verified. See the review notes and alignment.json.", "",
           "~~~~text"]
    for row in report["rows"]:
        if row["status"] == "credit":
            continue
        stamp = timestamp(row["time"])
        if row["status"] == "gap":
            out.extend([f"[{stamp}]", ""])
        elif row["status"] == "unresolved":
            out.extend([f"[{stamp}] [UNRESOLVED — source row {row['source_row']}]",
                        "[SPELLING UNRESOLVED]", ""])
        else:
            out.extend([f"[{stamp}] {row['text']}", row["spelling"], ""])
    out.extend(["~~~~", "", "## Review notes", ""])
    notes = False
    for row in report["rows"]:
        if row["review"]:
            notes = True
            out.append(f"- {timestamp(row['time'])}, source row {row['source_row']}: "
                       + ", ".join(row["review"]))
    if report["unmatched_manual_ids"]:
        notes = True
        out.append("- Unmatched manual blocks: " + ", ".join(report["unmatched_manual_ids"]))
    if report["unused_repeat_ids"]:
        notes = True
        out.append("- Unused reusable blocks: " + ", ".join(report["unused_repeat_ids"]))
    if report["duplicate_timestamp_values"]:
        notes = True
        out.append("- Duplicate timestamps: inspect alignment.json; none were discarded.")
    if not notes:
        out.append("- No structural warnings; listening verification is still required.")
    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manual", type=Path)
    parser.add_argument("timed", type=Path)
    parser.add_argument("output", type=Path, help="New output directory, outside the repository")
    args = parser.parse_args()
    manual_bytes, timed_bytes = args.manual.read_bytes(), args.timed.read_bytes()
    report = align(json.loads(manual_bytes), json.loads(timed_bytes))
    report["input_sha256"] = {
        "manual": hashlib.sha256(manual_bytes).hexdigest(),
        "timed": hashlib.sha256(timed_bytes).hexdigest(),
    }
    # Refuse to overwrite an earlier review.
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "alignment.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8")
    (args.output / "timed-proofread.md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    print(f"Review rows: {report['review_row_count']}; audio_verified=false")


if __name__ == "__main__":
    main()
```

## Output and listening review

`timed-proofread.md` places the source timestamp beside the proofread text and
the associated spelling on the next line. It includes empty timestamps for
musical gaps. Review flags are in a separate section, not inserted into lyrics.

~~~~text
[mm:ss.xx] Proofread lyrics
Associated spelling
~~~~

`alignment.json` retains input hashes, provider/recording identity, original
online text, manual block IDs, matching scores/status, omitted backing-vocal
flags, unresolved content, duplicate timestamps, and boundary warnings.
The status `exact` means matching normalized foreground text, not audio approval.
`repeat` means reuse of an explicitly supplied passage, not a new transcription.
`audio_verified` remains false until a person has checked the recording; this
prototype does not change it.

Before presenting a result:

- Confirm output row count, ordering, and numeric timestamps match the timing
  input exactly. Duplicate timestamps remain present for review.
- Confirm all resolved text and spelling came from supplied whole blocks or
  explicit parts; no language engine generated replacement readings.
- Account for all unresolved online rows and unmatched manual blocks. Do not
  hide placeholders when exporting a listening candidate.
- Preserve gaps and list omitted backing vocals. Phrase-boundary warnings need
  listening review even when adjacent text matches strongly.
- Check the actual chosen recording. This method inherits provider timing errors,
  including a constant lyric delay; text matching cannot repair those errors.

For a fresh source, freeze the fetched result before repeating the test.
An input change requires a new alignment/review, not reusing a previous result.
No app build, release, or repository integration is part of this workflow.

## Reference experiment: 少年吔，安啦！

The user supplied 30 paired lyric/spelling blocks from
[台客鬼's transcription](https://taikegui.wordpress.com/2017/04/28/少年吔，安啦/),
crediting 關德樂 for romanization. The timing snapshot came from
[NetEase recording 5237870](https://music.163.com/song?id=5237870).
The selected Apple Music track was Wu Bai, album 愛你伍佰年:1, duration approximately
413.786 seconds. These details identify the experiment, not every release of the song.

To reproduce its alignment with those same inputs:

- Keep all 30 supplied blocks in sequence; mark the six chorus blocks reusable.
- Supply two explicit lyric/spelling parts for blocks 1, 2, 4, and 5, following
  the original paired columns. Do not split the other multi-phrase blocks.
- Explicitly identify the parenthesized chorus prefix in three late online rows
  as backing vocals absent from the user's foreground transcription.
- Classify the three initial metadata rows as credits and the six blank rows as
  musical-gap events.

Observed result:

| Observation | Result |
|---|---:|
| Online rows, including metadata and gaps | 58 |
| Timestamped sung candidates | 49 |
| Exact normalized foreground matches | 15 |
| Expanded chorus occurrences | 21 |
| Approximate matches | 13 |
| Musical-gap events retained | 6 |
| Rows with omitted backing vocals | 3 |

The 13 approximate timestamps were 00:26.92, 01:12.42, 01:23.28, 01:43.73,
02:04.05, 02:34.29, 02:40.73, 03:02.00, 03:07.03, 03:40.86, 04:00.23,
05:22.08, and 05:28.58. Backing-vocal omissions were at 05:09.08, 05:15.43,
and 05:22.08; these overlap the approximate set, so review counts are not additive.

The phrase at the end of supplied block 28 occurs at the start of the following
online row. Preserve the supplied grouping, but flag blocks 28 and 29: 05:28.58
may precede the actual onset of block 29. No finer onset was measured or invented.

This was a local text-alignment feasibility test, not audio verification. The
49-row result is not a general accuracy benchmark. Current provider data may
differ; compare input hashes before expecting identical output.
