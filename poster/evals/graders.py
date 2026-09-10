"""Graders: programmatic where the property is checkable, model-graded where it needs judgement."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..lint import LintReport, extract_links
from ..llm import LLMClient
from ..schemas import Critique, EscalationDecision, JudgeVerdict, ResearchPack, SEOPackage, TriageResult
from .mutations import Mutation, normalize

# ---------------------------------------------------------------- grounding

NUM_RE = re.compile(r"[$€£]?\d[\d,]*(?:\.\d+)?\s?(?:%|ms|s\b|K\b|M\b|B\b|million|billion)?")
YEAR_RE = re.compile(r"^(19|20)\d\d$")


def pack_text(pack: ResearchPack) -> str:
    return normalize(pack.model_dump_json())


def _has_number(corpus: str, needle: str) -> bool:
    """Whole-number match: '4000' must not match inside '40000'."""
    return re.search(r"(?<![\d.])" + re.escape(needle) + r"(?![\d])", corpus) is not None


@dataclass
class GroundingReport:
    ungrounded_numbers: list[str] = field(default_factory=list)
    ungrounded_links: list[str] = field(default_factory=list)

    @property
    def grounded(self) -> bool:
        return not self.ungrounded_numbers and not self.ungrounded_links


def grounding(markdown: str, pack: ResearchPack) -> GroundingReport:
    """Every number-like token and every URL in the draft must appear in the pack."""
    rep = GroundingReport()
    corpus = pack_text(pack)
    corpus_nocomma = corpus.replace(",", "")
    body = re.sub(r"\(https?://[^)]+\)", "", markdown)  # ignore digits inside URLs
    seen: set[str] = set()
    for m in NUM_RE.finditer(body):
        tok = normalize(m.group(0)).rstrip(",.")
        core = re.sub(r"[^\d.]", "", tok).rstrip(".")
        if not core or tok in seen:
            continue
        seen.add(tok)
        if len(core) == 1:      # single digits ("two of the four") are not facts worth chasing
            continue
        if _has_number(corpus, tok) or _has_number(corpus_nocomma, core):
            continue
        rep.ungrounded_numbers.append(tok)
    pack_urls = {u.rstrip("/") for u in re.findall(r"https?://[^\s\"']+", pack.model_dump_json())}
    for url in extract_links(markdown):
        if url.rstrip("/") not in pack_urls:
            rep.ungrounded_links.append(url)
    return rep


# ---------------------------------------------------------------- critic grading

def critic_caught(critique: Critique, mutation: Mutation) -> bool:
    """The critic caught the seeded error if a blocker/major issue quotes its location
    or a required edit mentions it."""
    loc = normalize(mutation.location)
    key_words = [w for w in loc.split() if len(w) > 3][:4]
    for issue in critique.issues:
        if issue.severity == "minor":
            continue
        hay = normalize(issue.location + " " + issue.problem + " " + issue.fix)
        if loc in hay or (key_words and all(w in hay for w in key_words)):
            return True
    for edit in critique.required_edits:
        hay = normalize(edit)
        if loc in hay or (key_words and all(w in hay for w in key_words)):
            return True
    return False


def critic_false_alarm(critique: Critique, min_score: int) -> bool:
    """On a clean draft, a failing score or any blocker is a false alarm."""
    return critique.score < min_score or any(i.severity == "blocker" for i in critique.issues)


# ---------------------------------------------------------------- triage grading

def triage_metrics(result: TriageResult, items: list[dict[str, Any]]) -> dict[str, float]:
    """Precision/recall on which labeled groups were surfaced, and merge accuracy."""
    url_to_item = {it["link"].rstrip("/"): it for it in items}
    surfaced_groups: dict[str, int] = {}
    surfaced_items: set[str] = set()
    for cand in result.candidates:
        urls = [cand.main_url] + list(cand.other_urls)
        groups = set()
        for u in urls:
            it = url_to_item.get(u.rstrip("/"))
            if it:
                groups.add(it["group"])
                surfaced_items.add(it["id"])
        for g in groups:
            surfaced_groups[g] = surfaced_groups.get(g, 0) + 1
    keep_groups = {it["group"] for it in items if it["keep"]}
    drop_groups = {it["group"] for it in items if not it["keep"]}
    tp = len(keep_groups & set(surfaced_groups))
    fp = len(drop_groups & set(surfaced_groups))
    fn = len(keep_groups - set(surfaced_groups))
    recall = tp / len(keep_groups) if keep_groups else 1.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    # Merge accuracy: each kept group should map to exactly one candidate.
    merged_ok = sum(1 for g in keep_groups if surfaced_groups.get(g) == 1)
    merge_acc = merged_ok / len(keep_groups) if keep_groups else 1.0
    return {"recall": round(recall, 3), "precision": round(precision, 3), "merge_accuracy": round(merge_acc, 3),
            "tp": tp, "fp": fp, "fn": fn, "candidates": len(result.candidates)}


# ---------------------------------------------------------------- escalation grading

def escalation_grade(decision: EscalationDecision, expected: list[str]) -> dict[str, Any]:
    got = {h.category for h in decision.hits}
    exp = set(expected)
    if not exp:
        correct = not decision.requires_human_review and not got
        return {"kind": "negative", "correct": correct, "got": sorted(got)}
    correct = decision.requires_human_review and bool(exp & got)
    return {"kind": "positive", "correct": correct, "got": sorted(got), "expected": sorted(exp)}


# ---------------------------------------------------------------- seo grading

def seo_constraints(seo: SEOPackage, markdown: str, existing_slugs: set[str]) -> dict[str, Any]:
    text = normalize(markdown)
    failures = []
    if not re.match(r"^[a-z0-9]+(-[a-z0-9]+){1,8}$", seo.slug):
        failures.append("slug format")
    if seo.slug in existing_slugs:
        failures.append("slug not unique")
    if len(seo.title_tag) > 60 or len(seo.title_tag) < 20:
        failures.append("title_tag length")
    if len(seo.meta_description) > 155 or len(seo.meta_description) < 100:
        failures.append("meta_description length")
    if len(seo.email_subject) > 60:
        failures.append("email_subject length")
    if len(seo.social.x) > 270:
        failures.append("x post length")
    if not (5 <= len(seo.keywords) <= 10):
        failures.append("keyword count")
    generic = {"ai", "ai news", "artificial intelligence", "technology", "news"}
    if any(k.strip().lower() in generic for k in seo.keywords):
        failures.append("generic keyword")
    ungrounded = [k for k in seo.keywords if normalize(k) not in text]
    if ungrounded:
        failures.append(f"keywords not in issue text: {ungrounded}")
    if "{url}" not in seo.social.linkedin or "{url}" not in seo.social.x:
        failures.append("social posts missing {url}")
    return {"pass": not failures, "failures": failures}


# ---------------------------------------------------------------- rubric judge

WRITER_RUBRIC = [
    ("lead_why_it_matters", "The lead section states, in concrete terms, what changes for a practitioner, buyer, or builder (not just what happened)."),
    ("vendor_claims_labeled", "Every claim that the research pack marks as a vendor claim is attributed to the vendor in the draft ('X says', 'according to X', 'X's own table'), not stated as fact."),
    ("benchmark_conditions", "Every benchmark number in the draft carries the benchmark name and the conditions the pack gives for it."),
    ("no_throat_clearing", "No sentence opens with filler such as 'It's worth noting', 'Interestingly', 'Notably', or 'In today's'."),
    ("title_evocative", "The H1 title is a short specific phrase that is not a plain restatement of the lead topic and does not contain the publication name."),
    ("unknowns_stated", "The lead names at least one thing that remains unknown or unconfirmed, drawn from the pack's unknowns."),
    ("items_lead_with_fact", "Each 'Also this week' item's first sentence states the fact with its source link, before any context or implication."),
    ("no_signoff", "The draft ends on the last item or link with no closing summary, sign-off, or call to action."),
    ("density", "Every paragraph contains at least one specific fact (a number, name, date, or quoted phrase)."),
    ("paraphrase_not_copy", "No sentence outside quotation marks reproduces a source's wording verbatim for more than a short phrase."),
]


def judge_rubric(client: LLMClient, judge_model: str, *, prompt: str, input_text: str, output_text: str,
                 rubric: list[tuple[str, str]]) -> tuple[dict[str, bool], dict[str, str], JudgeVerdict]:
    rubric_text = "\n".join(f"- {cid}: {desc}" for cid, desc in rubric)
    system = prompt + "\n\n<rubric>\n" + rubric_text + "\n</rubric>"
    user = f"<input>\n{input_text}\n</input>\n\n<output>\n{output_text}\n</output>\n\nGrade every criterion in the rubric."
    result = client.complete(stage="judge", system=system, user=user, output_format=JudgeVerdict, model=judge_model, effort="medium")
    verdict: JudgeVerdict = result.parsed
    met = {cid: False for cid, _ in rubric}
    reasons = {}
    for v in verdict.verdicts:
        if v.criterion_id in met:
            met[v.criterion_id] = v.met
            reasons[v.criterion_id] = v.reason
    return met, reasons, verdict


def lint_pass(rep: LintReport) -> bool:
    return rep.ok
