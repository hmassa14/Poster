import json

from poster.evals import graders
from poster.evals.mutations import all_mutations
from poster.evals.runner import EvalOptions, EvalRunner, harness_smoke
from poster.lint import lint_draft, load_banned
from poster.policy import Policy
from poster.schemas import (Critique, Draft, EscalationDecision, EscalationHit, Issue, ResearchPack, SEOPackage, SocialPosts,
                            TriageResult, JudgeVerdict, CriterionVerdict, Candidate)
from tests.conftest import ROOT, FakeClaude
from poster.llm import LLMResult


def _pack():
    return ResearchPack.model_validate_json((ROOT / "evals/cases/research_pack.json").read_text())


def _clean():
    return (ROOT / "evals/cases/clean_draft.md").read_text()


def test_fixture_is_clean_and_grounded(project):
    md = _clean()
    rep = lint_draft(md, banned=load_banned(ROOT / "publication/banned_phrases.txt"),
                     min_words=project.editorial.target_words_min, max_words=project.editorial.target_words_max)
    assert rep.ok, rep.as_text()
    g = graders.grounding(md, _pack())
    assert g.grounded, (g.ungrounded_numbers, g.ungrounded_links)


def test_every_mutation_is_distinct_and_detectable():
    md = _clean()
    muts = all_mutations(md)
    assert len({m.id for m in muts}) == len(muts) >= 12
    for m in muts:
        assert m.markdown != md
        assert m.location in m.markdown, m.id
    # Fact mutations that invent numbers/links must trip the grounding grader.
    pack = _pack()
    by_id = {m.id: m for m in muts}
    for mid in ("number_changed", "price_changed", "unsourced_link", "number_invented"):
        assert not graders.grounding(by_id[mid].markdown, pack).grounded, mid


def test_harness_smoke_oracle_and_null(project):
    res = harness_smoke(project, Policy.load(ROOT))
    assert res["ok"], res["checks"]


def test_critic_caught_matching():
    m = all_mutations(_clean())[0]
    hit = Critique(score=5, summary="", issues=[Issue(severity="major", kind="fact", location="...p50 is 210 ms...", problem="wrong", fix="use 410 ms")], required_edits=[])
    miss = Critique(score=5, summary="", issues=[Issue(severity="minor", kind="fact", location="p50 is 210 ms", problem="", fix="")], required_edits=[])
    assert graders.critic_caught(hit, m)
    assert not graders.critic_caught(miss, m)


def test_triage_metrics_merge():
    items = json.loads((ROOT / "evals/cases/triage_items.json").read_text())["items"]
    # Surfacing g1 as two separate candidates (unmerged) plus one noise item.
    res = TriageResult(candidates=[
        Candidate(id="a", headline="x", main_url="https://halcyon.example/blog/tern-3-pricing", event_date="2026-09-08", summary="", category="models", significance=5, why_candidate=""),
        Candidate(id="b", headline="y", main_url="https://wiretap.example/2026/09/08/halcyon-tern-3-price-cut", event_date="2026-09-08", summary="", category="models", significance=4, why_candidate=""),
        Candidate(id="c", headline="z", main_url="https://techwire.example/kestrel-seed", event_date="2026-09-05", summary="", category="business", significance=1, why_candidate=""),
    ], dropped_summary="")
    m = graders.triage_metrics(res, items)
    assert m["tp"] == 1 and m["fp"] == 1 and m["merge_accuracy"] < 1


def test_seo_constraints_reject_generic_and_ungrounded_keywords():
    md = _clean()
    pkg = SEOPackage(slug="ok-slug-here", title_tag="Halcyon cuts Tern 3 pricing and publishes latency", meta_description="m" * 120,
                     headline_h1="h", excerpt="e", keywords=["AI news", "Halcyon Labs", "Tern 3", "Marlin-27B", "Cinder Compute"], tags=["models"],
                     social=SocialPosts(linkedin="l {url}", x="x {url}", threads="t"), email_subject="s", email_preheader="p",
                     og_title="o", og_description="d", image_alt="i")
    g = graders.seo_constraints(pkg, md, set())
    assert not g["pass"] and "generic keyword" in g["failures"]


