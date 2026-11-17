import * as OpenCC from "opencc-js";
import type { FoldTable } from "./fold";

// Character-by-character (not phrase) conversion, so the browser can repeat it with a plain table.
// Taiwan → mainland is nearly lossless one character at a time: traditional → simplified is mostly many-to-one.
export const toSimplified = OpenCC.Converter({ from: "tw", to: "cn" });

/** Traditional → simplified for every Han character in `text` that converts differently. */
export function simplifiedTable(text: string): FoldTable {
  const table: FoldTable = {};
  for (const character of new Set(text)) {
    if (!/\p{Script=Han}/u.test(character)) continue;
    const simplified = toSimplified(character);
    if (simplified !== character) table[character] = simplified;
  }
  return table;
}
