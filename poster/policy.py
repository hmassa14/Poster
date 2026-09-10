"""Policy as code: deterministic content checks, PII scrubbing, escalation, cost caps.

The rules live in policy.yaml; the human-readable policies they implement are
in docs/policies/. This module never decides editorial quality (that is the
critic's job); it decides whether publishing is *allowed*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .config import Settings
from .llm import LLMClient
from .schemas import EscalationDecision

QUOTE_RE = re.compile(r'"([^"\n]{20,})"|“([^”\n]{20,})”')


@dataclass
class Policy:
    raw: dict[str, Any]

    @classmethod
    def load(cls, root: Path) -> "Policy":
        path = root / "policy.yaml"
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {})

    @property
    def content(self) -> dict[str, Any]:
        return self.raw.get("content", {})

    @property
    def escalation(self) -> dict[str, Any]:
        return self.raw.get("escalation", {})

    @property
    def operations(self) -> dict[str, Any]:
        return self.raw.get("operations", {})

    @property
    def thresholds(self) -> dict[str, float]:
        return self.raw.get("evals", {}).get("thresholds", {})

    @property
    def judge_model(self) -> str:
        return self.raw.get("evals", {}).get("judge_model", "claude-sonnet-5")


@dataclass
class PolicyReport:
    violations: list[str] = field(default_factory=list)   # block publishing
    escalations: list[str] = field(default_factory=list)  # force human review
    notes: list[str] = field(default_factory=list)

    @property
    def publishable(self) -> bool:
        return not self.violations

    @property
    def needs_review(self) -> bool:
        return bool(self.escalations)

    def as_dict(self) -> dict[str, Any]:
        return {"publishable": self.publishable, "needs_review": self.needs_review,
                "violations": self.violations, "escalations": self.escalations, "notes": self.notes}


# ---------------------------------------------------------------- content checks

def check_content(markdown: str, policy: Policy, *, rendered_html: str | None = None,
                  disclosure: str = "") -> PolicyReport:
    rep = PolicyReport()
    c = policy.content

    # Quotation limits.
    max_words = int(c.get("max_quote_words", 40))
    quotes = [q[0] or q[1] for q in QUOTE_RE.findall(markdown)]
    for q in quotes:
        n = len(q.split())
        if n > max_words:
            rep.violations.append(f"quote of {n} words exceeds the {max_words}-word limit: \"{q[:60]}...\"")
    max_per_source = int(c.get("max_quotes_per_source", 2))
    if len(quotes) > max_per_source * 6:
        rep.notes.append(f"{len(quotes)} quoted passages; check quotes-per-source in the critique")

    # PII.
    for pat in c.get("pii_patterns", []):
        for m in re.finditer(pat, markdown):
            frag = m.group(0)
            if "@" in frag:
                rep.violations.append(f"personal data in issue: {frag}")
            elif not _inside_link(markdown, m.start()):
                rep.violations.append(f"possible phone number in issue: {frag.strip()}")

    # Forbidden assertions in the publication's own voice.
    for rule in c.get("forbidden_assertions", []):
        m = re.search(rule["pattern"], markdown, re.I)
        if m:
            rep.violations.append(f"{rule['reason']}: \"{markdown[max(0, m.start()-30):m.end()+30].strip()}\"")

    # Disclosure on the rendered artifact.
    if c.get("require_disclosure", True) and rendered_html is not None:
        probe = disclosure[:60] if disclosure else ""
        if probe and probe not in rendered_html:
            rep.violations.append("rendered page is missing the AI-authorship disclosure")

    # Deterministic escalation backstop.
    for pat in policy.escalation.get("keyword_backstop", []):
        m = re.search(pat, markdown, re.I)
        if m:
            rep.escalations.append(f"keyword backstop matched: \"{markdown[max(0, m.start()-20):m.end()+20].strip()}\"")
    return rep


def _inside_link(markdown: str, pos: int) -> bool:
    before = markdown[:pos]
    return before.rfind("](") > before.rfind(")")


# ---------------------------------------------------------------- escalation classifier

def classify_escalation(client: LLMClient, settings: Settings, policy: Policy, markdown: str) -> EscalationDecision:
    from .stages.common import load_prompt

    cats = policy.escalation.get("categories", [])
    cat_text = "\n".join(f"- {c['id']}: {c['description']}" for c in cats)
    system = load_prompt(settings, "escalation") + "\n\n<escalation_categories>\n" + cat_text + "\n</escalation_categories>"
    user = f"<draft>\n{markdown}\n</draft>\n\nDecide whether this draft requires human review before publication."
    result = client.complete(stage="policy", system=system, user=user, output_format=EscalationDecision, effort="medium")
    decision: EscalationDecision = result.parsed
    valid = {c["id"] for c in cats}
    decision.hits = [h for h in decision.hits if h.category in valid]
    decision.requires_human_review = decision.requires_human_review or bool(decision.hits)
    return decision


# ---------------------------------------------------------------- feedback hygiene

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
INSTRUCTION_RE = re.compile(r"(ignore (all |the )?(previous|prior|above) instructions|you are now|system prompt|disregard)", re.I)


def scrub_pii(text: str) -> str:
    text = EMAIL_RE.sub("[email removed]", text)
    text = PHONE_RE.sub("[phone removed]", text)
    return text


def looks_like_injection(text: str) -> bool:
    return bool(INSTRUCTION_RE.search(text))


# ---------------------------------------------------------------- operations

def check_cost(policy: Policy, est_cost_usd: float, *, kind: str = "issue") -> str | None:
    key = "max_cost_usd_per_issue" if kind == "issue" else "max_cost_usd_per_feedback_run"
    cap = float(policy.operations.get(key, 0) or 0)
    if cap and est_cost_usd > cap:
        return f"estimated cost ${est_cost_usd:.2f} exceeds the {kind} cap of ${cap:.2f}"
    return None


def check_models(policy: Policy, *models: str) -> list[str]:
    allowed = set(policy.operations.get("allowed_models", []))
    if not allowed:
        return []
    return [m for m in models if m not in allowed]
