"""Audit a completed preparation run without network or Music access."""
import argparse
from collections import Counter
import json
from pathlib import Path

from lyrics_pro.curated import _decode_asset
from scripts.prepare_proofread import digest, promotable


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(source=Path("resources/lyrics-spelling"), output=Path("resources/proofread-preparation"),
           assets=Path("src/lyrics_pro/data/proofread")):
    manifest = json.loads((output / "manifest.json").read_text())
    entries = manifest["inputs"]
    by_path = {entry["path"]: entry for entry in entries}
    expected = {str(path) for path in source.iterdir() if path.is_file()}
    require(len(by_path) == len(entries) == manifest["input_count"], "Duplicate/missing manifest input")
    require(set(by_path) == expected, "Manifest does not cover every raw source")
    require(dict(Counter(e["status"] for e in entries)) == manifest["summary"], "Incorrect status counts")
    prepared = 0
    ready = set()
    for entry in entries:
        raw = Path(entry["path"]).read_bytes()
        require(digest(raw) == entry["sha256"], f"Changed source: {entry['path']}")
        if entry["status"] == "duplicate":
            original = Path(entry["duplicate_of"]).read_text()
            require(" ".join(raw.decode("utf-8-sig").split()) == " ".join(original.split()), "Invalid duplicate")
            require(entry["duplicate_of"] in by_path, "Missing duplicate target")
            continue
        if entry.get("asset_id") == "shao-nian-eh-an-la":
            _decode_asset((assets / "shao-nian-eh-an-la.json").read_bytes())
            ready.add(entry["asset_id"])
            continue
        directory = output / entry["id"]
        if "report" not in entry:
            require(entry["status"] != "ready", "Ready input has no alignment")
            continue
        report = json.loads((directory / "alignment.json").read_text())
        timed = json.loads((directory / "timed.json").read_text())
        manual = json.loads((directory / "proofread.json").read_text())
        prepared += 1
        require(report["audio_verified"] is False, "Unexpected audio-verification claim")
        for name in ("manual", "timed"):
            filename = "proofread.json" if name == "manual" else "timed.json"
            require(digest((directory / filename).read_bytes()) == report["input_sha256"][name], "Input hash mismatch")
        require(report["input_sha256"]["original_source"] == entry["sha256"], "Raw input hash mismatch")
        require([r["time"] for r in report["rows"]] == [r["time"] for r in timed["lines"]], "Source timing changed")
        require([r["online_text"] for r in report["rows"]] == [r["text"] for r in timed["lines"]], "Source order changed")
        if entry["status"] != "ready":
            continue
        require(promotable(report, entry["duration"]), "Unreviewed alignment marked ready")
        blocks = {f"{b['id']}:{i}": p for b in manual["blocks"] for i, p in enumerate(b.get("parts") or [b])}
        for row in report["rows"]:
            if row["status"] in ("gap", "credit"):
                continue
            assigned = [blocks[key] for key in row["manual_id"].split("+")]
            for field in ("text", "spelling"):
                require(row[field] == " ".join(b[field] for b in assigned), "Unsupplied text or spelling")
        payload = (directory / "asset.json").read_bytes()
        _decode_asset(payload)
        require((assets / (entry["asset_id"] + ".json")).read_bytes() == payload, "Bundled asset differs from audited proposal")
        ready.add(entry["asset_id"])
    bundled = [_decode_asset(p.read_bytes()) for p in assets.glob("*.json")]
    reviewed_root = source / "wubai-reviewed"
    if (reviewed_root / "manifest.json").exists():
        from scripts.prepare_wubai import audit
        ready.update(audit(reviewed_root, assets))
    require(len({r.reference for r in bundled}) == len(bundled), "Duplicate asset identity")
    require({r.lyrics.proofread.asset_id for r in bundled} == ready, "Bundled assets and manifest disagree")
    return dict(inputs=len(entries), prepared_timelines=prepared, bundled_assets=len(ready), summary=manifest["summary"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("resources/lyrics-spelling"))
    parser.add_argument("--output", type=Path, default=Path("resources/proofread-preparation"))
    args = parser.parse_args()
    print(json.dumps(verify(args.input, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
