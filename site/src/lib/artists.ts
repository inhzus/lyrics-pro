import { pinyin } from "pinyin-pro";
import type { Song } from "./catalog";

const romanized = new Map<string, string>();

/** Mandarin pinyin without tones, used only for grouping and ordering (never displayed). */
export function romanize(name: string) {
  let value = romanized.get(name);
  if (value === undefined) {
    value = pinyin(name, { toneType: "none", nonZh: "consecutive", v: true }).replace(/\s+/g, " ").trim().toLowerCase();
    romanized.set(name, value);
  }
  return value;
}

const byRomanization = (a: string, b: string) =>
  romanize(a).localeCompare(romanize(b), "en") || a.localeCompare(b, "zh-Hant");

/** Artist, then title, each by romanization; the manifest id breaks exact ties. */
export const compareSongs = (a: Song, b: Song) =>
  byRomanization(a.artist, b.artist) || byRomanization(a.title, b.title) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);

export const initial = (name: string) => {
  const letter = romanize(name).charAt(0).toUpperCase();
  return /^[A-Z]$/.test(letter) ? letter : "#";
};

/** Artist groups bucketed by romanized initial: A–Z, then "#" for anything else. */
export function byInitial(groups: [string, Song[]][]): [string, [string, Song[]][]][] {
  const keyed = groups.map((group) => ({ group, letter: initial(group[0]) }));
  keyed.sort((a, b) => byRomanization(a.group[0], b.group[0]));
  const letters = new Map<string, [string, Song[]][]>();
  for (const { group, letter } of keyed) letters.set(letter, [...(letters.get(letter) ?? []), group]);
  return [...letters].sort(([a], [b]) => (a === "#" ? 1 : b === "#" ? -1 : a.localeCompare(b)));
}
