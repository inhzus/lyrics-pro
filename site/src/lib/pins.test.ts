import { describe, expect, it } from "vitest";
import { parsePins, togglePin } from "./pins";

const defaults = ["/artists/aaaaaaaaaaaa/", "/artists/bbbbbbbbbbbb/"];

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
    const raw = JSON.stringify(["/songs/supplied-1/", 3, "https://x/", "/artists/a/", "/songs/supplied-1/", "/other/x/"]);
    expect(parsePins(raw, defaults)).toEqual(["/songs/supplied-1/", "/artists/a/"]);
  });
});

describe("togglePin", () => {
  it("appends a new pin and removes an existing one", () => {
    expect(togglePin(defaults, "/songs/x/")).toEqual([...defaults, "/songs/x/"]);
    expect(togglePin(defaults, defaults[0])).toEqual([defaults[1]]);
  });
});
