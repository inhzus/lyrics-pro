import { globSync, readFileSync } from "node:fs";
import { defineConfig } from "astro/config";
import { songs } from "./src/lib/catalog.ts";
import { codePoints, keepUsedFaces } from "./src/lib/fontSubset.ts";

/**
 * Fontsource's Noto Serif TC stylesheets declare ~108 unicode-range slices per weight. Keep
 * only the slices that cover a character in the catalog or the page templates, so the CSS
 * stays small. Filtering in `transform` keeps Vite's content hash in step with the result.
 */
function notoSlices() {
  let used;
  return {
    name: "noto-serif-tc-slices",
    enforce: "pre",
    transform(code, id) {
      if (!/@fontsource\/noto-serif-tc\/\d+\.css$/.test(id.split("?")[0])) return;
      used ??= codePoints([
        ...songs().flatMap((song) => Object.values(song)),
        ...globSync("src/**/*.{astro,ts}").map((path) => readFileSync(path, "utf8")),
      ]);
      return { code: keepUsedFaces(code, used), map: null };
    },
  };
}

export default defineConfig({
  site: "https://lyrics.inhzus.io",
  output: "static",
  trailingSlash: "always",
  build: { format: "directory" },
  vite: { plugins: [notoSlices()] },
});
