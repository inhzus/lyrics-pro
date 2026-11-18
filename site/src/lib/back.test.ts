import { describe, expect, it } from "vitest";
import { returnsTo } from "./back";

const origin = "https://lyrics.inhzus.io";

describe("returnsTo", () => {
  it("matches the page the reader came from", () => {
    expect(returnsTo(`${origin}/`, `${origin}/`, origin)).toBe(true);
    expect(returnsTo("/artists/wu-bai/", `${origin}/artists/wu-bai/`, origin)).toBe(true);
  });

  it("ignores the referrer's query and hash", () => {
    expect(returnsTo(`${origin}/`, `${origin}/?q=1#W`, origin)).toBe(true);
  });

  it("rejects another page", () => {
    expect(returnsTo(`${origin}/`, `${origin}/songs/wu-bai/lang-jin-tsing-kua/`, origin)).toBe(false);
  });

  it("rejects another origin or no referrer", () => {
    expect(returnsTo(`${origin}/`, "https://example.com/", origin)).toBe(false);
    expect(returnsTo(`${origin}/`, "", origin)).toBe(false);
  });
});
