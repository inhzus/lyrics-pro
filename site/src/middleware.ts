import { globSync, readFileSync } from "node:fs";
import { defineMiddleware } from "astro:middleware";
import { simplifiedTable } from "./lib/hans";
import { hansHtml } from "./lib/hansHtml";
import { isHansPath } from "./lib/variant";

// Interface text written by page scripts (search summaries, pin labels) is not in the HTML.
let interfaceText: string | undefined;
const scriptText = () =>
  (interfaceText ??= globSync("src/**/*.{astro,ts}").map((path) => readFileSync(path, "utf8")).join("\n"));

/**
 * Writes the simplified pages under /hans/ while static pages are prerendered, so OpenCC stays
 * build-only. Each also gets the traditional → simplified mappings for its own characters (`#hans`),
 * which lib/script.ts uses for text that page scripts add later.
 */
export const onRequest = defineMiddleware(async (context, next) => {
  const response = await next();
  if (!isHansPath(context.url.pathname) || !response.headers.get("content-type")?.startsWith("text/html")) {
    return response;
  }
  const html = await response.text();
  const mappings = simplifiedTable(html + scriptText());
  const table = `<script type="application/json" id="hans">${JSON.stringify(mappings)}</script>`;
  return new Response(hansHtml(html, mappings).replace("</head>", `${table}</head>`), response);
});
