/** Point markdown photos at the public image folders without moving the source files. */
export function remarkRewriteImages() {
  return (tree) => {
    walk(tree);
  };
}

function walk(node) {
  if (!node || typeof node !== 'object') return;
  if (node.type === 'image' && typeof node.url === 'string') {
    node.url = publicImage(node.url);
  }
  if (Array.isArray(node.children)) {
    for (const child of node.children) walk(child);
  }
}

function publicImage(url) {
  if (url.startsWith('http://') || url.startsWith('https://') || url.startsWith('/')) return url;
  const filename = decodeURIComponent(url.split('/').pop()?.split('?')[0] ?? '');
  if (!filename) return url;
  if (url.startsWith('images/')) return `/media/cookbook/${filename}`;
  if (url.includes('/images/')) return `/media/blog/${filename}`;
  return url;
}
