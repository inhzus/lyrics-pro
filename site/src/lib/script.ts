import type { FoldTable } from "./fold";

/**
 * The 繁/简 switch. Pages are written in traditional characters; each page carries the
 * simplified form of its own characters (`#hans`, injected by src/middleware.ts), and the
 * choice is kept in the visitor's localStorage under `script` ("hans", or absent for 繁).
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

// Browser runtime: everything below touches the document.

const ATTRIBUTES = ["placeholder", "title", "aria-label", "lang"];
const SKIP = "script, style, code, template, [data-no-convert]";

let table: FoldTable = {};
let mode: Mode = "hant";
// Original and converted text, so 繁 restores the exact source and later edits are noticed.
const texts = new WeakMap<Text, [string, string]>();
const attributes = new WeakMap<Element, Map<string, [string, string]>>();
let title: [string, string] | undefined;

/** Links Noto Serif SC's stylesheets (listed on `<html data-sc-fonts>`) and waits for them. */
function loadFonts() {
  const hrefs: string[] = JSON.parse(document.documentElement.dataset.scFonts ?? "[]");
  const links = [...document.head.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]')];
  return Promise.all(
    hrefs.map((href) => {
      let link = links.find((other) => other.getAttribute("href") === href);
      if (link?.sheet) return;
      if (!link) {
        link = document.head.appendChild(document.createElement("link"));
        link.rel = "stylesheet";
        link.href = href;
      }
      const pending = link;
      return new Promise((resolve) => {
        pending.addEventListener("load", resolve, { once: true });
        pending.addEventListener("error", resolve, { once: true });
      });
    }),
  );
}

const shown = (source: string) => (mode === "hans" ? convert(table, source) : source);

function updateText(node: Text) {
  if (node.parentElement?.closest(SKIP)) return;
  const record = texts.get(node);
  const source = record && node.data === record[1] ? record[0] : node.data;
  const next = shown(source);
  texts.set(node, [source, next]);
  if (node.data !== next) node.data = next;
}

function updateAttributes(element: Element) {
  if (element.closest(SKIP)) return;
  let records = attributes.get(element);
  for (const name of ATTRIBUTES) {
    const value = element.getAttribute(name);
    if (value === null) continue;
    records ??= new Map();
    const record = records.get(name);
    const source = record && value === record[1] ? record[0] : value;
    const next = name === "lang" ? swapLang(source, mode) : shown(source);
    records.set(name, [source, next]);
    if (value !== next) element.setAttribute(name, next);
  }
  if (records) attributes.set(element, records);
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

function updateAll() {
  const source = title && document.title === title[1] ? title[0] : document.title;
  title = [source, shown(source)];
  if (document.title !== title[1]) document.title = title[1];
  update(document.documentElement);
  for (const button of document.querySelectorAll<HTMLButtonElement>("button[data-script]")) {
    button.setAttribute("aria-pressed", String(button.dataset.script === mode));
  }
}

export function setMode(next: Mode) {
  mode = next;
  if (mode === "hans") void loadFonts();
  const root = document.documentElement;
  if (mode === "hans") root.dataset.script = "hans";
  else delete root.dataset.script;
  try {
    if (mode === "hans") localStorage.setItem(KEY, "hans");
    else localStorage.removeItem(KEY);
  } catch {}
  updateAll();
}

/** Adds mappings for text that arrives later (the home page's /search.json rows). */
export function extend(more: FoldTable) {
  Object.assign(table, more);
  if (mode === "hans") update(document.body);
}

export function start() {
  const root = document.documentElement;
  try {
    table = JSON.parse(document.querySelector("#hans")?.textContent ?? "{}");
  } catch {}
  // The pre-paint script in Base.astro has already read the saved choice.
  mode = root.dataset.script === "hans" ? "hans" : "hant";
  updateAll();
  new MutationObserver((records) => {
    if (mode === "hant") return;
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
  document.addEventListener("click", (event) => {
    const button = (event.target as Element).closest<HTMLButtonElement>("button[data-script]");
    if (button) setMode(button.dataset.script as Mode);
  });
  // Reveal a simplified page once Noto Serif SC's stylesheet is in (Base.astro has a timeout too).
  if (mode === "hans") void loadFonts().finally(() => root.classList.remove("converting"));
  else root.classList.remove("converting");
}
