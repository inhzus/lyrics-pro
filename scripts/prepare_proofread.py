"""Offline, resumable preparation of supplied transcriptions; never runs in the app.

Run: uv run --locked python -m scripts.prepare_proofread --help
Network snapshots stay in .build; review artifacts are written separately.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import re
import signal
from threading import Event
import time

from taibun import to_simplified, to_traditional

from lyrics_pro import lyrics as providers
from lyrics_pro.curated import _decode_asset
from lyrics_pro.models import LookupCancelled, LookupFailure, Playback
from lyrics_pro.pronunciation import HAN, normalize
from scripts.proofread_alignment import align, markdown, reading_key

VERSION = 8
CREDIT = re.compile(r"^(?:作[詞词曲]|[詞词曲]|編曲|编曲|製作人?|制作人?|演唱|原唱|"
                    r"吉他|貝斯|贝斯|混音|錄音|录音|母帶|母带|和聲|和声|"
                    r"詞曲|词曲|Lyricist|Composer|Arranger)\s*[:：]", re.I)
HEADER = re.compile(r"^(?:作[詞词曲]\s*[:：]|(?:詞曲|词曲|[詞词曲])\s*[:：]|(?:台羅|台語|客語)拼音\s*[:：])")
NAMED_CREDIT_HEADER = re.compile(r"^作詞\s+[^：]+\s*：\s*作曲\s+[^：]+\s*：\s*台語拼音\s*：.+$")
NOTE = re.compile(r"^(?:Note\s*:|註\s*[:：]|注\s*[:：]|備註\s*[:：])", re.I)
COLUMNS = re.compile(r"[\t\u3000 ]{2,}")


def digest(value):
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def metadata(name):
    title, separator, artist = name.rpartition("-")
    reasons = []
    if not separator or not title.strip() or not artist.strip():
        return name, "", ["filename_needs_title_and_artist"]
    # Strip an explicit track prefix, never a numeric song title (9453, 8+9).
    title = re.sub(r"^\d{1,2}\s+[－–—-]\s+", "", title).strip()
    duplicate = re.fullmatch(r"(.+)-\d{1,2}-(.+)", title)
    if duplicate and normalize(duplicate[1]) == normalize(duplicate[2]):
        title = duplicate[2]
    elif re.search(r"-\d{1,2}-", title):
        reasons.append("ambiguous_track_number_in_title")
    if re.match(re.escape(artist.strip()) + r"\s*(?:\([^)]*\))?\s+[–—－]\s+", title):
        reasons.append("artist_prefix_in_title_requires_override")
    return title, artist.strip(), reasons


def parse_transcription(text):
    """No synthesized text/readings. Every nonempty line is paired or reported."""
    body, credits, notes, reasons = [], [], [], []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if HEADER.match(line) or NAMED_CREDIT_HEADER.fullmatch(line):
            credits.append(dict(line=number, text=line))
        elif NOTE.match(line):
            notes.append(dict(line=number, text=line))
            # Notes can distinguish live/studio arrangements or explain omissions.
            reasons.append(f"source_note_requires_review:{number}")
        else:
            body.append((number, line))
    blocks = []
    cursor = 0
    while cursor < len(body):
        number, lyric = body[cursor]
        if cursor + 1 >= len(body):
            reasons.append(f"unpaired_line:{number}")
            break
        next_number, spelling = body[cursor + 1]
        if not HAN.search(lyric) or HAN.search(spelling):
            reasons.append(f"ambiguous_pair:{number},{next_number}")
            cursor += 1
            continue
        block = dict(id=f"line-{number}", text=lyric, spelling=spelling,
                     source_lines=[number, next_number])
        words, readings = COLUMNS.split(lyric), COLUMNS.split(spelling)
        if len(words) == len(readings) and len(words) > 1 and all(words + readings):
            block["parts"] = [dict(text=w, spelling=r) for w, r in zip(words, readings)]
        blocks.append(block)
        cursor += 2
    if not blocks:
        reasons.append("no_paired_lyrics")
    spellings = defaultdict(set)
    for block in blocks:
        spellings[normalize(block["text"])].add(reading_key(block["spelling"]))
    if any(len(values) > 1 for values in spellings.values()):
        reasons.append("conflicting_spellings_for_repeated_text")
    return dict(blocks=blocks, credits=credits, notes=notes, reasons=sorted(set(reasons)))


def strict_alignment(manual, timed):
    """Exact monotonic alignment with explicit columns and adjacent-block merges.

    Reuse only text present multiple times with identical supplied spelling.
    Complete exact paths are counted (capped at two); no arbitrary best-path
    decision can promote an ambiguous song. Approximate prototype is review-only.
    """
    blocks = []
    for block in manual["blocks"]:
        for index, part in enumerate(block.get("parts") or [block]):
            blocks.append(dict(part, id=f"{block['id']}:{index}"))
    if not 0 < len(blocks) <= 200 or not 0 < len(timed["lines"]) <= 500:
        raise ValueError("Preparation limit: 200 supplied fragments / 500 timing rows")
    previous = -1
    for row in timed["lines"]:
        stamp = row.get("time")
        if type(stamp) not in (float, int) or not math.isfinite(stamp) or stamp < previous or stamp < 0:
            raise ValueError("Timing input must be finite, nonnegative and ordered")
        previous = stamp
    keys = [normalize(b["text"]) for b in blocks]
    repeated = {key for key, count in Counter(keys).items() if count > 1}
    readings = defaultdict(set)
    for key, block in zip(keys, blocks):
        readings[key].add(reading_key(block["spelling"]))
    repeated = {key for key in repeated if len(readings[key]) == 1}
    canonical = {key: next(b for k, b in zip(keys, blocks) if k == key) for key in repeated}
    # Online providers sometimes put an entire repeated two-line refrain at one
    # timestamp. Reuse only groups actually adjacent in the supplied input.
    repeat_groups = {}
    conflicting_groups = set()
    for start in range(len(blocks)):
        group_key = ""
        for end in range(start, min(start + 6, len(blocks))):
            if keys[end] not in repeated:
                break
            group_key += keys[end]
            assigned = blocks[start:end + 1]
            group_reading = reading_key(" ".join(b["spelling"] for b in assigned))
            if group_key in repeat_groups:
                old = repeat_groups[group_key]
                if reading_key(" ".join(b["spelling"] for b in old)) != group_reading:
                    conflicting_groups.add(group_key)
            else:
                repeat_groups[group_key] = assigned
    verse = [(k, b) for k, b in zip(keys, blocks) if k not in repeated]
    events, targets, used = [], [], set()
    for index, source in enumerate(timed["lines"]):
        text = source["text"]
        kind = source.get("kind", "lyric") if text.strip() else "gap"
        event = dict(source_row=index, time=source["time"], online_text=text, match_text=text,
                     text=None, spelling=None, manual_id=None, status="unresolved", review=[])
        key = normalize(text)
        if kind in ("gap", "credit"):
            event.update(text=text, spelling="", status=kind)
        elif key in repeat_groups and key not in conflicting_groups:
            assigned = repeat_groups[key]
            event.update(text=" ".join(b["text"] for b in assigned),
                         spelling=" ".join(b["spelling"] for b in assigned),
                         manual_id="+".join(b["id"] for b in assigned),
                         status="repeat", similarity=1.0)
            used.update(normalize(b["text"]) for b in assigned)
        else:
            targets.append((key, event))
        events.append(event)
    # Each target consumes 1..6 adjacent supplied blocks. Groups never cross a
    # removed repeat: its source position remains an explicit boundary.
    positions = {b["id"]: i for i, b in enumerate(blocks)}
    paths = {(0, 0): (1, [])}
    for j, (target, _) in enumerate(targets):
        for i in range(len(verse)):
            if (i, j) not in paths:
                continue
            count, path = paths[i, j]
            merged = ""
            for end in range(i, min(i + 6, len(verse))):
                if end > i and positions[verse[end][1]["id"]] != positions[verse[end-1][1]["id"]] + 1:
                    break
                merged += verse[end][0]
                if merged == target:
                    state = (end + 1, j + 1)
                    old = paths.get(state)
                    paths[state] = (min(2, count + (old[0] if old else 0)),
                                    old[1] if old else path + [(i, end + 1)])
                if len(merged) >= len(target):
                    break
    complete = paths.get((len(verse), len(targets)))
    if not complete:
        # The documented experiment still provides useful review candidates.
        # Its two-column limit is respected by expanding explicitly paired parts.
        fallback = dict(manual, blocks=[dict(b, repeat=normalize(b["text"]) in repeated) for b in blocks])
        report = align(fallback, timed)
        report["strict_complete"] = False
        return report
    count, path = complete
    for (_, event), (start, end) in zip(targets, path):
        assigned = [b for _, b in verse[start:end]]
        event.update(text=" ".join(b["text"] for b in assigned),
                     spelling=" ".join(b["spelling"] for b in assigned),
                     manual_id="+".join(b["id"] for b in assigned), status="exact", similarity=1.0)
    return dict(recording_id=timed["recording_id"], timing_source=timed["source"],
                manual_source=manual.get("source"), audio_verified=False, strict_complete=True,
                ambiguous_sequence_alignment=count > 1, summary=dict(Counter(e["status"] for e in events)),
                review_row_count=0, unmatched_manual_ids=[],
                unused_repeat_ids=[canonical[key]["id"] for key in sorted(repeated - used)],
                duplicate_timestamp_values=[t for t, c in Counter(e["time"] for e in events).items() if c > 1],
                boundary_warnings=[], rows=events)


def promotable(report, duration):
    return (report.get("strict_complete") is True and not report["ambiguous_sequence_alignment"]
            and not report["unmatched_manual_ids"] and not report["unused_repeat_ids"]
            and not report["boundary_warnings"] and not report["review_row_count"]
            and not report["duplicate_timestamp_values"]
            and any(r["status"] in ("exact", "repeat") for r in report["rows"])
            and all(r["status"] in ("exact", "repeat", "gap", "credit")
                    and 0 <= r["time"] <= duration for r in report["rows"]))


def alignment_score(manual, report):
    """Prefer a complete review candidate over a tiny exact lyric fragment."""
    atoms = {f"{b['id']}:{i}": (normalize(p["text"]), reading_key(p["spelling"]))
             for b in manual["blocks"] for i, p in enumerate(b.get("parts") or [b])}
    supplied = set(atoms.values())
    sung = [row for row in report["rows"] if row["status"] not in ("gap", "credit")]
    resolved = [row for row in sung if row["status"] in ("exact", "approximate", "repeat")]
    covered = {atoms[key] for row in resolved for key in (row["manual_id"] or "").split("+") if key in atoms}
    manual_coverage = sum(len(key[0]) for key in covered) / max(1, sum(len(key[0]) for key in supplied))
    coverage = min(manual_coverage, len(resolved) / max(1, len(sung)))
    exact_fraction = sum(row["status"] in ("exact", "repeat") for row in sung) / max(1, len(sung))
    return coverage, exact_fraction


class Snapshots:
    """Sequential, cancellable requests, at least one second apart; frozen success."""
    def __init__(self, root, cancelled=None, retry=False, *, offline=False):
        self.root = Path(root)
        self.cancelled = cancelled or Event()
        self.retry = retry
        self.offline = offline
        self.last = 0.0
        self.trace = {}

    def unchanged(self, saved):
        if not isinstance(saved, dict) or saved.get("root") != str(self.root):
            return False
        for key, expected in saved.get("requests", {}).items():
            if not re.fullmatch(r"[a-f0-9]{64}", key):
                return False
            path = self.root / (key + ".json")
            actual = digest(path.read_bytes()) if path.exists() else None
            if actual != expected:
                return False
        return True

    def check(self):
        if self.cancelled.is_set():
            raise LookupCancelled("Preparation cancelled; completed results were saved.")

    def request(self, provider, endpoint, params):
        self.check()
        key = digest(json.dumps([provider, endpoint, params], sort_keys=True, ensure_ascii=False))
        path = self.root / (key + ".json")
        self.trace[key] = digest(path.read_bytes()) if path.exists() else None
        if path.exists():
            saved = json.loads(path.read_text())
            if "response" in saved:
                return saved["response"]
            if not self.retry:
                raise LookupFailure(saved["error"], retryable=saved.get("retryable", False))
        if self.offline:
            raise LookupFailure(f"No usable frozen {provider} snapshot for {endpoint}; offline mode forbids requests.")
        error = None
        for attempt in range(3):
            if self.cancelled.wait(max(0, 1 - (time.monotonic() - self.last))):
                self.check()
            self.check()
            self.last = time.monotonic()
            try:
                if provider == "netease":
                    response = providers.request_json(endpoint, params, self.cancelled)
                elif provider == "lrcapi":
                    response = providers.LrcAPIProvider(cancelled=self.cancelled).request(params)
                else:
                    response = providers.lrclib_request_json(endpoint, params, self.cancelled)
                write_json(path, dict(provider=provider, endpoint=endpoint, params=params,
                                     fetched_at=time.time(), response=response))
                self.trace[key] = digest(path.read_bytes())
                return response
            except LookupCancelled:
                raise
            except LookupFailure as caught:
                error = caught
                if not error.retryable or attempt == 2:
                    break
                if self.cancelled.wait(2 ** attempt):
                    self.check()
        write_json(path, dict(provider=provider, endpoint=endpoint, params=params,
                             fetched_at=time.time(), error=str(error), retryable=error.retryable))
        self.trace[key] = digest(path.read_bytes())
        raise error


def discover(title, artist, snapshots):
    """Discover duration from catalog metadata; never guess a Playback duration."""
    errors, evidence = [], []
    for provider in ("netease", "lrcapi", "lrclib"):
        found = {}
        titles = list(dict.fromkeys((to_simplified(title), title, to_traditional(title))))
        queries = (list(dict.fromkeys((f"{to_simplified(title)} {to_simplified(artist)}", f"{title} {artist}", title)))
                   if provider == "netease" else titles)
        try:
            for query in queries:
                if provider == "netease":
                    response = snapshots.request(provider, "search/get",
                        {"s": query, "type": 1, "limit": 30})
                    records = providers.response_items(response, "songs", search=True)[:30]
                    candidate_fn = providers.candidate_from_record
                elif provider == "lrcapi":
                    records = snapshots.request(provider, "jsonapi", {"title": query, "artist": artist, "album": ""}) or []
                    candidate_fn = providers.LrcAPIProvider.candidate
                else:
                    records = snapshots.request(provider, "search", {"track_name": query}) or []
                    candidate_fn = providers.lrclib_candidate
                if not isinstance(records, list):
                    raise LookupFailure(f"{provider}: invalid candidate list", retryable=True)
                for record in records[:20 if provider == "lrclib" else 30]:
                    if not isinstance(record, dict):
                        continue
                    candidate = candidate_fn(record)
                    if not candidate or normalize(candidate.title) != normalize(title):
                        continue
                    candidate = replace(candidate, provider=provider)
                    verified = providers.credits_match(candidate.artists, artist)
                    evidence.append(dict(asdict(candidate), verified_artist=verified))
                    if verified:
                        found.setdefault(candidate.reference, (candidate, record))
                if found:
                    break
            results = []
            # Provider order is authoritative. Inspect no more than 3 recordings.
            for candidate, record in list(found.values())[:3]:
                if provider == "netease":
                    payload = snapshots.request(provider, "song/lyric", {"id": candidate.song_id, "lv": -1, "kv": -1, "tv": -1})
                    raw = providers.decode_record(payload, candidate.song_id) if payload else None
                elif provider == "lrcapi":
                    track = Playback("paused", title, artist, candidate.album, candidate.duration)
                    raw = providers.LrcAPIProvider.decode(candidate, record, track)
                else:
                    raw = providers.decode_lrclib(record, candidate.song_id)
                if raw and raw.synced and raw.lines:
                    timed = dict(recording_id=candidate.reference, source=raw.source,
                        lines=[dict(time=line.time, text=line.text,
                                    kind="gap" if not line.text.strip() else "credit" if CREDIT.match(line.text) else "lyric")
                               for line in raw.lines])
                    results.append((candidate, timed))
            if results:
                return results, evidence, errors
        except LookupCancelled:
            raise
        except LookupFailure as error:
            errors.append(dict(provider=provider, error=str(error), retryable=error.retryable))
    return [], evidence, errors


def process(path, output, snapshots, accepted=None, override=None):
    raw = path.read_bytes()
    sha = digest(raw)
    title, artist, metadata_reasons = metadata(path.name)
    override = override or {}
    if override:
        if set(override) - {"title", "artist"} or any(not isinstance(v, str) or not v.strip() for v in override.values()):
            raise ValueError(f"Invalid title/artist override for {path.name}")
        title, artist = override.get("title", title), override.get("artist", artist)
        if "title" in override and artist:
            metadata_reasons = []
    asset_id = "supplied-" + digest(path.name)[:20]
    directory = output / asset_id
    parsed = parse_transcription(raw.decode("utf-8-sig"))
    result = dict(path=str(path), sha256=sha, id=asset_id, title=title, artist=artist,
                  attribution=parsed["credits"], audio_verified=False, tool_version=VERSION,
                  metadata_override=override)
    if accepted:
        return result | dict(status="ready", asset_id=accepted, reasons=["previously_accepted_asset_preserved"])
    write_json(directory / "parsed.json", parsed)
    reasons = metadata_reasons + parsed["reasons"]
    if reasons:
        return result | dict(status="parsing review", reasons=reasons)
    recordings, candidates, errors = discover(title, artist, snapshots)
    write_json(directory / "recordings.json", dict(candidates=candidates, errors=errors))
    if not recordings:
        status = "lookup failure" if errors else "recording review" if any(not c["verified_artist"] for c in candidates) else "no timed lyrics"
        return result | dict(status=status, reasons=errors or ["no_verified_timed_recording"])
    proposals = []
    for candidate, timed in recordings:
        snapshots.check()
        manual = dict(recording_id=candidate.reference, source="User-supplied " + str(path), blocks=parsed["blocks"])
        try:
            report = strict_alignment(manual, timed)
        except ValueError as error:
            write_json(directory / "rejected-timing.json", timed)
            return result | dict(status="alignment review", reasons=[str(error)], recording_id=candidate.reference)
        report["input_sha256"] = dict(original_source=sha)
        ready = promotable(report, candidate.duration)
        score = alignment_score(manual, report)
        proposals.append((ready, score, candidate, timed, manual, report))
    proposals.sort(key=lambda p: (not p[0], -p[1][0], -p[1][1], p[2].reference))
    ready, _, candidate, timed, manual, report = proposals[0]
    equivalent = lambda p: [(r["time"], normalize(r["text"])) for r in p[3]["lines"]]
    tied = [p for p in proposals if p[:2] == proposals[0][:2]]
    conflict = any(equivalent(p) != equivalent(proposals[0]) or abs(p[2].duration - candidate.duration) > 2 for p in tied)
    write_json(directory / "proofread.json", manual)
    write_json(directory / "timed.json", timed)
    report["input_sha256"].update(manual=digest((directory / "proofread.json").read_bytes()),
                                  timed=digest((directory / "timed.json").read_bytes()))
    write_json(directory / "alignment.json", report)
    write_json(directory / "selection.json", dict(selected=asdict(candidate), conflicting_top_candidates=conflict,
        candidates=[dict(recording_id=p[2].reference, duration=p[2].duration, ready=p[0],
                         coverage=p[1][0], exact_fraction=p[1][1],
                         summary=p[5]["summary"]) for p in proposals]))
    (directory / "timed-proofread.md").write_text(markdown(report))
    result.update(recording_id=candidate.reference, duration=candidate.duration, summary=report["summary"],
                  report=str(directory / "alignment.json"))
    if conflict:
        return result | dict(status="recording review", reasons=["conflicting_equally_supported_timings"])
    if not ready:
        blockers = {
            "approximate_rows": report["summary"].get("approximate", 0),
            "unresolved_rows": report["summary"].get("unresolved", 0),
            "unmatched_supplied_blocks": len(report["unmatched_manual_ids"]),
            "unused_repeat_blocks": len(report["unused_repeat_ids"]),
            "ambiguous_sequence": int(report["ambiguous_sequence_alignment"]),
            "boundary_warnings": len(report["boundary_warnings"]),
            "duplicate_timestamps": len(report["duplicate_timestamp_values"]),
            "timestamps_outside_duration": sum(not 0 <= r["time"] <= candidate.duration for r in report["rows"]),
        }
        reasons = [f"{key}:{count}" for key, count in blockers.items() if count]
        return result | dict(status="alignment review", reasons=reasons or ["no_complete_exact_alignment"])
    asset = dict(schema_version=1, id=asset_id, revision="1", title=title, artist=artist, album=candidate.album,
                 duration=candidate.duration, language="supplied", attribution="User-provided transcription. " +
                 " / ".join(c["text"] for c in parsed["credits"]), alignment=report)
    _decode_asset(json.dumps(asset, ensure_ascii=False))
    write_json(directory / "asset.json", asset)
    return result | dict(status="ready", asset_id=asset_id, reasons=[])


def promote(result, output, destination_root):
    """Never overwrite accepted assets or introduce ambiguous automatic matches."""
    if result["status"] != "ready" or result["asset_id"] == "shao-nian-eh-an-la":
        return result
    source = output / result["id"] / "asset.json"
    payload = source.read_bytes()
    candidate = _decode_asset(payload)
    destination = destination_root / (result["asset_id"] + ".json")
    for existing in destination_root.glob("*.json"):
        if existing == destination:
            if existing.read_bytes() != payload:
                return result | dict(status="recording review", reasons=["existing_asset_revision_requires_review"])
            continue
        recording = _decode_asset(existing.read_bytes())
        existing_titles = {normalize(t) for t in (recording.title, *recording.title_aliases)}
        proposed_titles = {normalize(t) for t in (candidate.title, *candidate.title_aliases)}
        if existing_titles & proposed_titles and abs(recording.duration - candidate.duration) <= 4:
            # Two +/-2 second match windows must not overlap.
            return result | dict(status="recording review", reasons=[f"overlapping_asset_match:{recording.reference}"])
    if not destination.exists():
        destination_root.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    return result


def summarize(output, entries):
    counts = dict(Counter(e["status"] for e in entries))
    write_json(output / "manifest.json", dict(schema_version=1, tool_version=VERSION,
        input_count=len(entries), audio_verified=False, summary=counts, inputs=entries))
    rows = ["# Supplied lyrics preparation", "", "No new alignment is audio-verified.", "",
            "| Status | Inputs |", "|---|---:|"]
    rows += [f"| {status} | {count} |" for status, count in sorted(counts.items())]
    rows += ["", "## Ready listening previews", ""]
    for entry in entries:
        if entry["status"] == "ready":
            preview = ("../lyrics-spelling/shao-nian-eh-an-la/timed-proofread.md"
                       if entry.get("asset_id") == "shao-nian-eh-an-la"
                       else entry["id"] + "/timed-proofread.md")
            rows.append(f"- [{entry['title']} — {entry['artist']}]({preview})")
    rows += ["", "See manifest.json for hashes, aliases and reasons; song directories contain frozen",
             "timing inputs, alignment reports and timestamped listening previews.", "",
             "| Source file | Status | Details |", "|---|---|---|"]
    for entry in entries:
        reason = "; ".join(str(r) for r in entry.get("reasons", []))
        label = Path(entry["path"]).name.replace("|", "\\|")
        if "report" in entry:
            reason = f"[Preview]({entry['id']}/timed-proofread.md). " + reason
        rows.append(f"| {label} | {entry['status']} | {reason.replace('|', '/')} |")
    (output / "README.md").write_text("\n".join(rows) + "\n")


def write_notices(assets, destination):
    lines = ["Bundled user-provided lyrics and corresponding spelling", "",
             "The application's MIT license applies to its code, not to song lyrics or",
             "transcriptions. Attribution does not grant redistribution rights to that content.",
             "Alignments retain provider timestamps and are not audio-verified.", ""]
    for path in sorted(assets.glob("*.json")):
        asset = json.loads(path.read_text())
        lines += [f"{asset['title']} — {asset['artist']}", f"Asset: proofread:{asset['id']}",
                  asset["attribution"].strip()]
        if asset["id"] == "shao-nian-eh-an-la":
            # Retain the full credits from the previously bundled content notice.
            lines.append("Words: 伍佰 / 陳世杰. Music: 伍佰. Romanization: 關德樂.")
        if asset.get("transcription_url"):
            lines.append("Transcription reference: " + asset["transcription_url"])
        lines += ["Timing: " + asset["alignment"]["timing_source"], ""]
    destination.write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("resources/lyrics-spelling"))
    parser.add_argument("--output", type=Path, default=Path("resources/proofread-preparation"))
    parser.add_argument("--snapshots", type=Path, default=Path(".build/proofread-snapshots"))
    parser.add_argument("--overrides", type=Path, default=Path("resources/proofread-metadata-overrides.json"),
                        help="Reviewed filename -> {title, artist} JSON mapping (defaults to the collection overrides)")
    parser.add_argument("--offline", action="store_true", help="Only use frozen responses; never make a network request")
    parser.add_argument("--retry", action="store_true", help="Revisit failed/review results; retain successful response snapshots")
    parser.add_argument("--promote", action="store_true", help="Copy only ready assets into the app; never overwrite an asset")
    parser.add_argument("--limit", type=int, help="Pilot: process this many inputs")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cancelled = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: cancelled.set())
    snapshots = Snapshots(args.snapshots, cancelled, args.retry, offline=args.offline)
    if not args.overrides.exists() and args.overrides != Path("resources/proofread-metadata-overrides.json"):
        parser.error(f"Missing metadata overrides: {args.overrides}")
    overrides = json.loads(args.overrides.read_text()) if args.overrides.exists() else {}
    if not isinstance(overrides, dict):
        parser.error("Overrides must be an object keyed by source filename")
    previous = {}
    manifest = args.output / "manifest.json"
    if manifest.exists():
        previous = {e["path"]: e for e in json.loads(manifest.read_text())["inputs"]}
    accepted_path = args.input / "少年吔，安啦-伍佰"
    accepted_hash = None
    accepted_asset = Path("src/lyrics_pro/data/proofread/shao-nian-eh-an-la.json")
    if accepted_path.exists() and accepted_asset.exists():
        pinned = json.loads(accepted_asset.read_text())["alignment"]["input_sha256"]["original"]
        if digest(accepted_path.read_bytes()) == pinned:
            accepted_hash = digest(" ".join(accepted_path.read_text().split()))
    entries, seen = [], {}
    paths = sorted(p for p in args.input.iterdir() if p.is_file())
    if args.limit:
        paths = paths[:args.limit]
    try:
        for index, path in enumerate(paths, 1):
            snapshots.check()
            content = path.read_bytes()
            sha, dedup = digest(content), digest(" ".join(content.decode("utf-8-sig").split()))
            old = previous.get(str(path))
            if dedup in seen:
                title, artist, _ = metadata(path.name)
                result = dict(path=str(path), sha256=sha, status="duplicate", duplicate_of=seen[dedup]["path"],
                              id=seen[dedup]["id"], title=title, artist=artist, attribution=seen[dedup]["attribution"],
                              reasons=["identical_transcription_after_whitespace_normalization"])
            elif (old and old["sha256"] == sha and old.get("tool_version") == VERSION
                  and old.get("metadata_override", {}) == overrides.get(path.name, {})
                  and snapshots.unchanged(old.get("snapshots"))
                  and (not args.retry or old["status"] == "ready")):
                result = old
            else:
                snapshots.trace = {}
                kwargs = dict(override=overrides[path.name]) if path.name in overrides else {}
                result = process(path, args.output, snapshots,
                                 "shao-nian-eh-an-la" if dedup == accepted_hash else None, **kwargs)
                result["snapshots"] = dict(root=str(snapshots.root), requests=dict(snapshots.trace))
            if args.promote:
                result = promote(result, args.output, Path("src/lyrics_pro/data/proofread"))
            seen.setdefault(dedup, result)
            entries.append(result)
            previous[str(path)] = result
            summarize(args.output, [previous[str(p)] for p in paths if str(p) in previous])
            print(f"{index}/{len(paths)} {result['status']}: {path.name}", flush=True)
    except LookupCancelled as error:
        print(str(error), flush=True)
        return 130
    if args.promote:
        write_notices(Path("src/lyrics_pro/data/proofread"), Path("packaging/Proofread-content.txt"))
    print(json.dumps(Counter(e["status"] for e in entries), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
