import { pinyin } from "pinyin-pro";

/**
 * Readings pinyin-pro gets wrong in this catalog, replaced before conversion (longest first).
 * Its default for 車 is the chess reading jū; the others are Taiwanese spellings it has no
 * better guess for.
 */
const READINGS: Record<string, string> = {
  樂團: "yue tuan",
  樂師: "yue shi",
  車: "che",
  嘸: "m",
  妳: "ni",
  咁: "gan",
  麼: "me",
};
const PATTERN = new RegExp(Object.keys(READINGS).sort((a, b) => b.length - a.length).join("|"), "g");

/**
 * URL path segment: toneless Mandarin pinyin, ü as v, Latin and digits kept, everything else a
 * single "-". Characters with no romanization (bopomofo, kana) drop out. Never displayed.
 */
export function slugify(text: string) {
  const replaced = text.replace(PATTERN, (match) => ` ${READINGS[match]} `);
  return pinyin(replaced, { toneType: "none", nonZh: "consecutive", v: true })
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/['’]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

/**
 * Song titles drop bracketed English names and featured-artist credits, e.g.
 * 心內話 (Bottom of My Heart) → xin-nei-hua, 等待 (ft.甲子慧) → deng-dai.
 */
export function titleSlug(title: string) {
  const short = title
    .replace(/\s*[(（](?:feat\.|ft\.|with\s)[^()（）]*[)）]/giu, "")
    .replace(/\s*[(（][^()（）\p{Script=Han}]*[)）]/gu, "");
  return slugify(short) || slugify(title);
}
