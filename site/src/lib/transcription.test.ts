import { describe, expect, it } from "vitest";
import { classify } from "./transcription";

describe("classify", () => {
  it("pairs columns and keeps credits, notes and unpaired lines in order", () => {
    const raw = "作詞：甲   台語拼音：乙\n\nNote: italics are English\n\n心內話\t\t無人聽\n"
      + "Sim-lāi-uē    bô lâng thiann\n\n\n\nHello world\n孤單\n";
    const { credits, items } = classify(raw);
    expect(credits).toEqual(["作詞：甲 台語拼音：乙"]);
    expect(items).toEqual([
      { kind: "note", text: "Note: italics are English" },
      { kind: "break", blanks: 1 },
      {
        kind: "pair", text: "心內話 無人聽", spelling: "Sim-lāi-uē bô lâng thiann",
        parts: [{ text: "心內話", spelling: "Sim-lāi-uē" }, { text: "無人聽", spelling: "bô lâng thiann" }],
      },
      { kind: "break", blanks: 3 },
      { kind: "line", text: "Hello world" },
      { kind: "line", text: "孤單" },
    ]);
  });

  it("keeps Han lines without romanization plain and skips blank lines inside a pair", () => {
    expect(classify("第一句\n第二句\n\nkhuànn\n").items).toEqual([
      { kind: "line", text: "第一句" },
      { kind: "pair", text: "第二句", spelling: "khuànn" },
    ]);
  });

  it("does not align columns when their counts differ", () => {
    const [item] = classify("妳送予我的批信 我攏無拍開\nlí sàng hōo guá ê phue-sìn  guá lóng bô phah khui").items;
    expect(item).toMatchObject({ kind: "pair" });
    expect(item).not.toHaveProperty("parts");
  });

  it("never pairs a lyric with a credit or note", () => {
    const { credits, items } = classify("心內話\n作曲：甲\n無人聽\nNote: live\n");
    expect(credits).toEqual(["作曲：甲"]);
    expect(items).toEqual([
      { kind: "line", text: "心內話" },
      { kind: "line", text: "無人聽" },
      { kind: "note", text: "Note: live" },
    ]);
  });

  it("keeps every nonempty source character", () => {
    const raw = "嘿! 朋友 <b>&\nhey! pîng-iú\n";
    const flat = classify(raw).items.flatMap((item) =>
      item.kind === "pair" ? [item.text, item.spelling] : item.kind === "break" ? [] : [item.text]);
    expect(flat.join("").replace(/\s/g, "")).toBe(raw.replace(/\s/g, ""));
  });
});
