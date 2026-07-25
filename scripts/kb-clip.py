#!/usr/bin/env python3
"""kb-clip.py -- deterministic web-source capture into the personal
knowledgebase vault (see scripts/kb.sh).

Fetches a URL, extracts metadata and main content with ZERO model calls
(no LLM anywhere in fetch/extract), and writes one `type: source` note
under KB_HOME/<project>/sources/<slug-of-title>.md using the vault's
LOCKED frontmatter schema. question/summary are left empty on capture --
a later classifier fills them in, never this script.

Usage:
    scripts/kb-clip.py URL [--project NAME] [--kb-home DIR]

Defaults: --project inbox, --kb-home = KB_HOME env, else ~/.knowledgebase.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import socket
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from email.message import Message
from pathlib import Path
from typing import IO

import lxml.html
from readability import Document

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
FETCH_TIMEOUT_SEC = 20
ALLOWED_URL_SCHEMES = {"http", "https"}

# CGNAT / Tailscale range. Some Python ipaddress versions still mark this
# is_global=True, so it needs its own explicit reject on top of is_global.
TAILSCALE_CGNAT_RANGE = ipaddress.ip_network("100.64.0.0/10")

# schema.org fields that mark a JSON-LD block as article-like enough to
# pull author/date/description from.
ARTICLE_LIKE_KEYS = {"headline", "datePublished", "author"}

HEADING_LEVEL = {f"h{n}": n for n in range(1, 7)}
BLOCK_XPATH = (
    ".//p | .//li | .//blockquote | .//h1 | .//h2 | .//h3 "
    "| .//h4 | .//h5 | .//h6 | .//pre"
)

FRONTMATTER_FIELDS = (
    "type", "title", "source", "author", "site", "published", "fetched",
    "description", "tags", "project", "status", "question", "summary",
)


@dataclass
class SourceMeta:
    """Parsed web-source metadata, mapped onto the LOCKED frontmatter schema."""

    title: str
    author: str
    site: str
    published: str
    description: str
    tags: list[str]


def check_url_scheme(url: str) -> None:
    """Reject any URL whose scheme is not http/https (blocks file://,
    ftp://, and other local/unintended-protocol reads via urlopen)."""
    scheme = urllib.parse.urlparse(url).scheme
    if scheme not in ALLOWED_URL_SCHEMES:
        raise ValueError(
            f"unsupported URL scheme: {scheme!r} (only http/https allowed)"
        )


def check_destination_is_public(url: str) -> None:
    """Resolve url's hostname via DNS (A + AAAA) and reject the URL if any
    resolved IP is not a public/global address. Blocks SSRF against
    loopback, private LAN, link-local incl. cloud metadata
    (169.254.169.254), CGNAT/Tailscale (100.64.0.0/10), unspecified,
    reserved, and multicast addresses -- even when reached through a
    public-looking hostname that merely resolves to one of these."""
    hostname = urllib.parse.urlparse(url).hostname
    if not hostname:
        raise ValueError(f"URL has no hostname: {url!r}")
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"could not resolve host {hostname!r}: {exc}") from exc
    for _family, _type, _proto, _canon, sockaddr in addr_info:
        ip = ipaddress.ip_address(sockaddr[0])
        is_cgnat = ip.version == 4 and ip in TAILSCALE_CGNAT_RANGE
        if not ip.is_global or is_cgnat:
            raise ValueError(
                f"destination host {hostname!r} resolves to a "
                "non-public address"
            )


class _DestinationCheckingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-runs the scheme + destination guard on every redirect hop.

    urllib's default handler auto-follows redirects, so without this a
    302 from an allowed URL to an internal target would bypass the
    pre-fetch check entirely.
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> urllib.request.Request | None:
        check_url_scheme(newurl)
        check_destination_is_public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_html(url: str) -> str:
    """Plain GET via stdlib urllib. Static pages only. Sole choke point
    for both /clip and /atomize (kb-serve.py routes both through
    kb_clip.clip -> fetch_html), so the SSRF guard here covers both.

    # ponytail: DNS-rebinding TOCTOU remains -- the guard resolves and
    # validates the hostname, then urlopen resolves it again to connect.
    # An attacker controlling DNS could flip the record between the two
    # lookups. Full mitigation would resolve once and connect to the
    # pinned IP directly. Accepted gap for a personal loopback/Tailscale
    # service with no auth boundary to defend beyond this.
    # ponytail: JS-render escalation goes here. Playwright browsers are
    # already cached at ~/.cache/ms-playwright (chromium/firefox) for a
    # future headless-render path; not built now since a plain fetch
    # already covers this tool's static-page targets.
    """
    check_url_scheme(url)
    check_destination_is_public(url)
    opener = urllib.request.build_opener(_DestinationCheckingRedirectHandler)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with opener.open(request, timeout=FETCH_TIMEOUT_SEC) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def meta_by_attr(tree: lxml.html.HtmlElement, attr: str, value: str) -> str:
    """First <meta attr="value" content="..."> content, or ''."""
    matches = tree.xpath(f'//meta[@{attr}="{value}"]/@content')
    return matches[0].strip() if matches else ""


