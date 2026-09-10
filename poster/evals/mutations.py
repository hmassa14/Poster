"""Seeded-error mutations of a clean draft for the critic eval.

Each mutation injects exactly one known defect and returns the mutated
Markdown plus the expected finding. The critic eval measures whether the
fact-checker reports an issue at that location with blocker/major severity.
Mutations are deterministic (no randomness) so results are reproducible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


@dataclass
class Mutation:
    id: str
    kind: str            # fact | source | style | format | judgement
    description: str
    location: str        # a unique substring of the mutated text the critic should quote
    markdown: str


def _replace_once(text: str, old: str, new: str) -> str:
    if old not in text:
        raise ValueError(f"mutation anchor not found: {old!r}")
    return text.replace(old, new, 1)


def m_number_changed(md: str) -> Mutation:
    new = _replace_once(md, "p50 is 410 ms and p99 is 1.9 s", "p50 is 210 ms and p99 is 0.9 s")
    return Mutation("number_changed", "fact", "Latency figures altered from the source (410 ms / 1.9 s)",
                    "p50 is 210 ms", new)


def m_price_changed(md: str) -> Mutation:
    new = _replace_once(md, "down from $2.50, with output pricing unchanged at $10.00",
                        "down from $2.50, with output pricing unchanged at $8.00")
    return Mutation("price_changed", "fact", "Output price altered ($10.00 -> $8.00)", "unchanged at $8.00", new)


def m_fabricated_quote(md: str) -> Mutation:
    new = _replace_once(md, "Brightline says it [will appeal]",
                        "\"We reject the Authority's findings in their entirety and will see them in court,\" the company said. Brightline says it [will appeal]")
    return Mutation("fabricated_quote", "fact", "A quote not present in the research pack",
                    "reject the Authority's findings", new)


def m_vendor_claim_as_fact(md: str) -> Mutation:
    new = _replace_once(md, "Halcyon claims that at the new price Tern 3 is cheaper than self-hosted Marlin-27B",
                        "At the new price Tern 3 is cheaper than self-hosted Marlin-27B")
    new = _replace_once(new, "That is Halcyon's number, produced by Halcyon's own cost calculator, and it assumes a team without its own accelerators; the [pricing post](https://halcyon.example/blog/tern-3-pricing) does not show the calculation. ", "")
    return Mutation("vendor_claim_as_fact", "fact", "A vendor claim stated as established fact",
                    "At the new price Tern 3 is cheaper", new)


def m_unsourced_link(md: str) -> Mutation:
    new = _replace_once(md, "Its previous largest site had 12,000.",
                        "Its previous largest site had 12,000, and a [leaked capacity plan](https://leakboard.example/cinder-plan) shows a third site in Quebec.")
    return Mutation("unsourced_link", "source", "A link and claim not in the research pack",
                    "leaked capacity plan", new)


def m_wrong_attribution(md: str) -> Mutation:
    new = _replace_once(md, "said Priya Raman, Halcyon's head of platform", "said Ingrid Solberg, Halcyon's head of platform")
    return Mutation("wrong_attribution", "fact", "Quote attributed to the wrong person",
                    "said Ingrid Solberg, Halcyon", new)


def m_date_changed(md: str) -> Mutation:
    new = _replace_once(md, "since Tern 3 launched in May 2026", "since Tern 3 launched in March 2026")
    return Mutation("date_changed", "fact", "Launch month altered (May -> March)", "launched in March 2026", new)


def m_benchmark_condition_dropped(md: str) -> Mutation:
    new = _replace_once(md, "but that figure is pass@1 with 8 samples, while the Tern 3 [model card](https://halcyon.example/tern-3/model-card) reports pass@1 with 1 sample. The two numbers were produced under different conditions and do not support a head-to-head ranking.",
                        "and the Tern 3 [model card](https://halcyon.example/tern-3/model-card) confirms the gap, so the ranking stands.")
    return Mutation("benchmark_condition_dropped", "judgement", "Benchmark conditions removed; unlike comparison presented as settled",
                    "confirms the gap, so the ranking stands", new)


def m_banned_phrase(md: str) -> Mutation:
    new = _replace_once(md, "The price is the headline,", "This is a game-changer. The price is the headline,")
    return Mutation("banned_phrase", "style", "Banned vocabulary inserted", "This is a game-changer", new)


def m_signoff(md: str) -> Mutation:
    new = md.rstrip() + "\n\nThat's all for this week, thanks for reading and see you next week.\n"
    return Mutation("signoff", "format", "Closing sign-off added", "see you next week", new)


def m_first_person_test(md: str) -> Mutation:
    new = _replace_once(md, "A vendor volunteering its p99 is rare,", "We tested the endpoint ourselves and saw similar numbers. A vendor volunteering its p99 is rare,")
    return Mutation("first_person_test", "style", "The system claims to have tested something",
                    "We tested the endpoint", new)


def m_number_invented(md: str) -> Mutation:
    new = _replace_once(md, "The logs were previously a paid add-on with 30-day retention.",
                        "The logs were previously a paid add-on with 30-day retention that cost $4,000 per month.")
    return Mutation("number_invented", "fact", "A price not in the research pack", "$4,000 per month", new)


MUTATIONS: list[Callable[[str], Mutation]] = [
    m_number_changed, m_price_changed, m_fabricated_quote, m_vendor_claim_as_fact, m_unsourced_link,
    m_wrong_attribution, m_date_changed, m_benchmark_condition_dropped, m_banned_phrase, m_signoff,
    m_first_person_test, m_number_invented,
]


def all_mutations(clean_markdown: str) -> list[Mutation]:
    return [fn(clean_markdown) for fn in MUTATIONS]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()
