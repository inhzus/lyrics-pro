import { describe, expect, it } from "vitest";
import { foldWith } from "./fold";
import { createFolder } from "./search";

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
