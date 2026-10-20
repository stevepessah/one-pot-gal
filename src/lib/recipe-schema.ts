const SITE = "https://www.onepotgal.com";

export function absoluteUrl(pathOrUrl: string, site = SITE) {
  if (pathOrUrl.startsWith("http://") || pathOrUrl.startsWith("https://")) return pathOrUrl;
  return new URL(pathOrUrl, site).href;
}

export function canonicalUrl(pathname: string, site = SITE) {
  const path = pathname !== "/" && pathname.endsWith("/") ? pathname.slice(0, -1) : pathname;
  return new URL(path, site).href;
}

export function plainLead(body: string | undefined, fallback: string) {
  if (!body) return fallback;
  const paragraph = body
    .split("\n")
    .map((line) => line.trim())
    .find((line) => line && !line.startsWith("#") && !line.startsWith("!") && !line.startsWith("-") && !/^\d+[.)]\s/.test(line));
  if (!paragraph) return fallback;
  const clean = paragraph
    .replace(/!\[[^\]]*]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)]\([^)]*\)/g, "$1")
    .replace(/\*\*/g, "")
    .replace(/[_`]/g, "")
    .trim();
  if (clean.length <= 180) return clean;
  const cut = clean.slice(0, 177);
  const lastSpace = cut.lastIndexOf(" ");
  return `${(lastSpace > 120 ? cut.slice(0, lastSpace) : cut).trim()}…`;
}

function isHeading(line: string) {
  const trimmed = line.trim();
  return /^#{1,6}\s+/.test(trimmed) || /^\*\*.+\*\*/.test(trimmed);
}

function headingLabel(line: string) {
  return line
    .trim()
    .replace(/^#{1,6}\s+/, "")
    .replace(/\*\*/g, "")
    .replace(/:+\s*$/, "")
    .trim()
    .toLowerCase();
}

function listItem(line: string) {
  const match = line.match(/^\s*(?:[-*]|\d+[.)])\s+(.+)$/);
  if (!match) return undefined;
  const text = match[1].replace(/\*\*/g, "").replace(/!\[[^\]]*]\([^)]*\)/g, "").trim();
  if (!text || text.startsWith("![")) return undefined;
  return text;
}

export function parseRecipeSections(body: string | undefined) {
  const ingredients: string[] = [];
  const instructions: string[] = [];
  if (!body) return { ingredients, instructions };

  let section: "none" | "ingredients" | "instructions" = "none";
  for (const line of body.split("\n")) {
    if (isHeading(line)) {
      const label = headingLabel(line);
      if (label.includes("instruction")) section = "instructions";
      else if (
        label.includes("ingredient") ||
        ["filling", "wrapping", "toppings", "broth", "supplies"].some((name) => label === name || label.endsWith(` ${name}`))
      ) {
        section = "ingredients";
      }
      continue;
    }
    const item = listItem(line);
    if (!item) continue;
    if (section === "ingredients") ingredients.push(item);
    if (section === "instructions") instructions.push(item);
  }
  return { ingredients, instructions };
}

export function recipeJsonLd(options: {
  title: string;
  description?: string;
  body?: string;
  author?: string;
  image?: string;
  datePublished?: string;
}) {
  const { ingredients, instructions } = parseRecipeSections(options.body);
  if (ingredients.length === 0 && instructions.length === 0) return undefined;

  const data: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "Recipe",
    name: options.title,
  };
  if (options.description) data.description = options.description;
  if (options.image) data.image = [absoluteUrl(options.image)];
  if (options.author) data.author = { "@type": "Person", name: options.author };
  if (options.datePublished) data.datePublished = options.datePublished;
  if (ingredients.length) data.recipeIngredient = ingredients;
  if (instructions.length) {
    data.recipeInstructions = instructions.map((text) => ({ "@type": "HowToStep", text }));
  }
  return data;
}

export function jsonLdScript(data: Record<string, unknown>) {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
