import { describe, expect, it } from "vitest";
import { foldWith } from "./fold";
import type { Song } from "./catalog";
import { createFolder, searchIndex } from "./search";

describe("search folding", () => {
  it("matches traditional, simplified and mixed queries against folded titles", () => {
    const { fold, table } = createFolder();
    const titles = ["島嶼天光", "臺灣味", "KISS ME (星星知我心)"].map(fold);
    const matches = (query: string) => titles.filter((title) => title.includes(foldWith(table, query)));
    expect(matches("岛屿天光")).toEqual(["岛屿天光"]);
    expect(matches("島屿")).toEqual(["岛屿天光"]);
    expect(matches("台湾")).toEqual(["台湾味"]);
    expect(matches("臺灣")).toEqual(["台湾味"]);
    expect(matches("kiss")).toHaveLength(1);
  });

  it("ships only characters that change", () => {
    const { fold, table } = createFolder();
    fold("天光 Ripple 島");
    expect(table).toEqual({ 島: "岛" });
  });
});

describe("search index", () => {
  const song = (id: string, title: string, artist: string): Song => ({ id, title, artist, file: "", source: "" });
  const groups: [string, Song[]][] = [
    ["伍佰 & China Blue", [song("a", "島嶼天光", "伍佰 & China Blue"), song("b", "臺灣味", "伍佰 & China Blue")]],
    ["百合花", [song("c", "茶店仔", "百合花")]],
  ];

  it("lists every artist, then every song", () => {
    const { hits } = searchIndex(groups);
    expect(hits.map((hit) => hit.title)).toEqual(["伍佰 & China Blue", "百合花", "島嶼天光", "臺灣味", "茶店仔"]);
    expect(hits[1]).toMatchObject({ meta: "歌手 · 1 首", href: "/artists/bai-he-hua/" });
    expect(hits[4]).toEqual(expect.objectContaining({ href: "/songs/bai-he-hua/cha-dian-zai/", meta: "百合花" }));
  });

  it("matches traditional, simplified and pinyin queries", () => {
    const { table, hits } = searchIndex(groups);
    const matches = (query: string) =>
      hits.filter((hit) => hit.search.includes(foldWith(table, query))).map((hit) => hit.title);
    expect(matches("台湾")).toEqual(["臺灣味"]);
    expect(matches("島屿")).toEqual(["島嶼天光"]);
    expect(matches("bai he")).toEqual(["百合花"]);
  });
});