def extract_ld_json_item(item: dict) -> dict[str, str]:
    """Pull author/published/description/headline/keywords off one
    schema.org JSON-LD dict, normalizing author to a plain name string."""
    author = item.get("author", "")
    if isinstance(author, dict):
        author = author.get("name", "")
    elif isinstance(author, list) and author and isinstance(author[0], dict):
        author = author[0].get("name", "")
    elif not isinstance(author, str):
        author = ""
    keywords = item.get("keywords", "")
    return {
        "author": author,
        "published": item.get("datePublished", ""),
        "description": item.get("description", ""),
        "headline": item.get("headline", ""),
        "keywords": keywords if isinstance(keywords, str) else "",
    }


def ld_json_fields(tree: lxml.html.HtmlElement) -> dict[str, str]:
    """First article-like <script type="application/ld+json"> block's
    fields, checked in document order. Malformed JSON is skipped."""
    for raw in tree.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and ARTICLE_LIKE_KEYS & item.keys():
                return extract_ld_json_item(item)
    return {}


def split_tags(raw: str) -> list[str]:
    """Comma-separated keywords string -> list of trimmed tags."""
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


def parse_metadata(tree: lxml.html.HtmlElement, url: str) -> SourceMeta:
    """Pull the LOCKED metadata fields from a parsed page: OG > twitter >
    ld+json > plain <meta>/<title>/<time> tags, in that priority."""
    ld_json = ld_json_fields(tree)
    title_tags = tree.xpath("//title/text()")
    raw_title = title_tags[0].strip() if title_tags else ""
    title = (
        meta_by_attr(tree, "property", "og:title")
        or meta_by_attr(tree, "name", "twitter:title")
        or ld_json.get("headline", "")
        or raw_title
    )
    time_tags = tree.xpath("//time/@datetime")
    published = (
        meta_by_attr(tree, "property", "article:published_time")
        or ld_json.get("published", "")
        or (time_tags[0].strip() if time_tags else "")
    )
    author = (
        meta_by_attr(tree, "name", "author")
        or meta_by_attr(tree, "property", "article:author")
        or ld_json.get("author", "")
    )
    description = (
        meta_by_attr(tree, "name", "description")
        or meta_by_attr(tree, "property", "og:description")
        or ld_json.get("description", "")
    )
    keywords = meta_by_attr(tree, "name", "keywords") or ld_json.get("keywords", "")
    return SourceMeta(
        title=title or url,
        author=author,
        site=meta_by_attr(tree, "property", "og:site_name"),
        published=published,
        description=description,
        tags=split_tags(keywords),
    )


def html_to_markdown(fragment: str | lxml.html.HtmlElement) -> str:
    """Convert an HTML fragment to paragraph/heading/list markdown.

    # ponytail: block granularity only (headings, paragraphs, list
    # items), no inline bold/link/emphasis markdown. Readability already
    # strips nav/ads for us, so the remaining block structure is what a
    # searchable note body actually needs; round-tripping inline markup
    # would need a second full inline-formatting pass for no real gain
    # here. A block nested inside another matched block (e.g. <p> inside
    # <li>) can double-count; rare in readability's cleaned output.
    """
    tree = lxml.html.fromstring(fragment) if isinstance(fragment, str) else fragment
    lines: list[str] = []
    for el in tree.xpath(BLOCK_XPATH):
        text = " ".join(el.text_content().split())
        if not text:
            continue
        level = HEADING_LEVEL.get(el.tag)
        if level:
            lines.append(f"{'#' * level} {text}")
        elif el.tag == "li":
            lines.append(f"- {text}")
        else:
            lines.append(text)
    return "\n\n".join(lines)


def pick_densest_container(tree: lxml.html.HtmlElement) -> lxml.html.HtmlElement | None:
    """<article>/<main> with the most extracted text, else <body> itself."""
    candidates = tree.xpath("//article | //main")
    if candidates:
        return max(candidates, key=lambda el: len(el.text_content()))
    return tree.find("body")


