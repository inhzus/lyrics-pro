import { describe, expect, it } from "vitest";
import { simplifiedTable } from "./hans";
import { convert, swapLang } from "./script";

describe("simplifiedTable", () => {
  it("maps only the Han characters that convert differently", () => {
    const table = simplifiedTable('<p class="han" lang="nan-Hant">愛妳無目地 天 · ài lí</p>');
    expect(table).toEqual({ 愛: "爱", 無: "无" });
  });

  it("folds Taiwan variants to the mainland form", () => {
    expect(simplifiedTable("臺")).toEqual({ 臺: "台" });
  });
});

describe("convert", () => {
  const table = simplifiedTable("愛妳無目地，聽");

  it("converts table characters and leaves everything else", () => {
    expect(convert(table, "愛妳無目地，ài lí bô ba̍k-tē")).toBe("爱妳无目地，ài lí bô ba̍k-tē");
    expect(convert(table, "聽 (Live) 2024")).toBe("听 (Live) 2024");
    expect(convert(table, "天懸懸")).toBe("天懸懸");
  });
});

describe("swapLang", () => {
  it("switches the script subtag both ways", () => {
    expect(swapLang("zh-Hant-TW", "hans")).toBe("zh-Hans-TW");
    expect(swapLang("nan-Hans", "hant")).toBe("nan-Hant");
    expect(swapLang("nan-Latn", "hans")).toBe("nan-Latn");
  });
});
