"""Offline test fixtures: a copy of the project and a fake Claude client."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from poster.config import load_settings
from poster.llm import LLMResult
from poster.schemas import (Brief, Critique, Draft, FeedbackDigest, ItemPlan, ResearchPack, SEOPackage,
                            SocialPosts, TriageResult)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project(tmp_path: Path):
    """A throwaway copy of the repo's config, prompts, publication and templates."""
    for name in ("poster.yaml", "prompts", "publication", "templates"):
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, tmp_path / name)
        else:
            shutil.copy(src, tmp_path / name)
    for d in ("issues", "memory", "feedback/inbox", "feedback/processed", "feedback/metrics", "site"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    settings = load_settings(tmp_path)
    settings.editorial.verify_links = False
    return settings


SAMPLE_PACK = {
    "issue_window_start": "2026-09-02", "issue_window_end": "2026-09-10",
    "lead_recommendation": "s1 — the pricing change is the thing that changes buyer decisions this week.",
    "runner_up": "s2",
    "noise_check": {"claim": "Model X is 'AGI'", "what_evidence_supports": "A benchmark gain on one suite.",
                    "source_urls": ["https://example.com/noise"]},
    "research_gaps": [],
    "stories": [
        {"id": f"s{i}", "headline": f"Story {i} headline", "one_line": f"One line {i}", "category": "models",
         "event_date": "2026-09-08", "what_happened": f"Thing {i} happened.", "what_is_new": "It is new.",
         "why_it_matters": "Practitioners care.", "unknowns": "Pricing details.", "rank": i,
         "facts": [{"claim": f"Fact {i}", "source_url": f"https://example.com/s{i}", "verification": "verified"}],
         "quotes": [], "sources": [{"title": f"Source {i}", "url": f"https://example.com/s{i}", "publisher": "Example",
                                    "type": "primary"}]}
        for i in range(1, 9)
    ],
}


def sample_markdown(words_per_item: int = 24) -> str:
    filler = " ".join(["The announcement lists concrete numbers and the model card gives the conditions under which they hold, which is the part that matters for anyone deciding whether to switch."] * 3)
    items = "\n\n".join(
        f"**Story {i} headline.** The [source {i}](https://example.com/s{i}) says fact {i}. {filler}"
        for i in range(2, 8)
    )
    lead = " ".join([f"The [primary source](https://example.com/s1) lists the numbers. {filler}"] * 8)
    para = " ".join([filler] * 3)
    return f"""# The Price Is the Product

*The week's real news was a pricing table, not a model.*

## The week in one paragraph

{para} See the [details](https://example.com/s1).

## The lead: Story 1 headline

{lead} What to watch: the follow-up pricing page.

## Also this week

{items}

## Signal vs. noise

The claim that Model X is AGI rests on one [benchmark](https://example.com/noise). {filler}

## Worth your time

- [Source 8](https://example.com/s8): the technical report behind story 8.
- [Source 2](https://example.com/s2): the docs page with the full pricing table.
"""


class FakeClaude:
    """Returns canned structured objects per stage; records every call."""

    def __init__(self, trace=None) -> None:
        self.calls: list[dict] = []
        self.critic_scores = iter([6, 9, 9, 9])
        self.trace = trace

    def complete(self, *, stage, system, user, output_format=None, tools=None, model=None, effort=None, max_tokens=None):
        self.calls.append({"stage": stage, "system": system, "user": user, "tools": tools, "model": model})
        parsed = None
        text = ""
        if output_format is TriageResult:
            parsed = TriageResult(candidates=[], dropped_summary="fake")
        elif stage == "research":
            text = "# Notes\n\nStory 1 ... https://example.com/s1"
        elif output_format is ResearchPack:
            parsed = ResearchPack.model_validate(SAMPLE_PACK)
        elif output_format is Brief:
            parsed = Brief(working_title="The Price Is the Product", alternate_titles=["A", "B", "C"],
                           thesis="Pricing, not models, moved the market.", lead_story_id="s1", lead_angle="Why pricing matters",
                           also_this_week=[ItemPlan(story_id=f"s{i}", angle="x", target_words=100) for i in range(2, 8)],
                           signal_vs_noise="AGI claim", worth_your_time=["https://example.com/s8 — report"])
        elif output_format is Draft:
            parsed = Draft(title="The Price Is the Product", dek="The week's real news was a pricing table, not a model.",
                           body_markdown=sample_markdown(), stories_covered=[f"s{i}" for i in range(1, 9)])
        elif output_format is Critique:
            score = next(self.critic_scores)
            parsed = Critique(score=score, summary="fine" if score >= 8 else "needs work", issues=[],
                              required_edits=[] if score >= 8 else ["Tighten the lead."])
        elif output_format is SEOPackage:
            parsed = SEOPackage(slug="the price is the product!!", title_tag="Pricing, not models, moved the AI market this week and here is why",
                                meta_description="A pricing table changed buyer decisions more than any model launch this week.",
                                headline_h1="x", excerpt="Pricing moved the market.", keywords=["pricing", "models"],
                                tags=["models", "business"], internal_links=[],
                                social=SocialPosts(linkedin="LinkedIn {url}", x="X {url}", threads="Threads {url}"),
                                email_subject="The price is the product", email_preheader="What changed and for whom",
                                og_title="The Price Is the Product", og_description="Pricing moved the market.", image_alt="A pricing table")
        elif output_format is FeedbackDigest:
            parsed = FeedbackDigest(rule_changes=[{"target": "style", "action": "add", "rule": "Keep 'Also this week' items under 110 words.",
                                                  "rationale": "reader asked for shorter items"}],
                                    lessons=["Readers want shorter items."], corrections=[], ignored=[], summary="One style rule added.")
        if parsed is not None and not text:
            text = parsed.model_dump_json()
        if self.trace is not None:
            self.trace.record(stage=stage, model=model or "fake", usage={"input_tokens": 1000, "output_tokens": 200},
                              seconds=0.0, stop_reason="end_turn")
        return LLMResult(text=text, parsed=parsed, stop_reason="end_turn",
                         usage={"input_tokens": 1000, "output_tokens": 200}, model=model or "fake")
