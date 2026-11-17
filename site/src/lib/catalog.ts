import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { basename, join, resolve } from "node:path";
import { compareSongs } from "./artists";
import { slugify, titleSlug } from "./slug";

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
export const songs = () => (cached ??= checkPaths(loadSongs().songs).sort(compareSongs));

/** Pinyin path segments (slug.ts); a title or artist correction changes them. */
export const artistSlug = (artist: string) => slugify(artist);
export const artistPath = (artist: string) => `/artists/${artistSlug(artist)}/`;
export const songPath = (song: Song) => `/songs/${artistSlug(song.artist)}/${titleSlug(song.title)}/`;

/** Fails rather than letting two pages share a URL, or a name romanize to nothing. */
export function checkPaths(list: Song[]): Song[] {
  const owners = new Map<string, Set<string>>();
  const claim = (path: string, name: string) => owners.set(path, (owners.get(path) ?? new Set()).add(name));
  for (const song of list) {
    claim(artistPath(song.artist), song.artist);
    claim(songPath(song), `${song.title} – ${song.artist}`);
  }
  const problems = [...owners]
    .filter(([path, names]) => names.size > 1 || path.includes("//"))
    .map(([path, names]) => `${path}: ${[...names].join(", ")}`);
  if (problems.length) {
    throw new CatalogError(`Page paths must be unique and nonempty; add a reading in site/src/lib/slug.ts.\n  ${problems.join("\n  ")}`);
  }
  return list;
}

/** Pre-pinyin page paths (hashed artist names, manifest song IDs) and where they moved. */
export function legacyPaths(list: Song[]): [string, string][] {
  const moved = new Map<string, string>();
  for (const song of list) {
    moved.set(`/artists/${createHash("sha256").update(song.artist).digest("hex").slice(0, 12)}/`, artistPath(song.artist));
    moved.set(`/songs/${song.id}/`, songPath(song));
  }
  return [...moved];
}

export function byArtist(list: Song[]): [string, Song[]][] {
  const groups = new Map<string, Song[]>();
  for (const song of list) groups.set(song.artist, [...(groups.get(song.artist) ?? []), song]);
  return [...groups];
}
