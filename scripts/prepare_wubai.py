"""Reproduce explicitly reviewed Wu Bai assets offline; no matching heuristics.

Default writes reproducible previews/assets under the review directory.
--integrate also copies validated assets into the app, refusing changed content.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path

from lyrics_pro.curated import _decode_asset
from lyrics_pro.pronunciation import HAN, normalize
from lyrics_pro.recording_ref import source_ref
from scripts.prepare_proofread import digest, write_notices
from scripts.proofread_alignment import reading_key

ROOT = Path("resources/lyrics-spelling/wubai-reviewed")
ASSETS = Path("src/lyrics_pro/data/proofread")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def compact(value):
    return "".join(value.split())


def pair(block):
    return normalize(block["text"]), reading_key(block["spelling"])


def read_review(directory):
    review = json.loads((directory / "review.json").read_text())
    manual = json.loads((directory / "manual.json").read_text())
    timed = json.loads((directory / "timed.json").read_text())
    for name in ("manual", "timed"):
        require(digest((directory / (name + ".json")).read_bytes()) == review["input_sha256"][name],
                f"{directory}: changed {name} input")
    return review, manual, timed


def make_asset(review, manual, timed):
    """Validate explicit source fragments and assignments, never infer new ones."""
    raw = Path(review["source_path"]).read_bytes()
    require(digest(raw) == review["input_sha256"]["original"], "Changed original transcription")
    require(review["approved"] is True and review["audio_verified"] is False,
            "Missing explicit text review or unsupported audio-verification claim")
    require(review["recording"]["reference"] == timed["recording_id"] == source_ref(timed["source"]),
            "Timing provenance mismatch")
    lines = raw.decode("utf-8-sig").splitlines()
    for patch in manual.get("repairs", []):
        n, before, after = patch["line"], patch["before"], patch["after"]
        require(type(n) is int and 1 <= n <= len(lines) and before and patch.get("evidence"),
                "Repair needs a source line and evidence")
        require(lines[n-1].count(before) == 1, f"Repair does not match source line {n}")
        lines[n-1] = lines[n-1].replace(before, after, 1)
    atoms = {}
    for block in manual["blocks"]:
        source_lines = block["source_lines"]
        require(len(source_lines) == 2 and all(type(n) is int and 1 <= n <= len(lines) for n in source_lines),
                "Invalid transcription line reference")
        lyric_line, spelling_line = (lines[n-1] for n in source_lines)
        if source_lines[0] == source_lines[1]:
            if block.get("verbatim_latin"):
                require(not HAN.search(lyric_line) and block["text"] == block["spelling"] == lyric_line.strip(),
                        "Verbatim Latin text changed")
            else:
                require(compact(block["text"] + block["spelling"]) == compact(lyric_line),
                        "Inline words/spelling do not reproduce the source")
        else:
            require(compact(block["text"]) == compact(lyric_line)
                    and compact(block["spelling"]) == compact(spelling_line),
                    f"Unsupplied text/spelling at {block['id']}")
        parts = block.get("parts") or [block]
        for field in ("text", "spelling"):
            require(compact("".join(p[field] for p in parts)) == compact(block[field]),
                    f"Phrase split changed {field} at {block['id']}")
        for i, part in enumerate(parts):
            key = f"{block['id']}:{i}"
            require(key not in atoms and part["text"].strip() and part["spelling"].strip(),
                    "Duplicate or empty supplied fragment")
            atoms[key] = part
    assignments = review["assignments"]
    require(len(assignments) == len(timed["lines"]), "Missing or extra timing rows")
    require(len({r["time"] for r in timed["lines"]}) == len(timed["lines"]), "Ambiguous duplicate timestamps")
    used, rows = set(), []
    for index, (assignment, original) in enumerate(zip(assignments, timed["lines"])):
        require(assignment["source_row"] == index, "Reordered timing assignment")
        kind = assignment["kind"]
        if kind in ("credit", "gap"):
            require(not assignment.get("manual_ids"), "Nonsung event has a lyric assignment")
            require(original["kind"] == kind or assignment.get("reason"),
                    "Reclassified event lacks an explicit review decision")
            text, spelling = (original["text"] if kind == "credit" else ""), ""
            ids = []
        else:
            require(kind == "lyric" and original["kind"] not in ("gap", "credit"),
                    "Cannot replace a musical gap or credit with invented sung content")
            ids = assignment["manual_ids"]
            require(ids and all(i in atoms for i in ids), "Missing supplied fragment")
            text = " ".join(atoms[i]["text"] for i in ids)
            spelling = " ".join(atoms[i]["spelling"] for i in ids)
            used.update(ids)
            kind = "exact" if normalize(text) == normalize(original["text"]) else "approximate"
        rows.append(dict(source_row=index, time=original["time"], online_text=original["text"],
                         status=kind, text=text, spelling=spelling, manual_id="+".join(ids) or None,
                         review=[assignment["reason"]] if assignment.get("reason") else []))
    missing = {pair(p) for p in atoms.values()} - {pair(atoms[key]) for key in used}
    require(not missing, f"Unassigned supplied text/spelling: {missing}")
    recording = review["recording"]
    asset = dict(schema_version=1, id=review["id"], revision=review["revision"],
                 title=review["title"], title_aliases=review.get("title_aliases", []),
                 artist=recording.get("artist", "伍佰"), album=recording["album"],
                 duration=recording["duration"], language="hokkien", attribution=review["attribution"],
                 alignment=dict(recording_id=recording["reference"], timing_source=timed["source"],
                                manual_source=review["source_path"], audio_verified=False,
                                agent_review=review["reason"], input_sha256=review["input_sha256"],
                                source_spelling_notes=review.get("source_spelling_notes", []),
                                summary=dict(Counter(r["status"] for r in rows)), rows=rows))
    _decode_asset(json.dumps(asset, ensure_ascii=False))
    return asset


def preview(asset):
    report = asset["alignment"]
    result = [f"# {asset['title']} — reviewed alignment", "",
              f"Recording: {report['recording_id']} · {asset['album']} · {asset['duration']:.3f}s",
              "", "Provider timestamps preserved. Text alignment reviewed; not audio-verified.",
              "Supplied spelling is retained except for the documented source-backed repairs.", "",
              report["agent_review"], ""]
    result += [f"- Source spelling note: {note}" for note in report.get("source_spelling_notes", [])]
    result += ["", "~~~text"]
    for row in report["rows"]:
        minutes, seconds = divmod(row["time"], 60)
        result.append(f"[{int(minutes):02d}:{seconds:06.3f}] {row['text']}".rstrip())
        if row["spelling"]:
            result.append("    " + " ".join(row["spelling"].split()))
    return "\n".join(result + ["~~~", ""])


def index_text(catalog):
    counts = Counter(e["status"] for e in catalog["songs"])
    result = ["# Reviewed Wu Bai collection", "",
              f"{len(catalog['songs'])} distinct supplied songs: {counts['ready']} newly adapted, "
              f"{counts['existing']} previously accepted, {counts['needs timing']} awaiting reliable timing.",
              "The three duplicate raw files remain accounted for in the original preparation manifest.", "",
              "These are reviewed text alignments, not listening-verified pronunciation or onset corrections.",
              "Original transcripts are unchanged. Each folder preserves the selected online timeline,",
              "explicit phrase assignments, source-backed repairs, input hashes, and a listening preview.",
              "Automatic playback requires a reviewed title/alias and duration within two seconds;",
              "artist and album describe provenance. Explicit online recording choices remain online lyrics.", "",
              "## Reproduce", "", "Run from the repository root:", "", "~~~fish",
              "uv run --locked python -m scripts.prepare_wubai --check",
              "uv run --locked python -m scripts.prepare_wubai --integrate", "~~~", "",
              "Both commands are offline. The first checks bundled outputs; the second recreates and",
              "integrates reviewed outputs, refusing to overwrite a different existing asset.", "",
              "## Outstanding timing", ""]
    for e in catalog["songs"]:
        if e["status"] == "needs timing":
            result += [f"- **{e['title']}**: {e['reason']}"]
    result += ["", "## Source spelling and version notes", ""]
    for e in catalog["songs"]:
        for note in e.get("source_spelling_notes", []):
            result += [f"- **{e['title']}**: {note}"]
    result += ["", "## Listening previews", "", "| Song | Recording | Duration | Status |",
               "|---|---|---:|---|"]
    for e in catalog["songs"]:
        r = e.get("recording", {})
        title = e["title"]
        if e["status"] == "ready":
            title = f"[{title}]({e['id']}/timed-proofread.md)"
        elif e["status"] == "existing":
            title = f"[{title}](../shao-nian-eh-an-la/timed-proofread.md)"
        duration = f"{r['duration']:.3f}s" if r else "—"
        result.append(f"| {title} | {r.get('reference', '—')} · {r.get('album', '')} | {duration} | {e['status']} |")
    return "\n".join(result) + "\n"


def audit(root=ROOT, assets=ASSETS, *, write=False, integrate=False):
    catalog = json.loads((root / "manifest.json").read_text())
    require(catalog["schema_version"] == 1, "Invalid reviewed catalog")
    original = json.loads(Path("resources/proofread-preparation/manifest.json").read_text())
    expected = {e["path"] for e in original["inputs"] if e["artist"] == "伍佰" and e["status"] != "duplicate"}
    require({e["source_path"] for e in catalog["songs"]} == expected, "Reviewed catalog misses a Wu Bai source")
    identities, ready, payloads = set(), set(), {}
    for entry in catalog["songs"]:
        require(entry["id"] not in identities, "Duplicate reviewed song")
        identities.add(entry["id"])
        require(digest(Path(entry["source_path"]).read_bytes()) == entry["source_sha256"],
                "Changed catalog source")
        if entry["status"] == "existing":
            payload = (assets / (entry["asset_id"] + ".json")).read_bytes()
            require(digest(payload) == entry["asset_sha256"], "Previously accepted asset changed")
            continue
        if entry["status"] != "ready":
            require(entry["status"] == "needs timing" and entry.get("reason"), "Invalid unresolved entry")
            continue
        directory = root / entry["id"]
        review, manual, timed = read_review(directory)
        require(review["id"] == entry["id"] and review["source_path"] == entry["source_path"]
                and review["input_sha256"]["original"] == entry["source_sha256"],
                "Review and catalog disagree")
        asset = make_asset(review, manual, timed)
        payload = (json.dumps(asset, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
        payloads[asset["id"]] = payload
        ready.add(asset["id"])
        if not write:
            require((directory / "asset.json").read_bytes() == payload, "Stale generated asset")
            require((directory / "timed-proofread.md").read_text() == preview(asset), "Stale preview")
            require((assets / (asset["id"] + ".json")).read_bytes() == payload, "Bundle differs from reviewed asset")
    # Check the whole batch before writing, including collisions with existing assets.
    decoded = {p.stem: _decode_asset(p.read_bytes()) for p in assets.glob("*.json")}
    for identity, payload in payloads.items():
        destination = assets / (identity + ".json")
        if destination.exists():
            require(destination.read_bytes() == payload, "Existing asset revision requires explicit review")
        decoded[identity] = _decode_asset(payload)
    recordings = list(decoded.values())
    for i, a in enumerate(recordings):
        titles = {normalize(t) for t in (a.title, *a.title_aliases)}
        for b in recordings[i+1:]:
            overlap = titles & {normalize(t) for t in (b.title, *b.title_aliases)}
            require(not overlap or abs(a.duration-b.duration) > 4, "Overlapping proofread match windows")
    if write:
        for identity, payload in payloads.items():
            directory = root / identity
            (directory / "asset.json").write_bytes(payload)
            (directory / "timed-proofread.md").write_text(preview(json.loads(payload)))
            if integrate:
                (assets / (identity + ".json")).write_bytes(payload)
        if integrate:
            write_notices(assets, Path("packaging/Proofread-content.txt"))
        (root / "README.md").write_text(index_text(catalog))
    else:
        require((root / "README.md").read_text() == index_text(catalog), "Stale review index")
    return ready


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify generated and bundled outputs without writes")
    parser.add_argument("--integrate", action="store_true", help="Bundle explicitly reviewed results")
    args = parser.parse_args()
    if args.check and args.integrate:
        parser.error("--check and --integrate are mutually exclusive")
    ready = audit(write=not args.check, integrate=args.integrate)
    print(f"Validated {len(ready)} reviewed assets; original accepted asset preserved.")


if __name__ == "__main__":
    main()
