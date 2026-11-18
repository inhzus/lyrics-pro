/**
 * Links marked `data-back` return through history when they point at the page the reader just came
 * from, so the browser restores its scroll depth and state (such as the home page search). Otherwise,
 * for example on a direct visit or from a sibling song, they navigate normally.
 */
export const returnsTo = (href: string, referrer: string, origin: string): boolean => {
  if (!referrer) return false;
  try {
    const from = new URL(referrer);
    return from.origin === origin && from.pathname === new URL(href, origin).pathname;
  } catch {
    return false;
  }
};

// Browser runtime: everything below touches the document.

export function start() {
  document.addEventListener("click", (event) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = (event.target as Element | null)?.closest<HTMLAnchorElement>("a[data-back]");
    if (!link || history.length < 2 || !returnsTo(link.href, document.referrer, location.origin)) return;
    event.preventDefault();
    history.back();
  });
}
