import { describe, expect, it } from "vitest";
import { slugify, titleSlug } from "./slug";

describe("slugify", () => {
  it("romanizes Han text as toneless pinyin", () => {
    expect(slugify("伍佰")).toBe("wu-bai");
    expect(slugify("蘇打綠")).toBe("su-da-lv");
    expect(slugify("台灣製造")).toBe("tai-wan-zhi-zao");
  });

  it("keeps Latin and digits and collapses punctuation", () => {
    expect(slugify("滅火器 & Freddy (閃靈)")).toBe("mie-huo-qi-freddy-shan-ling");
    expect(slugify("11點的約會")).toBe("11-dian-de-yue-hui");
    expect(slugify("初心 (Beginner’s Mind)")).toBe("chu-xin-beginners-mind");
    expect(slugify("[2017] 進擊下半場")).toBe("2017-jin-ji-xia-ban-chang");
    expect(slugify("Bú-Tik")).toBe("bu-tik");
  });

  it("drops characters without a romanization", () => {
    expect(slugify("無緣ㄟ (Missed)")).toBe("wu-yuan-missed");
    expect(slugify("下晡的ワルツ")).toBe("xia-bu-de");
    expect(slugify("ㄟ")).toBe("");
  });

  it("drops bracketed English names from titles", () => {
    expect(titleSlug("心內話 (Bottom of My Heart)")).toBe("xin-nei-hua");
    expect(titleSlug("初心 (Beginner’s Mind)")).toBe("chu-xin");
    expect(titleSlug("為什麼 (今日的愛情)")).toBe("wei-shen-me-jin-ri-de-ai-qing");
    expect(titleSlug("等待 (ft.甲子慧)")).toBe("deng-dai");
    expect(titleSlug("思念呦 (with 阿杜)")).toBe("si-nian-you");
    expect(titleSlug("Would You Be My Girl (feat. 大支)")).toBe("would-you-be-my-girl");
    expect(titleSlug("男人三十 (30)")).toBe("nan-ren-san-shi");
    expect(titleSlug("(Intro)")).toBe("intro");
  });

  it("uses the reviewed readings", () => {
    expect(slugify("動力火車")).toBe("dong-li-huo-che");
    expect(slugify("董事長樂團")).toBe("dong-shi-chang-yue-tuan");
    expect(slugify("是嘸是")).toBe("shi-m-shi");
    expect(slugify("煞到妳")).toBe("sha-dao-ni");
  });
});
