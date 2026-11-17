import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { artistPath, byArtist, CatalogError, checkPaths, legacyPaths, loadSongs, REPOSITORY, type Song, songPath } from "./catalog";

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
    expect(checkPaths(songs)).toBe(songs);
    const segment = "[a-z0-9]+(-[a-z0-9]+)*";
    expect(songs.every((song) => new RegExp(`^/songs/${segment}/${segment}/$`).test(songPath(song)))).toBe(true);
    expect(artistPath("伍佰")).toBe("/artists/wu-bai/");
  });
});

describe("page paths", () => {
  const song = (id: string, title: string, artist: string): Song => ({ id, title, artist, file: "", source: "" });

  it("nests songs under their artist, so shared titles do not clash", () => {
    const list = [song("a", "日子", "滅火器"), song("b", "日子", "謝銘祐")];
    expect(checkPaths(list).map(songPath)).toEqual(["/songs/mie-huo-qi/ri-zi/", "/songs/xie-ming-you/ri-zi/"]);
  });

  it("fails on clashing or empty paths", () => {
    expect(() => checkPaths([song("a", "莎喲娜啦", "A"), song("b", "莎喲娜拉", "A")])).toThrow(/sha-yo-na-la.*莎喲娜啦 – A, 莎喲娜拉 – A/);
    expect(() => checkPaths([song("a", "ㄟ", "A")])).toThrow(CatalogError);
  });

  it("maps the hashed artist and manifest ID paths to the pinyin ones", () => {
    const hash = createHash("sha256").update("伍佰").digest("hex").slice(0, 12);
    expect(legacyPaths([song("supplied-1", "台灣製造", "伍佰")])).toEqual([
      [`/artists/${hash}/`, "/artists/wu-bai/"],
      ["/songs/supplied-1/", "/songs/wu-bai/tai-wan-zhi-zao/"],
    ]);
  });
});
