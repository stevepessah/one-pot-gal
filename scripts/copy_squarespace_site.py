#!/usr/bin/env python3
"""Copy the public one pot gal Squarespace site into archive/."""

from __future__ import annotations

import json
import re
import ssl
import time
from html import unescape
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1] / "archive"
ORIGIN = "https://www.onepotgal.com"
USER_AGENT = "one-pot-gal-site-copy/1.0 (owner archive before Squarespace disconnect)"
CTX = ssl.create_default_context()


def fetch(url: str, accept: str | None = None, timeout: int = 60) -> tuple[bytes, str]:
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout, context=CTX) as response:
        content_type = response.headers.get("Content-Type", "")
        return response.read(), content_type


def fetch_json(url: str) -> dict:
    body, _ = fetch(url, accept="application/json")
    return json.loads(body.decode("utf-8"))


def fetch_text(url: str) -> str:
    body, _ = fetch(url, accept="text/html")
    return body.decode("utf-8", "replace")


def abs_url(src: str) -> str:
    src = src.replace("&amp;", "&").strip()
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return ORIGIN + src
    return src


def image_base(src: str) -> str:
    src = abs_url(src).split("?", 1)[0].split("&", 1)[0]
    return src.rstrip("\\")


def unquote_full(value: str) -> str:
    previous = None
    while previous != value:
        previous = value
        value = unquote(value)
    return value


def asset_filename(src: str) -> str:
    path = unquote_full(urlparse(image_base(src)).path)
    parts = [part for part in path.split("/") if part]
    asset = parts[-2] if len(parts) >= 2 else "asset"
    name = parts[-1] if parts else "image"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "image"
    return f"{asset}-{safe}"


def is_content_image(url: str) -> bool:
    path = urlparse(url).path
    if not path or path.endswith("/"):
        return False
    name = path.rsplit("/", 1)[-1].lower()
    if name.endswith((".css", ".js", ".svg", ".html")):
        return False
    return "images.squarespace-cdn.com/content/v1/" in url


def plain_excerpt(html: str | None) -> str:
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    return " ".join(unescape(text).replace("\xa0", " ").split())


def iso_date(ms: int | None) -> str | None:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()


def _clean_inline(raw: str) -> str:
    text = raw.replace("\xa0", " ")
    text = re.sub(r"\x00https?:[^ \x00]*\x00", "", text)
    lines = [" ".join(line.split()) for line in text.split("\n")]
    text = "\n".join(line for line in lines if line).strip()
    text = re.sub(r"\*\*\s+\*\*", "", text)
    text = re.sub(r"(?<!\*)\*\s+\*(?!\*)", "", text)
    text = re.sub(r"\[\s*\]\([^)]*\)", "", text)
    return text.strip()


