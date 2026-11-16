import * as OpenCC from "opencc-js";
import { romanize } from "./artists";
import { artistSlug, type Song } from "./catalog";
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

export type SearchHit = { href: string; title: string; meta: string; search: string };

/** Everything the home page search needs, served as /search.json: artists first, then songs. */
export function searchIndex(groups: [string, Song[]][]): { table: FoldTable; hits: SearchHit[] } {
  // Fold every searchable string first; the table is complete only afterwards.
  const { fold, table } = createFolder();
  const hits: SearchHit[] = groups.map(([artist, list]) => ({
    href: `/artists/${artistSlug(artist)}/`,
    title: artist,
    meta: `歌手 · ${list.length} 首`,
    search: fold(`${artist} ${romanize(artist)}`),
  }));
  for (const [, list] of groups) {
    for (const song of list) {
      hits.push({ href: `/songs/${song.id}/`, title: song.title, meta: song.artist, search: fold(`${song.title} ${song.artist}`) });
    }
  }
  return { table, hits };
}
