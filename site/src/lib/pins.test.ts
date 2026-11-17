import { describe, expect, it } from "vitest";
import { legacyPins, migratePins, parsePins, togglePin } from "./pins";

const defaults = ["/artists/wu-bai/", "/artists/wu-yue-tian/"];

describe("parsePins", () => {
  it("uses the defaults until something is stored", () => {
    expect(parsePins(null, defaults)).toEqual(defaults);
  });

  it("falls back to the defaults for corrupt or non-list values", () => {
    expect(parsePins("{", defaults)).toEqual(defaults);
    expect(parsePins('{"a":1}', defaults)).toEqual(defaults);
    expect(parsePins("null", defaults)).toEqual(defaults);
  });

  it("keeps an empty list, so the defaults can be unpinned", () => {
    expect(parsePins("[]", defaults)).toEqual([]);
  });

  it("drops entries that are not page paths and repeats", () => {
    const raw = JSON.stringify(["/songs/a/b/", 3, "https://x/", "/artists/a/", "/songs/a/b/", "/other/x/", "/songs/a/"]);
    expect(parsePins(raw, defaults)).toEqual(["/songs/a/b/", "/artists/a/"]);
  });
});

describe("legacy pins", () => {
  it("finds hashed artist and manifest ID paths only", () => {
    expect(legacyPins(JSON.stringify(["/artists/wu-bai/", "/songs/a/b/"]))).toBeNull();
    expect(legacyPins(null)).toBeNull();
    expect(legacyPins("{")).toBeNull();
    expect(legacyPins(JSON.stringify(["/artists/0166065abe59/"]))).toEqual(["/artists/0166065abe59/"]);
    expect(legacyPins(JSON.stringify(["/songs/supplied-1/"]))).toEqual(["/songs/supplied-1/"]);
  });

  it("moves them in place and drops songs that no longer exist", () => {
    const moved = { "/artists/0166065abe59/": "/artists/wu-bai/", "/songs/supplied-1/": "/songs/wu-bai/ri-zi/" };
    const stored = ["/songs/a/b/", "/songs/supplied-1/", "/songs/supplied-gone/", "/artists/0166065abe59/"];
    expect(migratePins(stored, moved)).toEqual(["/songs/a/b/", "/songs/wu-bai/ri-zi/", "/artists/wu-bai/"]);
  });
});

describe("togglePin", () => {
  it("appends a new pin and removes an existing one", () => {
    expect(togglePin(defaults, "/songs/x/y/")).toEqual([...defaults, "/songs/x/y/"]);
    expect(togglePin(defaults, defaults[0])).toEqual([defaults[1]]);
  });
});