class SquarespaceToMarkdown(HTMLParser):
    """Convert a Squarespace layout into ordered markdown blocks.

    Capture depth is tracked explicitly so nested divs do not end the text region early.
    """

    VOID = {"img", "br", "hr", "source", "meta", "link"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict] = []
        self._div_depth = 0
        self._capture_until: int | None = None
        self._skip_until: int | None = None
        self._tag_depth = 0
        self._caption_until: int | None = None
        self._buf: list[str] = []
        self._block: str | None = None
        self._lists: list[tuple[str, int]] = []
        self._link: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        classes = set(attr.get("class", "").split())
        if tag not in self.VOID:
            self._tag_depth += 1
        if tag == "div":
            self._div_depth += 1
            if "sqs-html-content" in classes and self._capture_until is None:
                self._capture_until = self._div_depth
        if tag in {"script", "style"} and self._skip_until is None:
            self._skip_until = self._tag_depth
            return
        if self._skip_until is not None:
            return
        if tag == "figcaption" and self._caption_until is None:
            self._flush()
            self._caption_until = self._tag_depth
            self._buf = []
            return
        if self._caption_until is not None:
            if tag == "br":
                self._buf.append("\n")
            return
        if tag == "img":
            src = attr.get("data-image") or attr.get("data-src") or attr.get("src") or ""
            if "squarespace" in src or src.startswith("//"):
                self._flush()
                self.blocks.append(
                    {
                        "type": "image",
                        "src": image_base(src),
                        "alt": attr.get("alt", "").strip(),
                        "caption": "",
                    }
                )
            return
        if self._capture_until is None:
            return
        if tag in {"ul", "ol"}:
            self._lists.append((tag, 0))
        elif tag == "li":
            self._flush()
            self._block = "li"
        elif tag in {"p", "h1", "h2", "h3", "h4", "h5", "h6"}:
            if tag == "p" and self._block == "li":
                if self._buf:
                    self._buf.append("\n")
                return
            self._flush()
            self._block = tag
        elif tag in {"strong", "b"}:
            self._buf.append("**")
        elif tag in {"em", "i"}:
            self._buf.append("*")
        elif tag == "br":
            self._buf.append("\n")
        elif tag == "a":
            self._link = abs_url(attr.get("href", ""))
            self._buf.append("[")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li"} and self._block == tag:
            self._flush()
        if self._capture_until is not None and self._caption_until is None and self._skip_until is None:
            if tag in {"strong", "b"}:
                self._buf.append("**")
            elif tag in {"em", "i"}:
                self._buf.append("*")
            elif tag == "a" and self._link is not None:
                self._buf.append(f"]({self._link})")
                self._link = None
            elif tag in {"ul", "ol"} and self._lists and self._lists[-1][0] == tag:
                self._lists.pop()
        if tag == "figcaption" and self._caption_until is not None and self._tag_depth == self._caption_until:
            caption = _clean_inline("".join(self._buf))
            self._buf = []
            self._caption_until = None
            if caption and self.blocks and self.blocks[-1]["type"] == "image":
                self.blocks[-1]["caption"] = caption
        if tag in {"script", "style"} and self._skip_until is not None and self._tag_depth == self._skip_until:
            self._skip_until = None
        if tag not in self.VOID:
            if tag == "div" and self._capture_until is not None and self._div_depth == self._capture_until:
                self._flush()
                self._capture_until = None
            if tag == "div":
                self._div_depth -= 1
            self._tag_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_until is not None:
            return
        if self._caption_until is not None or (self._capture_until is not None and self._block):
            self._buf.append(data)

    def _flush(self) -> None:
        text = _clean_inline("".join(self._buf))
        self._buf = []
        tag = self._block
        self._block = None
        if not text or not tag:
            return
        if tag == "li":
            if self._lists and self._lists[-1][0] == "ol":
                kind, count = self._lists[-1]
                count += 1
                self._lists[-1] = (kind, count)
                text = f"{count}. {text}"
            else:
                text = f"- {text}"
        elif tag and tag.startswith("h") and len(tag) == 2 and tag[1].isdigit():
            text = f"{'#' * int(tag[1])} {text}"
        self.blocks.append({"type": "text", "text": text})

    def close(self) -> None:
        self._flush()
        super().close()


def blocks_from_html(html: str) -> list[dict]:
    parser = SquarespaceToMarkdown()
    parser.feed(html)
    parser.close()
    return parser.blocks


