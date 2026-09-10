"""Render an issue to the static site, the email HTML, RSS, and sitemap."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import Settings
from .schemas import SEOPackage


def md_to_html(text: str) -> str:
    return markdown.markdown(text, extensions=["extra", "sane_lists", "smarty"], output_format="html5")


def strip_title_and_dek(body_markdown: str) -> str:
    """The templates render title and dek themselves; remove them from the body."""
    lines = body_markdown.strip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    if lines and lines[0].startswith("*") and lines[0].rstrip().endswith("*"):
        lines = lines[1:]
    return "\n".join(lines).strip()


class Renderer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.env = Environment(loader=FileSystemLoader(str(settings.templates_dir)),
                               autoescape=select_autoescape(["html", "xml"]))
        self.env.filters["rfc2822"] = _rfc2822

    # ---- issue page and email ------------------------------------------
    def render_issue(self, *, issue_id: str, body_markdown: str, seo: SEOPackage, title: str, dek: str,
                     issues_index: list[dict[str, Any]], published_at: datetime) -> dict[str, str]:
        pub = self.settings.publication
        body_html = md_to_html(strip_title_and_dek(body_markdown))
        url = f"{pub.site_url.rstrip('/')}/issues/{seo.slug}/"
        related = [r for r in issues_index if r["slug"] in {l.slug for l in seo.internal_links}]
        json_ld = {
            "@context": "https://schema.org",
            "@type": "NewsArticle",
            "headline": title,
            "description": seo.meta_description,
            "datePublished": published_at.isoformat(),
            "dateModified": published_at.isoformat(),
            "inLanguage": pub.language,
            "keywords": ", ".join(seo.keywords),
            "mainEntityOfPage": url,
            "author": {"@type": "Organization", "name": f"{pub.name} editorial system"},
            "publisher": {"@type": "Person", "name": pub.publisher, "url": pub.publisher_url},
            "isAccessibleForFree": True,
        }
        ctx = dict(
            pub=pub, issue_id=issue_id, title=title, dek=dek, body_html=body_html, seo=seo, url=url,
            published_at=published_at, related=related, json_ld=json.dumps(json_ld, indent=1),
            disclosure=pub.disclosure, prev_issues=issues_index[-6:][::-1],
        )
        page = self.env.get_template("issue.html").render(**ctx)
        email = self.env.get_template("email.html").render(**ctx)
        return {"page": page, "email": email, "url": url}

    # ---- site-wide files -----------------------------------------------
    def render_site(self, issues_index: list[dict[str, Any]]) -> dict[str, str]:
        pub = self.settings.publication
        newest_first = sorted(issues_index, key=lambda r: r["issue_id"], reverse=True)
        now = datetime.now(timezone.utc)
        base = pub.site_url.rstrip("/")
        return {
            "index.html": self.env.get_template("index.html").render(pub=pub, issues=newest_first, disclosure=pub.disclosure, now=now),
            "feed.xml": self.env.get_template("feed.xml").render(pub=pub, issues=newest_first[:30], now=now, base=base),
            "sitemap.xml": self.env.get_template("sitemap.xml").render(pub=pub, issues=newest_first, now=now, base=base),
            "robots.txt": f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n",
            "style.css": (self.settings.templates_dir / "style.css").read_text(encoding="utf-8"),
        }

    def write_site(self, issues_index: list[dict[str, Any]], issue_pages: dict[str, str] | None = None) -> list[Path]:
        site = self.settings.site_dir
        site.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for name, content in self.render_site(issues_index).items():
            path = site / name
            path.write_text(content, encoding="utf-8")
            written.append(path)
        (site / ".nojekyll").write_text("", encoding="utf-8")
        for slug, page in (issue_pages or {}).items():
            d = site / "issues" / slug
            d.mkdir(parents=True, exist_ok=True)
            (d / "index.html").write_text(page, encoding="utf-8")
            written.append(d / "index.html")
        return written


def _rfc2822(value: datetime | str) -> str:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.strftime("%a, %d %b %Y %H:%M:%S %z")


def plain_text(body_markdown: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", body_markdown)
    text = re.sub(r"^#+ ", "", text, flags=re.M)
    text = text.replace("**", "").replace("*", "")
    return html.unescape(text)
