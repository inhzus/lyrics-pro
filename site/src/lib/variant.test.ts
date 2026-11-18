import { describe, expect, it } from "vitest";
import { alternates, inBothScripts, isHansPath, isPagePath, toHans, toHant } from "./variant";

describe("page paths", () => {
  it("recognizes home, artist and song pages only", () => {
    expect(["/", "/artists/wu-bai/", "/songs/wu-bai/ri-zi/"].every(isPagePath)).toBe(true);
    expect(["/search.json", "/_astro/a.css", "/songs/wu-bai/", "/artists/wu-bai", "/404"].some(isPagePath)).toBe(false);
  });

  it("moves pages under /hans/ and back", () => {
    expect(toHans("/songs/wu-bai/ri-zi/")).toBe("/hans/songs/wu-bai/ri-zi/");
    expect(toHant("/hans/songs/wu-bai/ri-zi/")).toBe("/songs/wu-bai/ri-zi/");
    expect(toHant("/hans/")).toBe("/");
    expect(toHant("/artists/hansen/")).toBe("/artists/hansen/");
    expect(isHansPath("/hans/")).toBe(true);
    expect(isHansPath("/hansen/")).toBe(false);
  });
});

describe("alternates", () => {
  it("pairs a page with its twin from either side", () => {
    const pair = { page: true, hant: "/artists/wu-bai/", hans: "/hans/artists/wu-bai/" };
    expect(alternates("/artists/wu-bai/")).toEqual(pair);
    expect(alternates("/hans/artists/wu-bai/")).toEqual(pair);
    expect(alternates("/hans/")).toEqual({ page: true, hant: "/", hans: "/hans/" });
  });

  it("offers the home pages elsewhere", () => {
    expect(alternates("/404")).toEqual({ page: false, hant: "/", hans: "/hans/" });
  });
});

describe("inBothScripts", () => {
  it("adds a traditional and a simplified entry for each path", () => {
    expect(inBothScripts([{ params: { slug: "wu-bai" }, props: { n: 1 } }])).toEqual([
      { params: { slug: "wu-bai", script: undefined }, props: { n: 1 } },
      { params: { slug: "wu-bai", script: "hans" }, props: { n: 1 } },
    ]);
  });
});
