import { globSync, readFileSync } from "node:fs";
import { defineMiddleware } from "astro:middleware";
import { simplifiedTable } from "./lib/hans";

// Interface text written by page scripts (search summaries, pin labels) is not in the HTML.
let interfaceText: string | undefined;
const scriptText = () =>
  (interfaceText ??= globSync("src/**/*.{astro,ts}").map((path) => readFileSync(path, "utf8")).join("\n"));

/**
 * Gives every page the traditional → simplified mappings for its own characters, for the
 * 繁/简 switch (lib/script.ts). Runs while static pages are prerendered, so OpenCC stays build-only.
 */
export const onRequest = defineMiddleware(async (_context, next) => {
  const response = await next();
  if (!response.headers.get("content-type")?.startsWith("text/html")) return response;
  const html = await response.text();
  const table = `<script type="application/json" id="hans">${JSON.stringify(simplifiedTable(html + scriptText()))}</script>`;
  return new Response(html.replace("</head>", `${table}</head>`), response);
});
