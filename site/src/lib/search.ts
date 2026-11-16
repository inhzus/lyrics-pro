import * as OpenCC from "opencc-js";
import { type FoldTable, foldWith } from "./fold";

// Character-by-character (not phrase) conversion, so the browser can repeat it with a plain table.
const toSimplified = OpenCC.Converter({ from: "tw", to: "cn" });

/**
 * Folds searchable text to simplified characters and records every mapping it used.
 * Ship `table` to the page after folding all the text: it then holds every traditional
 * character that can appear in a match, so traditional, simplified and mixed queries agree.
 */
export function createFolder() {
  const table: FoldTable = {};
  const fold = (text: string) => {
    for (const character of new Set(text.toLowerCase())) {
      if (!(character in table)) {
        const simplified = toSimplified(character);
        if (simplified !== character) table[character] = simplified;
      }
    }
    return foldWith(table, text);
  };
  return { fold, table };
}
