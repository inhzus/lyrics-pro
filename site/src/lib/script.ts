import type { FoldTable } from "./fold";

/**
 * Traditional ↔ simplified. Pages are written in traditional characters and each one also exists
 * under `/hans/`, converted while it is prerendered (src/middleware.ts, lib/hansHtml.ts). The 繁/简
 * switch links between the two and remembers the choice in localStorage under `script` ("hans", or
 * absent for 繁); only the bare home page follows it (Base.astro). On a simplified page this module
 * converts what scripts add later, from the `#hans` table that the middleware injects.
 */
export type Mode = "hant" | "hans";
const KEY = "script";

export const convert = (table: FoldTable, text: string) => {
  let out = "";
  for (const character of text) out += table[character] ?? character;
  return out;
};

/** `zh-Hant-TW` ↔ `zh-Hans-TW`, `nan-Hant` ↔ `nan-Hans`. */
export const swapLang = (lang: string, mode: Mode) =>
  mode === "hans" ? lang.replace(/-Hant\b/, "-Hans") : lang.replace(/-Hans\b/, "-Hant");

/** Attributes converted along with text; `lang` switches its script subtag instead. */
export const ATTRIBUTES = ["placeholder", "title", "aria-label", "lang"];
/** Elements whose contents are never converted, and the attribute that exempts any other element. */
export const RAW = ["script", "style", "code", "template"];
export const KEEP = "data-no-convert";

// Browser runtime: everything below touches the document.

const SKIP = [...RAW, `[${KEEP}]`].join(", ");
const table: FoldTable = {};
const hans = () => document.documentElement.dataset.script === "hans";

function updateText(node: Text) {
  if (node.parentElement?.closest(SKIP)) return;
  const next = convert(table, node.data);
  if (node.data !== next) node.data = next;
}

function updateAttributes(element: Element) {
  if (element.closest(SKIP)) return;
  for (const name of ATTRIBUTES) {
    const value = element.getAttribute(name);
    if (value === null) continue;
    const next = name === "lang" ? swapLang(value, "hans") : convert(table, value);
    if (value !== next) element.setAttribute(name, next);
  }
}

function update(root: Node) {
  if (root instanceof Text) return updateText(root);
  if (root instanceof Element) updateAttributes(root);
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node instanceof Text) updateText(node);
    else updateAttributes(node as Element);
  }
}

function remember(mode: Mode) {
  try {
    if (mode === "hans") localStorage.setItem(KEY, "hans");
    else localStorage.removeItem(KEY);
  } catch {}
}

/** Adds mappings for text that arrives later (the home page's /search.json rows). */
export function extend(more: FoldTable) {
  Object.assign(table, more);
  if (hans()) update(document.body);
}

export function start() {
  document.addEventListener("click", (event) => {
    const link = (event.target as Element).closest<HTMLAnchorElement>("a[data-script]");
    if (link) remember(link.dataset.script as Mode);
  });
  if (!hans()) return;
  try {
    Object.assign(table, JSON.parse(document.querySelector("#hans")?.textContent ?? "{}"));
  } catch {}
  new MutationObserver((records) => {
    for (const record of records) {
      if (record.type === "childList") record.addedNodes.forEach(update);
      else if (record.type === "characterData") updateText(record.target as Text);
      else updateAttributes(record.target as Element);
    }
  }).observe(document.body, {
    subtree: true,
    childList: true,
    characterData: true,
    attributeFilter: ATTRIBUTES,
  });
}
