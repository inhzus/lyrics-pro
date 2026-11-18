import { describe, expect, it } from "vitest";
import { simplifiedTable } from "./hans";
import { hansHtml } from "./hansHtml";

const page = (body: string, head = "") => `<!DOCTYPE html><html lang="zh-Hans"><head>${head}</head><body>${body}</body></html>`;
const run = (html: string) => hansHtml(html, simplifiedTable(html));

describe("hansHtml", () => {
  it("converts text, the title and the description", () => {
    const html = page("<h1>愛無目地</h1>", '<title>台灣製造 · 伍佰</title><meta name="description" content="台語歌詞">');
    expect(run(html)).toBe(
      page("<h1>爱无目地</h1>", '<title>台湾制造 · 伍佰</title><meta name="description" content="台语歌词">'),
    );
  });

  it("converts the browser's attributes and switches lang", () => {
    expect(run(page('<input placeholder="搜尋歌手" title="搜尋"><p lang="nan-Hant" aria-label="歌詞">愛</p>'))).toBe(
      page('<input placeholder="搜寻歌手" title="搜寻"><p lang="nan-Hans" aria-label="歌词">爱</p>'),
    );
  });

  it("leaves scripts, styles, code, templates and comments as written", () => {
    const body =
      '<script>const label = "置頂";</script><style>/* 歌詞 */</style><code>歌詞.txt</code>' +
      '<template id="t"><button title="置頂"></button></template><!-- 歌詞 -->';
    expect(run(page(body))).toBe(page(body));
  });

  it("leaves [data-no-convert] elements and everything inside them", () => {
    const body =
      '<div role="group" aria-label="繁體／简体" data-no-convert><a href="/songs/a/b/">繁</a><span><i>體</i></span>' +
      "<br></div><p>體</p>";
    expect(run(page(body))).toBe(
      page(
        '<div role="group" aria-label="繁體／简体" data-no-convert><a href="/songs/a/b/">繁</a><span><i>體</i></span>' +
          "<br></div><p>体</p>",
      ),
    );
  });

  it("moves links to other pages under /hans/", () => {
    const links = (...hrefs: string[]) => hrefs.map((href) => `<a href="${href}">x</a>`).join("");
    expect(run(page(links("/", "/artists/wu-bai/", "/songs/wu-bai/ri-zi/#top", "#a", "/search.json", "https://example.com/")))).toBe(
      page(links("/hans/", "/hans/artists/wu-bai/", "/hans/songs/wu-bai/ri-zi/#top", "#a", "/search.json", "https://example.com/")),
    );
  });

  it("leaves link elements, canonical URLs and Tâi-lô alone", () => {
    const head = '<link rel="canonical" href="/songs/a/b/"><link rel="stylesheet" href="/_astro/a.css">';
    const body = '<svg><path d="M1 2z" /></svg><p class="rom">ài lí bô ba̍k-tē</p>';
    expect(run(page(body, head))).toBe(page(body, head));
  });
});
