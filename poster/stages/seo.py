"""SEO and distribution metadata, with deterministic validation."""

from __future__ import annotations

import re

from ..config import Settings
from ..llm import LLMClient
from ..memory import Memory
from ..schemas import Draft, SEOPackage
from .common import load_prompt, publication_context

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+){1,8}$")


def make_seo(client: LLMClient, settings: Settings, memory: Memory, draft: Draft) -> SEOPackage:
    system = load_prompt(settings, "seo") + "\n\n" + publication_context(settings, include_format=False)
    user = (
        f"FINAL ISSUE MARKDOWN:\n{draft.body_markdown}\n\n"
        f"PAST ISSUES (slug: title — excerpt):\n{memory.issues_text()}\n\n"
        f"Site URL: {settings.publication.site_url}\n"
        "Produce the package now."
    )
    result = client.complete(stage="seo", system=system, user=user, output_format=SEOPackage, effort="medium")
    seo: SEOPackage = result.parsed
    return normalize_seo(seo, draft, existing_slugs={r["slug"] for r in memory.issues()})


def normalize_seo(seo: SEOPackage, draft: Draft, existing_slugs: set[str]) -> SEOPackage:
    """Enforce hard limits deterministically rather than trusting the model."""
    slug = seo.slug.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    if not SLUG_RE.match(slug):
        slug = re.sub(r"[^a-z0-9]+", "-", draft.title.lower()).strip("-")[:60].rstrip("-")
    base, n = slug, 2
    while slug in existing_slugs:
        slug = f"{base}-{n}"
        n += 1
    seo.slug = slug
    seo.title_tag = _clip(seo.title_tag, 60)
    seo.meta_description = _clip(seo.meta_description, 155)
    seo.email_subject = _clip(seo.email_subject, 60)
    seo.email_preheader = _clip(seo.email_preheader, 100)
    seo.headline_h1 = draft.title
    seo.keywords = [k.strip() for k in seo.keywords if k.strip()][:10]
    seo.tags = [t.strip().lower() for t in seo.tags if t.strip()][:6]
    seo.internal_links = [l for l in seo.internal_links if l.slug in existing_slugs][:3]
    seo.social.x = _clip(seo.social.x, 270)
    seo.social.threads = _clip(seo.social.threads, 290)
    return seo


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:-") + ("…" if not cut.endswith((".", "!", "?")) else "")
