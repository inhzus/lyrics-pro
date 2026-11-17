/**
 * The light/dark switch beside 繁/简. "auto" follows the system and is stored as no value;
 * otherwise the choice is kept in localStorage under `theme` and applied before first paint
 * by Base.astro. The icons are swapped by CSS from `:root[data-theme]`.
 */
export type Theme = "auto" | "light" | "dark";
const KEY = "theme";
const ORDER: Theme[] = ["auto", "light", "dark"];

export const THEME_NAMES: Record<Theme, string> = {
  auto: "主題：自動",
  light: "主題：淺色",
  dark: "主題：深色",
};

export const nextTheme = (current: Theme): Theme => ORDER[(ORDER.indexOf(current) + 1) % ORDER.length];

// Browser runtime: everything below touches the document.

export function start() {
  const root = document.documentElement;
  const current = (): Theme => (root.dataset.theme === "light" || root.dataset.theme === "dark" ? root.dataset.theme : "auto");
  const buttons = document.querySelectorAll<HTMLButtonElement>("[data-theme-toggle]");
  const render = () => {
    for (const button of buttons) {
      button.setAttribute("aria-label", THEME_NAMES[current()]);
      button.title = THEME_NAMES[current()];
    }
  };
  for (const button of buttons) {
    button.addEventListener("click", () => {
      const next = nextTheme(current());
      if (next === "auto") delete root.dataset.theme;
      else root.dataset.theme = next;
      try {
        if (next === "auto") localStorage.removeItem(KEY);
        else localStorage.setItem(KEY, next);
      } catch {}
      render();
    });
  }
  render();
}
