import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

const asDateString = (value: unknown) => {
  if (value instanceof Date) {
    const year = value.getUTCFullYear();
    const month = String(value.getUTCMonth() + 1).padStart(2, '0');
    const day = String(value.getUTCDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }
  return value;
};

const fileId = ({ entry }: { entry: string }) => entry.replace(/\\/g, '/').replace(/\.md$/, '');

const recipes = defineCollection({
  loader: glob({
    pattern: '*.md',
    base: './archive/content/recipes',
    generateId: fileId,
  }),
  schema: z.object({
    title: z.string(),
    slug: z.string().optional(),
    source: z.string().optional(),
    published: z.preprocess(asDateString, z.string()),
    excerpt: z.string().optional(),
    tags: z.array(z.string()).optional(),
    image: z.string().optional(),
  }),
});

const cookbook = defineCollection({
  loader: glob({
    pattern: ['*.md', '!index.md'],
    base: './content/cookbook',
    generateId: fileId,
  }),
  schema: z.object({
    title: z.string(),
    slug: z.string().optional(),
    author: z.string().optional(),
    credit: z.string().optional(),
    section: z.string(),
    part: z.string().optional(),
    source: z.string().optional(),
    pages: z.array(z.number()).optional(),
    images: z.array(z.string()).optional(),
  }),
});

const about = defineCollection({
  loader: glob({
    pattern: 'about.md',
    base: './archive/content',
    generateId: fileId,
  }),
  schema: z.object({
    title: z.string(),
    slug: z.string().optional(),
    source: z.string().optional(),
  }),
});

export const collections = { recipes, cookbook, about };
