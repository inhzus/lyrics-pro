import { globSync, readFileSync, writeFileSync } from "node:fs";
import { defineConfig } from "astro/config";
import { legacyPaths, songs } from "./src/lib/catalog.ts";
import { codePoints, keepUsedFaces } from "./src/lib/fontSubset.ts";
import { simplifiedTable } from "./src/lib/hans.ts";

/**
 * Fontsource's Noto Serif stylesheets declare ~108 unicode-range slices per weight. Keep only
 * the slices that cover a character in the catalog or the page templates, so the CSS stays
 * small. TC sets traditional text; SC is used only in 简 mode (src/lib/script.ts), so it also
 * covers the simplified forms. Filtering in `transform` keeps Vite's content hash in step.
 */
function notoSlices() {
  let traditional, simplified;
  return {
    name: "noto-serif-slices",
    enforce: "pre",
    transform(code, id) {
      const family = id.split("?")[0].match(/@fontsource\/noto-serif-(tc|sc)\/\d+\.css$/)?.[1];
      if (!family) return;
      if (!traditional) {
        const texts = [
          ...songs().flatMap((song) => Object.values(song)),
          ...globSync("src/**/*.{astro,ts}").map((path) => readFileSync(path, "utf8")),
        ];
        traditional = codePoints(texts);
        simplified = codePoints([...texts, ...texts.map((text) => Object.values(simplifiedTable(text)).join(""))]);
      }
      return { code: keepUsedFaces(code, family === "tc" ? traditional : simplified), map: null };
    },
  };
}

/** Cloudflare Pages `_redirects`: 301s from the hashed/ID page paths to the pinyin ones. */
function legacyRedirects() {
  return {
    name: "legacy-redirects",
    hooks: {
      "astro:build:done": ({ dir }) => {
        const lines = legacyPaths(songs()).map(([from, to]) => `${from} ${to} 301`);
        writeFileSync(new URL("_redirects", dir), `${lines.join("\n")}\n`);
      },
    },
  };
}

export default defineConfig({
  site: "https://lyrics.inhzus.io",
  output: "static",
  trailingSlash: "always",
  build: { format: "directory" },
  integrations: [legacyRedirects()],
  vite: { plugins: [notoSlices()] },
});
