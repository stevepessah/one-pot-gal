import type { CollectionEntry } from 'astro:content';

export const PARTS = ['Hungry, Hungry Hobans', 'The Next Generation'] as const;

export const SECTIONS = [
  'Appetizers',
  'Drinks',
  'Soups, Salads & Sides',
  'Mains',
  'Dessert',
] as const;

export function fileName(src?: string) {
  if (!src) return undefined;
  const name = decodeURIComponent(src.split('/').pop()?.split('?')[0] ?? '');
  return name || undefined;
}

export function blogImage(src?: string) {
  const name = fileName(src);
  return name ? `/media/blog/${name}` : undefined;
}

export function cookbookImage(src?: string) {
  const name = fileName(src);
  return name ? `/media/cookbook/${name}` : undefined;
}

export function formatDate(value: string) {
  const [year, month, day] = value.split('-').map(Number);
  return new Intl.DateTimeFormat('en-US', {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  }).format(new Date(year, month - 1, day));
}

export function byPublishedDesc(a: CollectionEntry<'recipes'>, b: CollectionEntry<'recipes'>) {
  return b.data.published.localeCompare(a.data.published);
}

export function isCookbookRecipe(entry: CollectionEntry<'cookbook'>) {
  return entry.data.section !== 'Introduction' && entry.data.section !== 'Glossary';
}

export function cookId(author: string) {
  return author
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
}

export function byBookOrder(a: CollectionEntry<'cookbook'>, b: CollectionEntry<'cookbook'>) {
  const partDelta = PARTS.indexOf(a.data.part as (typeof PARTS)[number]) - PARTS.indexOf(b.data.part as (typeof PARTS)[number]);
  if (partDelta) return partDelta;
  const sectionDelta =
    SECTIONS.indexOf(a.data.section as (typeof SECTIONS)[number]) -
    SECTIONS.indexOf(b.data.section as (typeof SECTIONS)[number]);
  if (sectionDelta) return sectionDelta;
  return a.data.title.localeCompare(b.data.title, 'en');
}