def render_markdown(blocks: list[dict], images: dict[str, str]) -> str:
    lines: list[str] = []
    for block in blocks:
        if block["type"] == "text":
            lines.append(block["text"])
            lines.append("")
            continue
        src = block["src"]
        local = images.get(src, src)
        alt = (block.get("alt") or "").replace("[", "").replace("]", "")
        lines.append(f"![{alt}]({local})")
        lines.append("")
        if block.get("caption"):
            lines.append(f"*{block['caption']}*")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def collect_image_urls(*html_blobs: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    pattern = re.compile(
        r'(?:https?:)?//(?:images\.squarespace-cdn\.com|static1\.squarespace\.com)/[^"\s\\<>]+'
    )
    for blob in html_blobs:
        for match in pattern.findall(blob):
            base = image_base(match.rstrip(".,)"))
            if base in seen or not is_content_image(base):
                continue
            seen.add(base)
            found.append(base)
    return found


def download_image(src: str, dest_dir: Path) -> tuple[str, str | None]:
    filename = asset_filename(src)
    dest = dest_dir / filename
    if dest.exists() and dest.stat().st_size > 100:
        return src, f"images/{filename}"
    accept = "image/jpeg,image/png,*/*;q=0.1"
    candidates = [src + "?format=2500w", src]
    body = b""
    content_type = ""
    last_error: Exception | None = None
    for url in candidates:
        try:
            body, content_type = fetch(url, accept=accept)
            if body and len(body) > 100:
                break
        except (HTTPError, URLError) as error:
            last_error = error
            body = b""
    if len(body) < 100:
        print(f"  skip {src} ({last_error})")
        return src, None
    if "png" in content_type and not filename.lower().endswith(".png"):
        filename = Path(filename).stem + ".png"
        dest = dest_dir / filename
    elif "jpeg" in content_type and not filename.lower().endswith((".jpg", ".jpeg")):
        filename = Path(filename).stem + ".jpg"
        dest = dest_dir / filename
    elif "webp" in content_type and not filename.lower().endswith(".webp"):
        filename = Path(filename).stem + ".webp"
        dest = dest_dir / filename
    dest.write_bytes(body)
    return src, f"images/{filename}"


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    started = time.time()
    for folder in ("raw/recipes", "data/recipes", "content/recipes", "images"):
        (ROOT / folder).mkdir(parents=True, exist_ok=True)

    print("fetching site json")
    home_json = fetch_json(ORIGIN + "/?format=json")
    about_json = fetch_json(ORIGIN + "/about?format=json")
    recipes_json = fetch_json(ORIGIN + "/recipes?format=json")
    items = recipes_json["items"]

    pages = {
        "home": ORIGIN + "/",
        "about": ORIGIN + "/about",
        "recipes": ORIGIN + "/recipes",
    }
    raw_html: dict[str, str] = {}
    for name, url in pages.items():
        print("html", url)
        html = fetch_text(url)
        raw_html[name] = html
        (ROOT / "raw" / f"{name}.html").write_text(html, encoding="utf-8")

    recipe_payloads = []
    for item in items:
        slug = item["urlId"]
        url = ORIGIN + item["fullUrl"]
        print("recipe", slug)
        detail = fetch_json(url + "?format=json")["item"]
        html = fetch_text(url)
        (ROOT / "raw" / "recipes" / f"{slug}.html").write_text(html, encoding="utf-8")
        raw_html[slug] = html
        recipe_payloads.append(detail)
        slim = {
            "id": detail.get("id"),
            "title": detail.get("title"),
            "slug": detail.get("urlId"),
            "url": url,
            "published": iso_date(detail.get("publishOn")),
            "updated": iso_date(detail.get("updatedOn")),
            "excerpt": plain_excerpt(detail.get("excerpt")),
            "tags": detail.get("tags") or [],
            "categories": detail.get("categories") or [],
            "featuredImage": image_base(detail["assetUrl"]) if detail.get("assetUrl") else None,
            "bodyHtml": detail.get("body") or "",
            "seo": detail.get("seoData") or {},
        }
        write_json(ROOT / "data" / "recipes" / f"{slug}.json", slim)

    website = home_json["website"]
    social = website.get("socialAccounts") or []
    instagram = next((account.get("profileUrl") for account in social if account.get("profileUrl")), None)
    logo = website.get("logoImageUrl")
    logo_url = abs_url(logo) if logo else None

    blobs = list(raw_html.values()) + [about_json.get("mainContent") or ""]
    blobs += [item.get("body") or "" for item in recipe_payloads]
    if logo_url:
        blobs.append(logo_url)
    image_urls = collect_image_urls(*blobs)
    # Featured images can be absent from the HTML src set when lazy-loaded differently.
    for item in recipe_payloads:
        if item.get("assetUrl"):
            base = image_base(item["assetUrl"])
            if base not in image_urls:
                image_urls.append(base)

    print(f"downloading {len(image_urls)} images")
    images: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(download_image, src, ROOT / "images") for src in image_urls]
        for future in as_completed(futures):
            src, local = future.result()
            if local:
                images[src] = local
                print(" ", local)

    def rel_for(content_path: Path, local: str | None) -> str | None:
        if not local:
            return None
        return Path(os_rel(content_path.parent, ROOT / local)).as_posix()

    about_blocks = blocks_from_html(about_json.get("mainContent") or "")
    about_md_path = ROOT / "content" / "about.md"
    about_body = render_markdown(about_blocks, {src: rel_for(about_md_path, local) or src for src, local in images.items()})
    about_title = (about_json.get("collection") or {}).get("title") or "About"
    about_md_path.write_text(
        "\n".join(
            [
                "---",
                f"title: {about_title}",
                "slug: about",
                f"source: {ORIGIN}/about",
                "---",
                "",
                about_body,
            ]
        ),
        encoding="utf-8",
    )

    recipe_index_lines = [
        "---",
        "title: Recipes",
        "slug: recipes",
        f"source: {ORIGIN}/recipes",
        "---",
        "",
        "# Recipes",
        "",
    ]
    content_recipes = []
    for detail in recipe_payloads:
        slug = detail["urlId"]
        title = unescape(detail.get("title") or slug)
        url = ORIGIN + detail["fullUrl"]
        excerpt = plain_excerpt(detail.get("excerpt"))
        published = iso_date(detail.get("publishOn"))
        featured = image_base(detail["assetUrl"]) if detail.get("assetUrl") else None
        md_path = ROOT / "content" / "recipes" / f"{slug}.md"
        local_images = {src: rel_for(md_path, local) or src for src, local in images.items()}
        blocks = blocks_from_html(detail.get("body") or "")
        featured_local = local_images.get(featured) if featured else None
        body_has_featured = featured is not None and any(
            block.get("src") == featured for block in blocks if block["type"] == "image"
        )
        body = render_markdown(blocks, local_images)
        if featured_local and not body_has_featured:
            alt = title.replace("[", "").replace("]", "")
            body = f"![{alt}]({featured_local})\n\n" + body
        tags = detail.get("tags") or []
        front = [
            "---",
            f"title: {yaml_quote(title)}",
            f"slug: {slug}",
            f"source: {url}",
            f"published: {published or ''}",
            f"excerpt: {yaml_quote(excerpt)}",
            "tags: [" + ", ".join(yaml_quote(tag) for tag in tags) + "]",
        ]
        if featured_local:
            front.append(f"image: {featured_local}")
        front += ["---", "", f"# {title}", ""]
        if excerpt:
            front += [excerpt, ""]
        md_path.write_text("\n".join(front) + "\n" + body, encoding="utf-8")
        content_recipes.append(
            {
                "title": title,
                "slug": slug,
                "url": url,
                "published": published,
                "excerpt": excerpt,
                "tags": tags,
                "image": images.get(featured) if featured else None,
            }
        )
        recipe_index_lines.append(f"- [{title}](recipes/{slug}.md) — {published or 'undated'}")
        if excerpt:
            recipe_index_lines.append(f"  {excerpt}")

    (ROOT / "content" / "recipes.md").write_text("\n".join(recipe_index_lines) + "\n", encoding="utf-8")

    home_sections = extract_home_sections(raw_html["home"])
    home_md = [
        "---",
        "title: one pot gal",
        "slug: home",
        f"source: {ORIGIN}/",
        "---",
        "",
        "# one pot gal",
        "",
        "Navigation: home, recipes, about.",
        "",
        f"Instagram: {instagram or ''}",
        "",
        "Fonts on the live site: Playfair Display for headlines, Libre Franklin for body text, Fjalla One for small labels.",
        "",
    ]
    home_image_map = {src: rel_for(ROOT / "content" / "home.md", local) or src for src, local in images.items()}
    for section in home_sections:
        home_md.append(f"## {section['label']}")
        home_md.append("")
        for paragraph in section["text"]:
            home_md.append(paragraph)
            home_md.append("")
        for src in section["images"]:
            local = home_image_map.get(src, src)
            home_md.append(f"![]({local})")
            home_md.append("")
    (ROOT / "content" / "home.md").write_text("\n".join(home_md).rstrip() + "\n", encoding="utf-8")

    site = {
        "title": website.get("siteTitle"),
        "tagline": website.get("siteTagLine"),
        "description": website.get("siteDescription"),
        "url": ORIGIN + "/",
        "instagram": instagram,
        "logo": images.get(image_base(logo_url)) if logo_url else None,
        "navigation": [
            {"label": "home", "path": "/"},
            {"label": "recipes", "path": "/recipes"},
            {"label": "about", "path": "/about"},
        ],
        "fonts": ["Playfair Display", "Libre Franklin", "Fjalla One"],
        "copiedOn": datetime.now(timezone.utc).isoformat(),
        "publicRecipeCount": len(content_recipes),
        "squarespaceItemCount": recipes_json.get("collection", {}).get("itemCount"),
        "tags": recipes_json.get("collection", {}).get("tags") or [],
        "recipes": content_recipes,
        "homepageSections": [
            {"id": section["id"], "label": section["label"], "text": section["text"]}
            for section in home_sections
        ],
        "images": images,
    }
    write_json(ROOT / "data" / "site.json", site)
    write_json(
        ROOT / "data" / "about.json",
        {
            "title": about_title,
            "url": ORIGIN + "/about",
            "bodyHtml": about_json.get("mainContent") or "",
            "seo": (about_json.get("collection") or {}).get("seoData") or {},
        },
    )

    readme = f"""# one pot gal site archive

Copied from {ORIGIN}/ on {site['copiedOn']}.

This is the public Squarespace site: home, about, and {len(content_recipes)} published recipes. Squarespace reported {site['squarespaceItemCount']} collection items; only the {len(content_recipes)} posts in the public RSS feed and sitemap were available to copy.

## Layout

- `content/` — readable pages for the rebuild. Recipes are markdown with local image paths.
- `images/` — photos, logo, and homepage images, saved at the largest size Squarespace serves (up to 2500px; some uploads are smaller).
- `data/` — titles, dates, excerpts, tags, and the original Squarespace HTML for each page.
- `raw/` — full HTML responses from the live site.
- `sitemap.xml` — the public sitemap at copy time.

The family cookbook in the project `content/cookbook/` folder is separate from this Squarespace blog.
"""
    (ROOT / "README.md").write_text(readme, encoding="utf-8")
    print(f"done in {time.time() - started:.1f}s — {len(content_recipes)} recipes, {len(images)} images")