def extract_body_markdown(html: str) -> str:
    """Extract main content: readability-lxml first, a densest-block
    fallback second (kept for a machine without the lib installed)."""
    try:
        markdown = html_to_markdown(Document(html).summary())
        if markdown.strip():
            return markdown
    except Exception as exc:  # noqa: BLE001 readability raises many
        # parser-specific exception types across malformed real-world
        # pages; any of them means "fall back", not "crash the clip".
        print(f"kb-clip: readability extraction failed ({exc}), using fallback", file=sys.stderr)

    # ponytail: densest <article>/<main>/<p> block, nav/script/style
    # stripped first, no inline formatting. Simpler than a second full
    # readability reimplementation for the rare page that trips it up.
    tree = lxml.html.fromstring(html)
    for junk in tree.xpath("//script | //style | //nav | //header | //footer"):
        junk.drop_tree()
    root = pick_densest_container(tree)
    return html_to_markdown(root) if root is not None else ""


def slugify(text: str) -> str:
    """Lowercase, hyphenate for a filesystem-safe filename component."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "untitled"


def build_note_path(sources_dir: Path, slug: str) -> Path:
    """Pick the destination filename, suffixing on a slug collision.

    Atomically reserves the returned path with O_CREAT|O_EXCL so two
    concurrent callers racing on the same slug can never both win the same
    filename (the existence check and the reservation are one syscall,
    closing the TOCTOU window a separate ``.exists()`` check would leave
    open). Leaves the reserved file empty; callers write its real content
    with their own ``write_text()`` right after.
    """
    n = 1
    while True:
        candidate = sources_dir / (f"{slug}.md" if n == 1 else f"{slug}-{n}.md")
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            n += 1
            continue
        os.close(fd)
        return candidate


def yaml_quote(value: str) -> str:
    """Double-quote a scalar for frontmatter: escape \\ and ", collapse
    whitespace/newlines, so every value stays valid single-line YAML
    regardless of source punctuation (colons, brackets, quotes)."""
    collapsed = " ".join(value.split())
    escaped = collapsed.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def yaml_list(tags: list[str]) -> str:
    """Inline YAML list of quoted strings, e.g. tags: ["a", "b"]."""
    return "[" + ", ".join(yaml_quote(t) for t in tags) + "]"


def render_note(meta: SourceMeta, url: str, project: str, fetched: str, body: str) -> str:
    """Serialize one type:source note: LOCKED frontmatter + body + Refs."""
    frontmatter = {
        "type": "source",
        "title": meta.title,
        "source": url,
        "author": meta.author,
        "site": meta.site,
        "published": meta.published,
        "fetched": fetched,
        "description": meta.description,
        "tags": yaml_list(meta.tags),
        "project": project,
        "status": "active",
        "question": "",
        "summary": "",
    }
    lines = ["---"]
    for key in FRONTMATTER_FIELDS:
        value = frontmatter[key]
        rendered = value if key == "tags" else yaml_quote(value)
        lines.append(f"{key}: {rendered}")
    lines.append("---")
    lines.append("")
    lines.append(body)
    lines.append("")
    lines.append("## Refs")
    lines.append("")
    lines.append(f"- {url}")
    return "\n".join(lines) + "\n"


def resolve_kb_home(cli_value: str | None) -> Path:
    """--kb-home > KB_HOME env > ~/.knowledgebase."""
    if cli_value:
        return Path(cli_value)
    env = os.environ.get("KB_HOME")
    return Path(env) if env else Path.home() / ".knowledgebase"


def clip(url: str, project: str, kb_home: Path) -> Path:
    """Fetch url, extract metadata + body, write a type:source note."""
    html = fetch_html(url)
    tree = lxml.html.fromstring(html)
    meta = parse_metadata(tree, url)
    body = extract_body_markdown(html)

    sources_dir = kb_home / project / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    fetched = date.today().isoformat()
    note = render_note(meta, url, project, fetched, body)
    note_path = build_note_path(sources_dir, slugify(meta.title))
    note_path.write_text(note, encoding="utf-8")
    return note_path


def build_parser() -> argparse.ArgumentParser:
    """Construct the clip CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--project", default="inbox")
    parser.add_argument("--kb-home", default=None)
    return parser


def main(argv: list[str]) -> int:
    """CLI entry point: clip one URL into a vault project."""
    args = build_parser().parse_args(argv)
    kb_home = resolve_kb_home(args.kb_home)
    note_path = clip(args.url, args.project, kb_home)
    print(json.dumps({"path": str(note_path), "project": args.project}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
