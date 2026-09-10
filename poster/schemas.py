"""Pydantic models for every artifact the pipeline produces.

These double as the structured-output schemas sent to Claude, so field
descriptions are written for the model as much as for humans.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "models", "products", "research", "policy", "infrastructure",
    "business", "safety", "open-source", "other",
]


# ---------------------------------------------------------------- ingest

class FeedItem(BaseModel):
    id: str
    title: str
    link: str
    source: str
    kind: str = "secondary"
    published: str = Field(description="ISO 8601 date or datetime")
    summary: str = ""


# ---------------------------------------------------------------- triage

class Candidate(BaseModel):
    id: str = Field(description="Short stable id, e.g. c01")
    headline: str
    main_url: str = Field(description="Best URL for the story, primary source preferred")
    other_urls: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list, description="Feed source names that carried it")
    event_date: str = Field(description="ISO date of the event, best estimate from the items")
    summary: str = Field(description="What happened, from the items only")
    category: Category
    significance: int = Field(ge=1, le=5)
    why_candidate: str = Field(description="One sentence on why this is consequential")


class TriageResult(BaseModel):
    candidates: list[Candidate]
    dropped_summary: str = Field(description="One paragraph on what was dropped and why")


# ---------------------------------------------------------------- research

class Source(BaseModel):
    title: str
    url: str
    publisher: str
    published: str = ""
    type: Literal["primary", "secondary", "analysis"]


class Fact(BaseModel):
    claim: str
    source_url: str
    verification: Literal["verified", "vendor-claim", "unverified", "disputed"]
    note: str = ""


class Quote(BaseModel):
    text: str
    speaker: str
    role: str
    source_url: str


class Story(BaseModel):
    id: str
    headline: str
    one_line: str
    category: Category
    event_date: str
    what_happened: str
    what_is_new: str = Field(description="What is actually new vs a repackaging")
    why_it_matters: str = Field(description="Concrete consequence for practitioners, buyers, builders")
    unknowns: str = Field(description="What remains unknown or is only claimed")
    facts: list[Fact]
    quotes: list[Quote] = Field(default_factory=list)
    sources: list[Source]
    past_coverage_note: str = Field(default="", description="If covered before, what is new now")
    rank: int


class NoiseCheck(BaseModel):
    claim: str
    what_evidence_supports: str
    source_urls: list[str]


class ResearchPack(BaseModel):
    issue_window_start: str
    issue_window_end: str
    stories: list[Story]
    lead_recommendation: str = Field(description="Story id and two sentences on why")
    runner_up: str
    noise_check: NoiseCheck
    research_gaps: list[str] = Field(default_factory=list, description="Things that could not be verified")


# ---------------------------------------------------------------- editor

class ItemPlan(BaseModel):
    story_id: str
    angle: str = Field(description="One-line angle for this item")
    target_words: int


class Brief(BaseModel):
    working_title: str
    alternate_titles: list[str]
    thesis: str
    lead_story_id: str
    lead_angle: str = Field(description="What the lead must explain and why it matters")
    also_this_week: list[ItemPlan]
    research_corner: list[ItemPlan] = Field(default_factory=list)
    signal_vs_noise: str
    worth_your_time: list[str] = Field(description="URLs from the pack with a one-line reason each, 'url — reason'")
    cuts: list[str] = Field(default_factory=list, description="Stories cut and why")
    corrections_to_run: list[str] = Field(default_factory=list)
    editor_notes: str = ""


# ---------------------------------------------------------------- writer

class Draft(BaseModel):
    title: str
    dek: str
    body_markdown: str = Field(description="The complete issue in Markdown, starting with the H1 title")
    stories_covered: list[str] = Field(description="Story ids used")
    writer_notes: str = ""


# ---------------------------------------------------------------- critic

class Issue(BaseModel):
    severity: Literal["blocker", "major", "minor"]
    kind: Literal["fact", "source", "format", "style", "judgement"]
    location: str = Field(description="A few quoted words locating the problem")
    problem: str
    fix: str


class Critique(BaseModel):
    score: int = Field(ge=1, le=10)
    summary: str
    issues: list[Issue]
    required_edits: list[str] = Field(description="Imperative edits for blockers and majors")


# ---------------------------------------------------------------- seo

class InternalLink(BaseModel):
    slug: str
    reason: str


class SocialPosts(BaseModel):
    linkedin: str
    x: str
    threads: str


class SEOPackage(BaseModel):
    slug: str
    title_tag: str
    meta_description: str
    headline_h1: str
    excerpt: str
    keywords: list[str]
    tags: list[str]
    internal_links: list[InternalLink] = Field(default_factory=list)
    social: SocialPosts
    email_subject: str
    email_preheader: str
    og_title: str
    og_description: str
    image_alt: str


# ---------------------------------------------------------------- feedback

class RuleChange(BaseModel):
    target: Literal["style", "format"]
    action: Literal["add", "modify", "remove"]
    rule: str = Field(description="The full text of the rule as it should appear")
    replaces: str = Field(default="", description="For modify/remove: the existing rule text being changed")
    rationale: str


class Correction(BaseModel):
    issue_id: str = Field(description="The issue the correction applies to, e.g. 2026-09-10, or 'unknown'")
    text: str = Field(description="The correction as it should be printed")


class FeedbackDigest(BaseModel):
    rule_changes: list[RuleChange] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list, description="Durable lessons for editor/research/writer")
    corrections: list[Correction] = Field(default_factory=list)
    ignored: list[str] = Field(default_factory=list)
    summary: str


# ---------------------------------------------------------------- policy

class EscalationHit(BaseModel):
    category: str = Field(description="Category id from the list provided")
    passage: str = Field(description="Exact quoted passage from the draft")
    reason: str


class EscalationDecision(BaseModel):
    requires_human_review: bool
    hits: list[EscalationHit] = Field(default_factory=list)
    summary: str


# ---------------------------------------------------------------- evals

class CriterionVerdict(BaseModel):
    criterion_id: str
    met: bool
    reason: str


class JudgeVerdict(BaseModel):
    verdicts: list[CriterionVerdict]
    overall_note: str = ""
