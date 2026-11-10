from dataclasses import replace
from functools import lru_cache
import re
import unicodedata

from taibun import Converter, to_traditional

from .models import Lyrics


HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U000323af]+")


def normalize(text: str) -> str:
    text = to_traditional(unicodedata.normalize("NFKC", text)).casefold()
    return "".join(char for char in text if char.isalnum())


ALIASES = {
    normalize(name): group
    for group, names in {
        "eason": ("陳奕迅", "Eason Chan", "Chan, Eason", "Eason Chan (陳奕迅)"),
        "wubai": ("伍佰", "Wu Bai", "伍佰 & China Blue", "Wu Bai & China Blue", "China Blue"),
    }.items()
    for name in names
}


def artist_key(artist: str) -> str:
    normalized = normalize(artist)
    return ALIASES.get(normalized, normalized)


def choose_language(artist: str, requested: str) -> tuple[str | None, str]:
    if requested != "auto":
        return requested, "explicit override"
    language = {"eason": "cantonese", "wubai": "hokkien"}.get(artist_key(artist))
    return language, "artist-based guess" if language else "unknown language"


class Romanizer:
    def __init__(self):
        self._hokkien = None

    @lru_cache(maxsize=4096)
    def line(self, text: str, language: str) -> str:
        if not HAN.search(text):
            return text
        if language == "cantonese":
            import ToJyutping

            # Convert the full line to retain context for polyphonic characters.
            # The API returns character-level readings for either Chinese script.
            parts: list[str] = []
            previous_reading = False
            for character, reading in ToJyutping.get_jyutping_list(text):
                is_reading = bool(reading) or bool(HAN.search(character))
                rendered = reading or (f"[{character}: ?]" if is_reading else character)
                if not rendered:
                    continue
                if parts:
                    # Separate syllables and adjoining Latin words, but preserve
                    # punctuation, existing whitespace, and non-Han text runs.
                    if ((is_reading and (previous_reading or parts[-1][-1].isalnum()))
                            or (previous_reading and character[0].isalnum())):
                        parts.append(" ")
                parts.append(rendered)
                previous_reading = is_reading
            return "".join(parts)
        if language == "hokkien":
            if self._hokkien is None:
                self._hokkien = Converter(
                    system="Tailo", dialect="south", format="number",
                    sandhi="none", punctuation="none",
                )
            converted = self._hokkien.get(text)
            return HAN.sub(lambda match: f"[{match.group()}: ?]", converted)
        raise ValueError(f"Unsupported language: {language}")

    def annotate(self, lyrics: Lyrics, language: str | None) -> Lyrics:
        if language is None:
            return lyrics
        return replace(lyrics, lines=tuple(
            replace(line, pronunciation=self.line(line.text, language))
            for line in lyrics.lines
        ))
