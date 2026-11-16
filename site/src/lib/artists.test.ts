import { describe, expect, it } from "vitest";
import { byInitial, compareSongs, initial } from "./artists";
import type { Song } from "./catalog";

const group = (artist: string): [string, Song[]] => [artist, []];

const song = (artist: string, title: string, id = title): Song => ({ id, title, artist, file: "", source: "" });

describe("song order", () => {
  it("sorts by romanized artist, then romanized title, with Latin titles among the letters", () => {
    const list = [song("伍佰", "釘子花"), song("江蕙", "酒醉還是地震"), song("伍佰", "KISS ME"), song("伍佰", "愛情限時批"),
      song("伍佰", "浪人", "b"), song("伍佰", "浪人", "a")];
    expect(list.sort(compareSongs).map((s) => `${s.title}${s.id === "a" || s.id === "b" ? s.id : ""}`))
      .toEqual(["酒醉還是地震", "愛情限時批", "釘子花", "KISS ME", "浪人a", "浪人b"]);
  });
});

describe("artist initials", () => {
  it("uses the Mandarin pinyin initial of traditional names and keeps Latin names", () => {
    expect(["伍佰", "滅火器", "董事長樂團", "江蕙", "Ripple", "閃靈"].map(initial))
      .toEqual(["W", "M", "D", "J", "R", "S"]);
    expect(initial("9453")).toBe("#");
  });

  it("orders letters A–Z with other names last, and artists by romanization within a letter", () => {
    const letters = byInitial(["五月天", "伍佰", "王識賢", "8+9", "Ripple", "江蕙"].map(group));
    expect(letters.map(([letter, groups]) => [letter, groups.map(([artist]) => artist)])).toEqual([
      ["J", ["江蕙"]],
      ["R", ["Ripple"]],
      ["W", ["王識賢", "伍佰", "五月天"]],
      ["#", ["8+9"]],
    ]);
  });
});
