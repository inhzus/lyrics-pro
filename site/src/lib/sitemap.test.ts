import { describe, expect, it } from "vitest";
import type { Song } from "./catalog";
import { sitemapXml } from "./sitemap";

describe("sitemapXml", () => {
  const song = (id: string, title: string, artist: string): Song => ({ id, title, artist, file: "", source: "" });

  it("lists home, each artist once, then every song, each followed by its /hans/ twin", () => {
    const xml = sitemapXml(new URL("https://lyrics.zunish.io"), [
      song("a", "台灣製造", "伍佰"),
      song("b", "日子", "伍佰"),
      song("c", "日子", "滅火器"),
    ]);
    expect(xml).toMatch(
      /^<\?xml version="1.0" encoding="UTF-8"\?>\n<urlset xmlns="http:\/\/www.sitemaps.org\/schemas\/sitemap\/0.9" xmlns:xhtml="http:\/\/www.w3.org\/1999\/xhtml">/,
    );
    const paths = [
      "/",
      "/artists/wu-bai/",
      "/artists/mie-huo-qi/",
      "/songs/wu-bai/tai-wan-zhi-zao/",
      "/songs/wu-bai/ri-zi/",
      "/songs/mie-huo-qi/ri-zi/",
    ];
    expect([...xml.matchAll(/<loc>([^<]*)<\/loc>/g)].map(([, url]) => url)).toEqual(
      paths.flatMap((path) => [`https://lyrics.zunish.io${path}`, `https://lyrics.zunish.io/hans${path}`]),
    );
  });

  it("gives both versions of a page the same alternates", () => {
    const xml = sitemapXml(new URL("https://lyrics.zunish.io"), [song("a", "台灣製造", "伍佰")]);
    const entries = xml.match(/<url>.*<\/url>/g)!;
    const alternates = (entry: string) => entry.replace(/<loc>[^<]*<\/loc>/, "");
    expect(alternates(entries[2])).toBe(alternates(entries[3]));
    expect(entries[3]).toContain('hreflang="zh-Hant" href="https://lyrics.zunish.io/artists/wu-bai/"');
    expect(entries[3]).toContain('hreflang="zh-Hans" href="https://lyrics.zunish.io/hans/artists/wu-bai/"');
    expect(entries[3]).toContain('hreflang="x-default" href="https://lyrics.zunish.io/artists/wu-bai/"');
  });
});