def os_rel(start: Path, target: Path) -> str:
    return Path(relpath(target, start)).as_posix()


def relpath(target: Path, start: Path) -> str:
    return str(Path(__file__).with_name("_unused") and __import__("os").path.relpath(target, start))


def yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def extract_home_sections(html: str) -> list[dict]:
    sections = []
    pattern = re.compile(r'<section id="([^"]+)" class="([^"]*Index-page[^"]*)"[^>]*>', re.I)
    matches = list(pattern.finditer(html))
    labels = {
        "share-your-vision": "Share your vision",
        "describe-what-youre-all-about": "Describe what you're all about",
        "banner": "Banner",
        "recent-recipes": "Recent recipes",
    }
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else html.find('<nav class="Index-nav">', match.end())
        if end < 0:
            end = match.end() + 5000
        chunk = html[match.start() : end]
        chunk = re.sub(r"<script[\s\S]*?</script>", " ", chunk)
        chunk = re.sub(r"<style[\s\S]*?</style>", " ", chunk)
        images = []
        for src in re.findall(r'data-image="([^"]+)"', chunk):
            base = image_base(src)
            if base not in images:
                images.append(base)
        text_only = re.sub(r"<[^>]+>", "\n", chunk)
        paragraphs = []
        for line in text_only.splitlines():
            line = " ".join(line.replace("\xa0", " ").replace("&nbsp;", " ").replace("&amp;", "&").split())
            if not line or line in {"Scroll"}:
                continue
            if paragraphs and paragraphs[-1] == line:
                continue
            paragraphs.append(line)
        section_id = match.group(1)
        sections.append(
            {
                "id": section_id,
                "label": labels.get(section_id, section_id),
                "text": paragraphs,
                "images": images,
            }
        )
    return sections


if __name__ == "__main__":
    main()
