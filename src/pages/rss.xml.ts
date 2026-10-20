import { getCollection } from "astro:content";
import type { APIContext } from "astro";
import { blogImage, byPublishedDesc } from "../lib/content";
import { absoluteUrl } from "../lib/recipe-schema";

function xml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export async function GET(context: APIContext) {
  const site = context.site?.href ?? "https://www.onepotgal.com";
  const recipes = (await getCollection("recipes")).sort(byPublishedDesc);
  const items = recipes
    .map((recipe) => {
      const link = absoluteUrl(`/recipes/${recipe.id}`, site);
      const image = blogImage(recipe.data.image);
      const enclosure = image
        ? `\n      <enclosure url="${xml(absoluteUrl(image, site))}" type="image/jpeg" />`
        : "";
      return `    <item>
      <title>${xml(recipe.data.title)}</title>
      <link>${xml(link)}</link>
      <guid>${xml(link)}</guid>
      <pubDate>${new Date(`${recipe.data.published}T12:00:00Z`).toUTCString()}</pubDate>
      <description>${xml(recipe.data.excerpt ?? recipe.data.title)}</description>${enclosure}
    </item>`;
    })
    .join("\n");

  const body = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>one pot gal</title>
    <link>${xml(absoluteUrl("/", site))}</link>
    <description>cooking the most tasty, cozy, and delicious food that one pot can offer</description>
${items}
  </channel>
</rss>
`;

  return new Response(body, {
    headers: { "Content-Type": "application/rss+xml; charset=utf-8" },
  });
}
