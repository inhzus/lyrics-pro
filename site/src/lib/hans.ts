import * as OpenCC from "opencc-js";
import type { FoldTable } from "./fold";

// Character-by-character (not phrase) conversion, so the browser can repeat it with a plain table.
// Taiwan → mainland is nearly lossless one character at a time: traditional → simplified is mostly many-to-one.
export const toSimplified = OpenCC.Converter({ from: "tw", to: "cn" });
const toTraditional = OpenCC.Converter({ from: "cn", to: "tw" });

/**
 * Traditional → simplified for every Han character in `text` that converts differently. A character
 * that is itself the simplified form of another (么, from 麼) is left out, so text that is already
 * simplified, such as rows cloned on a /hans/ page, comes out unchanged when converted again.
 */
export function simplifiedTable(text: string): FoldTable {
  const table: FoldTable = {};
  for (const character of new Set(text)) {
    if (!/\p{Script=Han}/u.test(character)) continue;
    const simplified = toSimplified(character);
    const already = toTraditional(character) !== character && toSimplified(toTraditional(character)) === character;
    if (simplified !== character && !already) table[character] = simplified;
  }
  return table;
}
