import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { artistSlug, byArtist, CatalogError, loadSongs, REPOSITORY } from "./catalog";

const SOURCES = "resources/lyrics-spelling";
const MANIFEST = "resources/proofread-preparation/manifest.json";

function fixture(files: Record<string, string>, statuses: Record<string, string> = {}) {
  const root = mkdtempSync(join(tmpdir(), "lyrics-site-"));
  mkdirSync(join(root, SOURCES), { recursive: true });
  mkdirSync(join(root, SOURCES, "reviewed-subdirectory"));
  mkdirSync(join(root, "resources/proofread-preparation"), { recursive: true });
  const inputs = Object.entries(files).map(([name, body], index) => {
    writeFileSync(join(root, SOURCES, name), body);
    const [title, artist] = name.split("-");
    return {
      path: `${SOURCES}/${name}`,
      sha256: createHash("sha256").update(body).digest("hex"),
      id: `supplied-${index}`,
      title,
      artist,
      status: statuses[name] ?? "ready",
    };
  });
  writeFileSync(join(root, MANIFEST), JSON.stringify({ inputs }));
  return root;
}

describe("loadSongs", () => {
  it("skips duplicates and sorts by artist then title", () => {
    const root = fixture({ "乙歌-B": "乙\nit\n", "甲歌-A": "甲\nkah\n", "副本-A": "甲\nkah\n" }, { "副本-A": "duplicate" });
    const { songs, duplicates } = loadSongs(root);
    expect(duplicates).toBe(1);
    expect(songs.map((song) => [song.artist, song.title, song.file])).toEqual([
      ["A", "甲歌", "甲歌-A"],
      ["B", "乙歌", "乙歌-B"],
    ]);
    expect(byArtist(songs).map(([artist, list]) => [artist, list.length])).toEqual([["A", 1], ["B", 1]]);
  });

  it.each(["edit", "extra", "missing"])("fails when the manifest is stale (%s)", (change) => {
    const root = fixture({ "歌-甲": "歌\nkua\n" });
    const path = join(root, SOURCES, "歌-甲");
    if (change === "edit") writeFileSync(path, "改\nkái\n");
    if (change === "extra") writeFileSync(join(root, SOURCES, "新-乙"), "新\nsin\n");
    if (change === "missing") unlinkSync(path);
    expect(() => loadSongs(root)).toThrow(CatalogError);
    expect(() => loadSongs(root)).toThrow(/rerun scripts\.prepare_proofread/);
  });

  it("loads the repository catalog", () => {
    const manifest = JSON.parse(readFileSync(join(REPOSITORY, MANIFEST), "utf8"));
    const expected = manifest.inputs.filter((entry: { status: string }) => entry.status !== "duplicate").length;
    const { songs, duplicates } = loadSongs();
    expect(songs).toHaveLength(expected);
    expect(duplicates).toBe(manifest.inputs.length - expected);
    expect(new Set(songs.map((song) => song.id)).size).toBe(songs.length);
    const artists = byArtist(songs).map(([artist]) => artist);
    expect(new Set(artists.map(artistSlug)).size).toBe(artists.length);
    expect(artists.map(artistSlug).every((slug) => /^[0-9a-f]{12}$/.test(slug))).toBe(true);
  });
});
