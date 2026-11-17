import { artistPath, byArtist, type Song, songPath } from "./catalog";

/** Every page as an absolute URL for /sitemap.xml: home, artists, then songs. No lastmod: the build has no per-page date. */
export function sitemapXml(site: URL, list: Song[]) {
  const paths = ["/", ...byArtist(list).map(([artist]) => artistPath(artist)), ...list.map(songPath)];
  const urls = paths.map((path) => `  <url><loc>${new URL(path, site).href}</loc></url>`);
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls.join("\n")}\n</urlset>\n`;
}
