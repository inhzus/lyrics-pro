/**
 * Pinned artists and songs, kept in the visitor's localStorage as a JSON array of page paths
 * (`/artists/<slug>/`, `/songs/<id>/`) in pin order. Until the visitor changes anything the
 * defaults on `<html data-default-pins>` apply; every toggle saves the whole list, so
 * unpinning a default sticks.
 */
const KEY = "pins";
const PATH = /^\/(artists|songs)\/[^/]+\/$/;

/** The stored list, or the defaults when nothing usable is stored. */
export function parsePins(raw: string | null, defaults: string[]): string[] {
  if (raw === null) return defaults;
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return defaults;
  }
  if (!Array.isArray(value)) return defaults;
  return [...new Set(value.filter((path): path is string => typeof path === "string" && PATH.test(path)))];
}

/** Unpins a pinned path, otherwise pins it after the others. */
export const togglePin = (list: string[], path: string) =>
  list.includes(path) ? list.filter((other) => other !== path) : [...list, path];

export const isArtist = (path: string) => path.startsWith("/artists/");

// Browser runtime: everything below touches the document.

const defaults = () => {
  try {
    return JSON.parse(document.documentElement.dataset.defaultPins ?? "[]") as string[];
  } catch {
    return [];
  }
};

export function pins(): string[] {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(KEY);
  } catch {}
  return parsePins(raw, defaults());
}

/** Reflects the current pins on every pin button under `root`. */
export function render(root: ParentNode = document) {
  const pinned = new Set(pins());
  for (const button of root.querySelectorAll<HTMLButtonElement>("button[data-pin]")) {
    const on = pinned.has(button.dataset.pin!);
    button.setAttribute("aria-pressed", String(on));
    button.title = on ? "取消置頂" : "置頂";
    const label = button.querySelector(".pin-label");
    if (label) label.textContent = on ? "已置頂" : "置頂";
  }
}

const changed = () => {
  render();
  document.dispatchEvent(new CustomEvent("pins-change"));
};

export function toggle(path: string) {
  const next = togglePin(pins(), path);
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {}
  changed();
}

/** A fresh pin button for rows built in the browser, cloned from PinButton's template. */
export function pinButton(path: string, pinned = pins().includes(path)) {
  const template = document.querySelector<HTMLTemplateElement>("#pin-template")!;
  const button = template.content.firstElementChild!.cloneNode(true) as HTMLButtonElement;
  button.dataset.pin = path;
  button.setAttribute("aria-pressed", String(pinned));
  button.title = pinned ? "取消置頂" : "置頂";
  return button;
}

let started = false;
/** Wires the delegated click handler and cross-tab sync once per page. */
export function start() {
  if (started) return;
  started = true;
  document.addEventListener("click", (event) => {
    const button = (event.target as Element).closest<HTMLButtonElement>("button[data-pin]");
    if (!button) return;
    event.preventDefault();
    button.classList.remove("pop");
    void button.offsetWidth;
    button.classList.add("pop");
    toggle(button.dataset.pin!);
  });
  addEventListener("storage", (event) => {
    if (event.key === KEY || event.key === null) changed();
  });
  render();
}
