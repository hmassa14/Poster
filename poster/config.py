"""Configuration: poster.yaml plus environment overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Publication:
    name: str
    tagline: str
    site_url: str
    publisher: str
    publisher_url: str
    language: str
    timezone: str
    disclosure: str


@dataclass
class Models:
    main: str
    fast: str
    effort: str
    fallbacks: bool
    max_tokens: int


@dataclass
class Research:
    lookback_days: int
    max_feed_items: int
    max_candidates: int
    max_web_searches: int
    max_web_fetches: int
    max_continuations: int


@dataclass
class Editorial:
    target_words_min: int
    target_words_max: int
    max_revision_rounds: int
    min_critic_score: int
    verify_links: bool


@dataclass
class Publishing:
    site_dir: str
    email_provider: str
    review_mode: str
    send_email: bool


@dataclass
class Feedback:
    github_repo: str
    github_label: str
    max_lessons_in_prompt: int


@dataclass
class Settings:
    root: Path
    publication: Publication
    models: Models
    research: Research
    editorial: Editorial
    publishing: Publishing
    feedback: Feedback
    raw: dict[str, Any] = field(default_factory=dict)

    # Derived paths
    @property
    def issues_dir(self) -> Path:
        return self.root / "issues"

    @property
    def memory_dir(self) -> Path:
        return self.root / "memory"

    @property
    def feedback_dir(self) -> Path:
        return self.root / "feedback"

    @property
    def publication_dir(self) -> Path:
        return self.root / "publication"

    @property
    def prompts_dir(self) -> Path:
        return self.root / "prompts"

    @property
    def templates_dir(self) -> Path:
        return self.root / "templates"

    @property
    def site_dir(self) -> Path:
        return self.root / self.publishing.site_dir


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def load_settings(root: str | Path | None = None) -> Settings:
    """Load poster.yaml from the project root, applying env overrides."""
    root_path = Path(root) if root else find_root()
    cfg_path = root_path / "poster.yaml"
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    pub = raw.get("publication", {})
    models = raw.get("models", {})
    research = raw.get("research", {})
    editorial = raw.get("editorial", {})
    publishing = raw.get("publishing", {})
    feedback = raw.get("feedback", {})

    return Settings(
        root=root_path,
        publication=Publication(
            name=pub.get("name", "This Week in AI"),
            tagline=pub.get("tagline", ""),
            site_url=os.environ.get("POSTER_SITE_URL") or pub.get("site_url", ""),
            publisher=pub.get("publisher", ""),
            publisher_url=pub.get("publisher_url", ""),
            language=pub.get("language", "en"),
            timezone=pub.get("timezone", "UTC"),
            disclosure=pub.get("disclosure", "").strip(),
        ),
        models=Models(
            main=os.environ.get("POSTER_MODEL_MAIN") or models.get("main", "claude-opus-5"),
            fast=os.environ.get("POSTER_MODEL_FAST") or models.get("fast", "claude-sonnet-5"),
            effort=os.environ.get("POSTER_EFFORT") or models.get("effort", "high"),
            fallbacks=_env_bool("POSTER_FALLBACKS", bool(models.get("fallbacks", True))),
            max_tokens=int(models.get("max_tokens", 32000)),
        ),
        research=Research(
            lookback_days=int(research.get("lookback_days", 8)),
            max_feed_items=int(research.get("max_feed_items", 300)),
            max_candidates=int(research.get("max_candidates", 40)),
            max_web_searches=int(research.get("max_web_searches", 30)),
            max_web_fetches=int(research.get("max_web_fetches", 30)),
            max_continuations=int(research.get("max_continuations", 6)),
        ),
        editorial=Editorial(
            target_words_min=int(editorial.get("target_words_min", 1400)),
            target_words_max=int(editorial.get("target_words_max", 2400)),
            max_revision_rounds=int(editorial.get("max_revision_rounds", 2)),
            min_critic_score=int(editorial.get("min_critic_score", 8)),
            verify_links=bool(editorial.get("verify_links", True)),
        ),
        publishing=Publishing(
            site_dir=publishing.get("site_dir", "site"),
            email_provider=os.environ.get("POSTER_EMAIL_PROVIDER") or publishing.get("email_provider", "dryrun"),
            review_mode=os.environ.get("POSTER_REVIEW_MODE") or publishing.get("review_mode", "auto"),
            send_email=bool(publishing.get("send_email", True)),
        ),
        feedback=Feedback(
            github_repo=os.environ.get("GITHUB_REPOSITORY") or feedback.get("github_repo", ""),
            github_label=feedback.get("github_label", "feedback"),
            max_lessons_in_prompt=int(feedback.get("max_lessons_in_prompt", 40)),
        ),
        raw=raw,
    )


def find_root(start: Path | None = None) -> Path:
    """Walk up from cwd until a poster.yaml is found."""
    here = (start or Path.cwd()).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "poster.yaml").exists():
            return candidate
    raise FileNotFoundError("poster.yaml not found in this directory or any parent")