class EvalFake(FakeClaude):
    """A fake that behaves like a mediocre pipeline: catches only number changes, escalates everything under every category."""

    def complete(self, *, stage, system, user, output_format=None, tools=None, model=None, effort=None, max_tokens=None):
        self.calls.append({"stage": stage, "system": system, "user": user, "model": model or "claude-opus-5", "served_by": model or "claude-opus-5",
                           "usage": {"input_tokens": 100, "output_tokens": 10}, "stop_reason": "end_turn", "output": ""})
        if output_format is Critique:
            issues = []
            if "p50 is 210 ms" in user:
                issues.append(Issue(severity="blocker", kind="fact", location="p50 is 210 ms", problem="altered", fix="410 ms"))
            score = 5 if issues else 9
            return LLMResult(text="", parsed=Critique(score=score, summary="s", issues=issues, required_edits=[]), stop_reason="end_turn", usage={}, model="claude-opus-5")
        if output_format is EscalationDecision:
            cats = ["legal_named_individual", "death_or_injury", "security_exploit", "election_or_political_persuasion",
                    "medical_legal_financial_advice", "minors", "unverified_major_claim"]
            return LLMResult(text="", parsed=EscalationDecision(requires_human_review=True, hits=[EscalationHit(category=c, passage="", reason="") for c in cats], summary=""), stop_reason="end_turn", usage={}, model="claude-opus-5")
        if output_format is JudgeVerdict:
            return LLMResult(text="", parsed=JudgeVerdict(verdicts=[CriterionVerdict(criterion_id=c, met=True, reason="") for c, _ in graders.WRITER_RUBRIC]), stop_reason="end_turn", usage={}, model="claude-sonnet-5")
        if output_format is Draft:
            return LLMResult(text="", parsed=Draft(title="T", dek="d", body_markdown=_clean(), stories_covered=[]), stop_reason="end_turn", usage={}, model="claude-opus-5")
        if output_format is SEOPackage:
            return LLMResult(text="", parsed=SEOPackage(slug="price-cut-latency-page", title_tag="Halcyon cuts Tern 3 pricing and publishes latency data",
                             meta_description="Halcyon cut Tern 3 input pricing from $2.50 to $1.00 per million tokens and published p50 and p99 latency by context tier.",
                             headline_h1="h", excerpt="e", keywords=["Halcyon Labs", "Tern 3", "Marlin-27B", "Nordic Digital Authority", "Cinder Compute"], tags=["models"],
                             social=SocialPosts(linkedin="l {url}", x="x {url}", threads="t"), email_subject="s", email_preheader="p", og_title="o", og_description="d", image_alt="i"),
                             stop_reason="end_turn", usage={}, model="claude-opus-5")
        if output_format is TriageResult:
            return LLMResult(text="", parsed=TriageResult(candidates=[], dropped_summary=""), stop_reason="end_turn", usage={}, model="claude-sonnet-5")
        raise AssertionError(f"unexpected stage {stage}")


def test_runner_end_to_end_with_fake(project, tmp_path):
    runner = EvalRunner(project, EvalFake(), Policy.load(project.root), log=lambda s: None)
    out = tmp_path / "results"
    summary = runner.run(EvalOptions(out_dir=out))
    f = summary["flows"]
    # Critic: only number_changed is caught -> recall 1/12; clean draft not falsely failed.
    assert f["critic"]["metrics"]["critic_recall"]["mean"] == round(1 / 12, 3)
    assert f["critic"]["metrics"]["critic_specificity"]["mean"] == 1.0
    assert f["critic"]["missed"] and "number_changed" not in f["critic"]["missed"]
    # Escalation: always escalating -> recall 1.0, specificity 0.0.
    assert f["escalation"]["metrics"]["escalation_recall"]["mean"] == 1.0
    assert f["escalation"]["metrics"]["escalation_specificity"]["mean"] == 0.0
    # Writer returned the grounded clean draft; judge met everything.
    assert f["writer"]["metrics"]["writer_grounded_rate"]["mean"] == 1.0
    assert f["writer"]["metrics"]["writer_rubric_mean"]["mean"] == 1.0
    assert f["triage"]["metrics"]["triage_recall"]["mean"] == 0.0
    assert f["seo"]["metrics"]["seo_constraint_pass_rate"]["mean"] == 1.0
    assert summary["thresholds"]["_all_pass"] is False
    assert summary["thresholds"]["critic_recall"]["pass"] is False
    assert (out / "critic" / "baseline" / "results.jsonl").exists()
    assert (out / "critic" / "baseline" / "traces" / "number_changed_rep0.json").exists()
    assert (out / "report.md").exists() and "critic_recall" in (out / "report.md").read_text()
    # Rerun resumes: no new rows written.
    before = (out / "critic" / "baseline" / "results.jsonl").read_text()
    runner.run(EvalOptions(out_dir=out, flows=["critic"]))
    assert (out / "critic" / "baseline" / "results.jsonl").read_text() == before
