/** Code ranges of a CSS `unicode-range` value: `U+4E00`, `U+4E00-9FFF` or the wildcard `U+4??`. */
export function parseUnicodeRange(value: string): [number, number][] {
  return value.split(",").map((part) => {
    const token = part.trim().replace(/^u\+/i, "");
    const [low, high] = token.includes("-")
      ? token.split("-")
      : [token.replace(/\?/g, "0"), token.replace(/\?/g, "f")];
    return [parseInt(low, 16), parseInt(high, 16)];
  });
}

export function codePoints(texts: Iterable<string>) {
  const points = new Set<number>();
  for (const text of texts) for (const character of text) points.add(character.codePointAt(0)!);
  return points;
}

const hex = (point: number) => point.toString(16);

/** Sorted code points as a compact `unicode-range` value. */
export function formatUnicodeRange(points: number[]) {
  const parts: string[] = [];
  for (let start = 0; start < points.length; ) {
    let end = start;
    while (end + 1 < points.length && points[end + 1] === points[end] + 1) end++;
    parts.push(end === start ? `U+${hex(points[start])}` : `U+${hex(points[start])}-${hex(points[end])}`);
    start = end + 1;
  }
  return parts.join(", ");
}

/**
 * Narrows each `@font-face` rule's `unicode-range` to the characters in `used`, and drops
 * rules (with their leading comment) that cover none. Rules without a range stay unchanged.
 * The font files are untouched, so browsers still download only the slices a page needs.
 * The legacy WOFF fallback is removed: every browser the site targets loads WOFF2.
 */
export function keepUsedFaces(css: string, used: Set<number>) {
  const sorted = [...used].sort((a, b) => a - b);
  return css.replace(/(?:\/\*[^*]*\*\/\s*)?@font-face\s*\{[^}]*\}\s*/g, (rule) => {
    const range = /unicode-range:\s*([^;}]+)/i.exec(rule);
    if (!range) return rule;
    const ranges = parseUnicodeRange(range[1]);
    const covered = sorted.filter((point) => ranges.some(([low, high]) => point >= low && point <= high));
    if (!covered.length) return "";
    return rule
      .replace(range[1], formatUnicodeRange(covered))
      .replace(/,\s*url\([^)]*\.woff\)\s*format\(['"]woff['"]\)/, "");
  });
}
