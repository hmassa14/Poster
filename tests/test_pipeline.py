import json

from poster.memory import Memory
from poster.pipeline import Pipeline, RunOptions
from poster.trace import Trace
from tests.conftest import ROOT, FakeClaude


def test_end_to_end_dry_run(project):
    trace = Trace(project.issues_dir / "2026-09-10" / "trace.jsonl")
    fake = FakeClaude(trace)
    pipe = Pipeline(project, fake, trace, log=lambda s: None)
    summary = pipe.run(RunOptions(issue_id="2026-09-10", dry_run=True, skip_feeds=True))

    d = project.issues_dir / "2026-09-10"
    for name in ("02-triage.json", "03-research.json", "04-brief.json", "05-draft.json", "06-critique-1.json",
                 "06-critique-2.json", "05-draft-r1.json", "final.md", "06b-policy.json", "07-seo.json", "issue.html", "email.html",
                 "social.md", "08-publish.json", "09-memory.json", "cost.json", "trace.jsonl"):
        assert (d / name).exists(), name

    # The critic scored 6 then 9, so exactly one revision ran.
    stages = [c["stage"] for c in fake.calls]
    assert stages == ["research", "structure", "brief", "draft", "critique-1", "revise-1", "critique-2", "policy", "seo"]
    # The research call carried the web tools; nothing else did.
    assert fake.calls[0]["tools"] and fake.calls[0]["tools"][0]["type"] == "web_search_20260209"
    assert all(c["tools"] is None for c in fake.calls[1:])

    # SEO normalisation cleaned the slug and the site was written.
    seo = json.loads((d / "07-seo.json").read_text())
    assert seo["slug"] == "the-price-is-the-product"
    site = project.site_dir
    assert (site / "index.html").exists() and (site / "feed.xml").exists() and (site / "sitemap.xml").exists()
    page = (site / "issues" / "the-price-is-the-product" / "index.html").read_text()
    assert "application/ld+json" in page and "The Price Is the Product" in page and "canonical" in page
    assert project.publication.disclosure[:40] in page
    assert "The Price Is the Product" in (site / "index.html").read_text()

    # Memory recorded coverage and the issue index.
    mem = Memory(project)
    assert len(mem.recent_coverage()) == 8
    assert mem.issues()[0]["slug"] == "the-price-is-the-product"
    assert summary["calls"] == 9

    # Second run is a no-op: every artifact exists.
    fake2 = FakeClaude()
    pipe2 = Pipeline(project, fake2, Trace(None), log=lambda s: None)
    pipe2.run(RunOptions(issue_id="2026-09-10", dry_run=True, skip_feeds=True))
    assert fake2.calls == []


def test_gate_mode_stops_before_publish(project):
    project.publishing.review_mode = "gate"
    fake = FakeClaude()
    pipe = Pipeline(project, fake, Trace(None), log=lambda s: None)
    pipe.run(RunOptions(issue_id="2026-09-10", dry_run=True, skip_feeds=True))
    d = project.issues_dir / "2026-09-10"
    assert (d / "REVIEW.md").exists()
    assert not (d / "08-publish.json").exists()


def test_prompts_include_style_and_lessons(project):
    Memory(project).add_lessons(["Never lead with a funding round."], source="test")
    fake = FakeClaude()
    Pipeline(project, fake, Trace(None), log=lambda s: None).run(
        RunOptions(issue_id="2026-09-10", dry_run=True, skip_feeds=True, stop_after="draft"))
    draft_call = next(c for c in fake.calls if c["stage"] == "draft")
    assert "<style_guide>" in draft_call["system"] and "<issue_format>" in draft_call["system"]
    assert "Never lead with a funding round." in draft_call["user"]


def test_policy_stage_escalation_gates_publish(project):
    from poster.schemas import EscalationDecision, EscalationHit
    from poster.llm import LLMResult

    class EscalatingFake(FakeClaude):
        def complete(self, *, stage, system, user, output_format=None, **kw):
            if output_format is EscalationDecision:
                self.calls.append({"stage": stage, "system": system, "user": user, "tools": None, "model": None})
                return LLMResult(text="", parsed=EscalationDecision(requires_human_review=True, summary="names a private individual",
                                 hits=[EscalationHit(category="legal_named_individual", passage="x", reason="lawsuit names an engineer")]),
                                 stop_reason="end_turn", usage={}, model="fake")
            return super().complete(stage=stage, system=system, user=user, output_format=output_format, **kw)

    fake = EscalatingFake()
    Pipeline(project, fake, Trace(None), log=lambda s: None).run(RunOptions(issue_id="2026-09-10", dry_run=True, skip_feeds=True))
    d = project.issues_dir / "2026-09-10"
    assert (d / "06b-policy.json").exists() and (d / "REVIEW.md").exists()
    assert "legal_named_individual" in (d / "REVIEW.md").read_text()
    assert not (d / "08-publish.json").exists()
    # A human acknowledges and the issue publishes.
    Pipeline(project, fake, Trace(None), log=lambda s: None).run(
        RunOptions(issue_id="2026-09-10", dry_run=True, skip_feeds=True, start_from="publish", force=True, acknowledge_escalation=True))
    assert (d / "08-publish.json").exists()
    prod = (project.root / "evals" / "production.jsonl").read_text()
    assert '"policy_escalations": 1' in prod
