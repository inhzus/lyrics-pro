import { artistPath, byArtist, type Song, songPath } from "./catalog";
import { toHans } from "./variant";

/**
 * Every page as an absolute URL for /sitemap.xml: home, artists, then songs, each traditional page
 * followed by its /hans/ twin, both listing the pair as hreflang alternates. No lastmod: the build
 * has no per-page date.
 */
export function sitemapXml(site: URL, list: Song[]) {
  const paths = ["/", ...byArtist(list).map(([artist]) => artistPath(artist)), ...list.map(songPath)];
  const urls = paths.flatMap((path) => {
    const hant = new URL(path, site).href;
    const hans = new URL(toHans(path), site).href;
    const links = [
      `<xhtml:link rel="alternate" hreflang="zh-Hant" href="${hant}"/>`,
      `<xhtml:link rel="alternate" hreflang="zh-Hans" href="${hans}"/>`,
      `<xhtml:link rel="alternate" hreflang="x-default" href="${hant}"/>`,
    ].join("");
    return [hant, hans].map((loc) => `  <url><loc>${loc}</loc>${links}</url>`);
  });
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n${urls.join("\n")}\n</urlset>\n`;
}
