import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';
import { remarkRewriteImages } from './src/lib/remark-rewrite-images.mjs';

export default defineConfig({
  site: 'https://www.onepotgal.com',
  integrations: [sitemap()],
  redirects: {
    '/search': '/cookbook',
  },
  markdown: {
    remarkPlugins: [remarkRewriteImages],
  },
});
