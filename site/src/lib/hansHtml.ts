import type { FoldTable } from "./fold";
import { ATTRIBUTES, convert, KEEP, RAW, swapLang } from "./script";
import { isPagePath, toHans } from "./variant";

/**
 * The simplified twin of a prerendered page: the rules lib/script.ts applies in the browser
 * (text and ATTRIBUTES, never RAW elements or anything inside [data-no-convert]), plus meta
 * `content` for the description and Open Graph tags, and links to other pages moved under /hans/.
 * A small tokenizer is enough for Astro's own output, which keeps the build free of a DOM library.
 */
const VOID = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"]);
const TOKEN = /<!--[\s\S]*?-->|<![^>]*>|<(\/?)([a-zA-Z][\w:-]*)((?:[^>"']|"[^"]*"|'[^']*')*)>|[^<]+|</g;
const ATTRIBUTE = /([^\s"'=/>]+)(\s*=\s*)("[^"]*"|'[^']*'|[^\s"'>]+)/g;

/** A same-site page link, moved to its simplified page; assets, data and other sites stay. */
function hansHref(href: string) {
  if (!href.startsWith("/") || href.startsWith("//")) return href;
  const cut = href.search(/[?#]/);
  const path = cut < 0 ? href : href.slice(0, cut);
  return isPagePath(path) ? toHans(path) + href.slice(path.length) : href;
}

function convertAttributes(tag: string, attributes: string, table: FoldTable) {
  return attributes.replace(ATTRIBUTE, (whole, name: string, equals: string, quoted: string) => {
    const quote = quoted[0] === '"' || quoted[0] === "'" ? quoted[0] : "";
    const value = quote ? quoted.slice(1, -1) : quoted;
    const attribute = name.toLowerCase();
    let next = value;
    if (attribute === "lang") next = swapLang(value, "hans");
    else if (ATTRIBUTES.includes(attribute) || (tag === "meta" && attribute === "content")) next = convert(table, value);
    else if (tag === "a" && attribute === "href") next = hansHref(value);
    return next === value ? whole : `${name}${equals}${quote}${next}${quote}`;
  });
}

export function hansHtml(html: string, table: FoldTable) {
  let out = "";
  // Open elements, and how many were open when a [data-no-convert] element began (-1: none).
  const open: string[] = [];
  let kept = -1;
  TOKEN.lastIndex = 0;
  for (let match = TOKEN.exec(html); match; match = TOKEN.exec(html)) {
    const [token, closing, name, attributes] = match;
    if (!name) {
      out += token.startsWith("<") || kept >= 0 ? token : convert(table, token);
      continue;
    }
    const tag = name.toLowerCase();
    if (closing) {
      const at = open.lastIndexOf(tag);
      if (at >= 0) open.length = at;
      if (open.length <= kept) kept = -1;
      out += token;
      continue;
    }
    const keep = kept >= 0 || new RegExp(`\\s${KEEP}(?=[\\s=/>]|$)`).test(attributes);
    out += keep ? token : `<${name}${convertAttributes(tag, attributes, table)}>`;
    if (RAW.includes(tag)) {
      // Contents stay as they are, up to the closing tag.
      const end = html.indexOf(`</${tag}`, TOKEN.lastIndex);
      const stop = end < 0 ? html.length : end;
      out += html.slice(TOKEN.lastIndex, stop);
      TOKEN.lastIndex = stop;
      continue;
    }
    if (VOID.has(tag) || attributes.trimEnd().endsWith("/")) continue;
    if (keep && kept < 0) kept = open.length;
    open.push(tag);
  }
  return out;
}
