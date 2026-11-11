# align_proofread.py
"""Offline review prototype. Does not modify Lyrics Pro or its cache."""
import argparse
from collections import Counter
from difflib import SequenceMatcher
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata

from taibun import to_traditional

THRESHOLD = 0.70  # Exploratory candidate threshold, NOT an accuracy confidence.
EPS = 1e-9


@lru_cache(maxsize=4096)
def norm(text):
    text = to_traditional(unicodedata.normalize("NFKC", text)).casefold()
    return "".join(c for c in text if c.isalnum())


def compact(text):
    return re.sub(r"\s+", "", text)


def reading_key(text):
    return "".join(c for c in unicodedata.normalize("NFC", text)
                   if not c.isspace() and not unicodedata.category(c).startswith("P"))


@lru_cache(maxsize=4096)
def similarity(a, b):
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


@lru_cache(maxsize=4096)
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
