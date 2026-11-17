import type { APIRoute } from "astro";
import { legacyPaths, songs } from "../lib/catalog";

// Old page path → current one; lib/pins.ts fetches it only to rewrite pins saved before the move.
export const GET: APIRoute = () => new Response(JSON.stringify(Object.fromEntries(legacyPaths(songs()))));
