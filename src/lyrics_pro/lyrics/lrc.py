"""LRC parsing shared by every online provider."""

import re

from ..models import LyricLine


STAMP = re.compile(r"\[(\d+):([0-5]\d)(?:[.:](\d{1,3}))?\]")
OFFSET = re.compile(r"\[offset:\s*([+-]?\d+)\]", re.IGNORECASE)
TAGS_ONLY = re.compile(r"(?:\[[^\]]*\]\s*)+")


def parse_lrc(text: str) -> tuple[LyricLine, ...]:
    offsets = OFFSET.findall(text)
    offset = int(offsets[-1]) / 1000 if offsets else 0
    entries: dict[float, list[str]] = {}
    for raw in text.splitlines():
        stamps = list(STAMP.finditer(raw))
        if not stamps or raw[:stamps[0].start()].strip():
            continue
        words = raw[stamps[-1].end():].strip()
        for stamp in stamps:
            minutes, seconds, fraction = stamp.groups()
            # Positive LRC offsets advance lyrics relative to the audio clock.
            time = max(0, int(minutes) * 60 + int(seconds) +
                       (float("0." + fraction) if fraction else 0) - offset)
            group = entries.setdefault(time, [])
            if words not in group:
                group.append(words)
    return tuple(LyricLine(" / ".join(filter(None, words)), time)
                 for time, words in sorted(entries.items()))


def has_text(lines: tuple[LyricLine, ...]) -> bool:
    return any(line.text for line in lines)


def plain_lines(text: str) -> tuple[LyricLine, ...]:
    """Untimed lines, skipping metadata tags and empty timestamped entries."""
    return tuple(LyricLine(line) for raw in text.splitlines()
                 if (line := raw.strip()) and not TAGS_ONLY.fullmatch(line))
