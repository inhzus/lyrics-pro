import { describe, expect, it } from "vitest";
import type { Song } from "./catalog";
import { sitemapXml } from "./sitemap";

describe("sitemapXml", () => {
  const song = (id: string, title: string, artist: string): Song => ({ id, title, artist, file: "", source: "" });

  it("lists home, each artist once, then every song as absolute URLs", () => {
    const xml = sitemapXml(new URL("https://lyrics.inhzus.io"), [
      song("a", "台灣製造", "伍佰"),
      song("b", "日子", "伍佰"),
      song("c", "日子", "滅火器"),
    ]);
    expect(xml).toMatch(/^<\?xml version="1.0" encoding="UTF-8"\?>\n<urlset xmlns="http:\/\/www.sitemaps.org\/schemas\/sitemap\/0.9">/);
    expect([...xml.matchAll(/<loc>([^<]*)<\/loc>/g)].map(([, url]) => url)).toEqual([
      "https://lyrics.inhzus.io/",
      "https://lyrics.inhzus.io/artists/wu-bai/",
      "https://lyrics.inhzus.io/artists/mie-huo-qi/",
      "https://lyrics.inhzus.io/songs/wu-bai/tai-wan-zhi-zao/",
      "https://lyrics.inhzus.io/songs/wu-bai/ri-zi/",
      "https://lyrics.inhzus.io/songs/mie-huo-qi/ri-zi/",
    ]);
  });
});
