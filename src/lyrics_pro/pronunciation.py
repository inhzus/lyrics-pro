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


# Credits that name one artist. Each key is a stable identity (saved song
# preferences use it); the first name is the native one Chinese services index.
ARTIST_GROUPS = {
    "eason": ("陳奕迅", "Eason Chan", "Chan, Eason", "Eason Chan (陳奕迅)"),
    "wubai": ("伍佰", "Wu Bai", "伍佰 & China Blue", "Wu Bai & China Blue", "China Blue"),
}
ALIASES = {normalize(name): group for group, names in ARTIST_GROUPS.items() for name in names}


def artist_key(artist: str) -> str:
    normalized = normalize(artist)
    return ALIASES.get(normalized, normalized)


def native_name(artist: str) -> str | None:
    """The native-script name for a known artist credit, if any."""
    group = ARTIST_GROUPS.get(artist_key(artist))
    return group[0] if group else None


def choose_language(artist: str, requested: str, lyrics: Lyrics | None = None) -> tuple[str | None, str]:
    """Explicit terminal language; artist metadata never guesses pronunciation."""
    if requested == "original":
        return None, "original lyrics only"
    if requested in {"cantonese", "hokkien"}:
        return requested, "explicit override"
    raise ValueError("Choose cantonese, hokkien or original")


def resolve_language(global_language: str, song_language="default", lyrics: Lyrics | None = None):
    if song_language != "default":
        return choose_language("", song_language)[0], "song preference"
    if lyrics and lyrics.proofread:
        return lyrics.proofread.language, "proofread transcription"
    return choose_language("", global_language)[0], "global default"


def supplied_annotation(lyrics: Lyrics, language: str | None) -> Lyrics | None:
    """Return an authoritative presentation, or None when an engine is needed."""
    if language is None:
        if not any(line.pronunciation is not None for line in lyrics.lines):
            return lyrics
        return replace(lyrics, lines=tuple(replace(line, pronunciation=None) for line in lyrics.lines))
    if lyrics.proofread and language == lyrics.proofread.language:
        return lyrics
    if lyrics.instrumental:
        return lyrics
    return None


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
        supplied = supplied_annotation(lyrics, language)
        if supplied is not None:
            return supplied
        return replace(lyrics, lines=tuple(
            replace(line, pronunciation=self.line(line.text, language))
            for line in lyrics.lines
        ))
