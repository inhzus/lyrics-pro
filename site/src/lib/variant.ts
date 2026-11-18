/**
 * Every page exists twice: traditional at its own path and simplified under `/hans/`, so search
 * engines can index both scripts. Pins, search rows and other stored paths use the traditional form.
 */
const HANS = "/hans";
/** Home, artist and song pages: the paths that have a simplified twin. */
const PAGE = /^\/(?:artists\/[^/]+\/|songs\/[^/]+\/[^/]+\/)?$/;

export const isPagePath = (path: string) => PAGE.test(path);
export const isHansPath = (pathname: string) => pathname.startsWith(`${HANS}/`);
export const toHans = (path: string) => HANS + path;
export const toHant = (pathname: string) => (isHansPath(pathname) ? pathname.slice(HANS.length) : pathname);

/** Both versions of a page; anything else (the 404 page) offers the two home pages. */
export function alternates(pathname: string) {
  const path = toHant(pathname);
  const page = isPagePath(path);
  return { page, hant: page ? path : "/", hans: toHans(page ? path : "/") };
}

/** Doubles static paths: each entry once at its own path and once under `/hans/`. */
export const inBothScripts = <T extends { params: Record<string, string> }>(entries: T[]) =>
  entries.flatMap((entry) => [
    { ...entry, params: { ...entry.params, script: undefined } },
    { ...entry, params: { ...entry.params, script: "hans" } },
  ]);

// Browser runtime: everything below touches the document.

/** A traditional page path as a link within the script of the current page. */
export const pagePath = (path: string) => (document.documentElement.dataset.script === "hans" ? toHans(path) : path);
