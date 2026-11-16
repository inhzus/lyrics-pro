import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { basename, join, resolve } from "node:path";
import { compareSongs } from "./artists";

// Builds and tests run from site/; Astro bundles this module, so import.meta.url is not stable.
export const REPOSITORY = resolve(process.cwd(), "..");
const SOURCES = "resources/lyrics-spelling";
const MANIFEST = "resources/proofread-preparation/manifest.json";

type Entry = { path: string; sha256: string; id: string; title: string; artist: string; status: string };
export type Song = { id: string; title: string; artist: string; file: string; source: string };

export class CatalogError extends Error {}

/** Publishable songs from the preparation manifest; every raw source must match its recorded hash. */
export function loadSongs(root = REPOSITORY): { songs: Song[]; duplicates: number } {
  const manifest: { inputs: Entry[] } = JSON.parse(readFileSync(join(root, MANIFEST), "utf8"));
  const listed = new Map(manifest.inputs.map((entry) => [basename(entry.path), entry]));
  const directory = join(root, SOURCES);
  const present = new Set(readdirSync(directory).filter(
    (name) => !name.startsWith(".") && statSync(join(directory, name)).isFile()));
  const problems: string[] = [];
  for (const name of [...present].sort()) if (!listed.has(name)) problems.push(`not in manifest: ${name}`);
  const songs: Song[] = [];
  let duplicates = 0;
  for (const [name, entry] of [...listed].sort(([a], [b]) => (a < b ? -1 : 1))) {
    const path = join(directory, name);
    if (!present.has(name) || !existsSync(path)) {
      problems.push(`missing source: ${name}`);
      continue;
    }
    const raw = readFileSync(path);
    if (createHash("sha256").update(raw).digest("hex") !== entry.sha256) {
      problems.push(`changed since preparation: ${name}`);
    } else if (entry.status === "duplicate") {
      duplicates++;
    } else {
      songs.push({ id: entry.id, title: entry.title, artist: entry.artist, file: name, source: raw.toString("utf8") });
    }
  }
  if (problems.length) {
    throw new CatalogError(
      `The manifest is out of date; rerun scripts.prepare_proofread first.\n  ${problems.join("\n  ")}`);
  }
  songs.sort((a, b) => compare(a.artist, b.artist) || compare(a.title, b.title) || compare(a.id, b.id));
  return { songs, duplicates };
}

const compare = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

let cached: Song[] | undefined;
/** Every page uses this order: artist, then title, by romanization (see artists.ts). */
export const songs = () => (cached ??= loadSongs().songs.sort(compareSongs));

/** Stable ASCII path segment; artist names contain spaces, "&" and parentheses. */
export const artistSlug = (artist: string) => createHash("sha256").update(artist).digest("hex").slice(0, 12);

export function byArtist(list: Song[]): [string, Song[]][] {
  const groups = new Map<string, Song[]>();
  for (const song of list) groups.set(song.artist, [...(groups.get(song.artist) ?? []), song]);
  return [...groups];
}
