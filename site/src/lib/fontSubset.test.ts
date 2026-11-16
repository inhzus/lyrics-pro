import { describe, expect, it } from "vitest";
import { codePoints, formatUnicodeRange, keepUsedFaces, parseUnicodeRange } from "./fontSubset";

const face = (name: string, range: string) =>
  `/* ${name} */\n@font-face {\n  font-family: 'Noto Serif TC';\n  src: url(./files/${name}.woff2) format('woff2'), url(./files/${name}.woff) format('woff');\n  unicode-range: ${range};\n}\n`;

describe("font slices", () => {
  it("parses single values, ranges and wildcards", () => {
    expect(parseUnicodeRange("U+4E00, u+3000-303f, U+4??")).toEqual([
      [0x4e00, 0x4e00],
      [0x3000, 0x303f],
      [0x400, 0x4ff],
    ]);
  });

  it("keeps only rules covering a used character", () => {
    const css = face("han", "U+5e97-5e98, U+8336") + face("kana", "U+3040-309f") + face("latin", "U+0000-00ff");
    const kept = keepUsedFaces(css, codePoints(["茶店仔", "Tâi-lô"]));
    expect(kept).toContain("han.woff2");
    expect(kept).toContain("latin.woff2");
    expect(kept).not.toContain("kana");
    expect(kept).toContain("unicode-range: U+5e97, U+8336;");
    expect(kept).not.toContain(".woff)");
  });

  it("formats sorted points as single values and runs", () => {
    expect(formatUnicodeRange([0x2d, 0x54, 0x61, 0x62, 0x63])).toBe("U+2d, U+54, U+61-63");
  });

  it("drops every CJK rule for an ASCII-only site but keeps rules without a range", () => {
    const css = face("han", "U+4e00-9fff") + "@font-face { font-family: x; src: url(x.woff2); }";
    expect(keepUsedFaces(css, codePoints(["Hello"]))).toBe("@font-face { font-family: x; src: url(x.woff2); }");
  });
});
