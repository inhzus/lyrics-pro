import type { APIRoute } from "astro";
import { byInitial } from "../lib/artists";
import { byArtist, songs } from "../lib/catalog";
import { searchIndex } from "../lib/search";

// Same artist order as the directory on the home page.
const groups = () => byInitial(byArtist(songs())).flatMap(([, list]) => list);

export const GET: APIRoute = () => new Response(JSON.stringify(searchIndex(groups())));
