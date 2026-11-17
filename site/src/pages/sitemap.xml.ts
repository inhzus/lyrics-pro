import type { APIRoute } from "astro";
import { songs } from "../lib/catalog";
import { sitemapXml } from "../lib/sitemap";

// Listed in public/robots.txt; submitted once in Search Console (docs/website.md).
export const GET: APIRoute = ({ site }) =>
  new Response(sitemapXml(site!, songs()), { headers: { "Content-Type": "application/xml; charset=utf-8" } });
