"""Deterministic checks on a draft: format headings, length, banned phrases, links."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
H2_RE = re.compile(r"^## (.+)$", re.MULTILINE)
H1_RE = re.compile(r"^# (.+)$", re.MULTILINE)

REQUIRED_H2 = ["The week in one paragraph", "The lead:", "Also this week", "Signal vs. noise", "Worth your time"]
OPTIONAL_H2 = ["Research corner", "Corrections"]
SIGNOFF_RE = re.compile(r"(see you next week|until next (time|week)|that'?s all for this week|thanks for reading)", re.I)


@dataclass
class LintReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    word_count: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_text(self) -> str:
        lines = [f"word_count: {self.word_count}"]
        lines += [f"ERROR: {e}" for e in self.errors]
        lines += [f"WARN: {w}" for w in self.warnings]
        return "\n".join(lines)


def load_banned(path: Path) -> list[str]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line.lower())
    return out


def word_count(markdown: str) -> int:
    text = LINK_RE.sub(r"\1", markdown)
    text = re.sub(r"[#*_>`]", " ", text)
    return len([w for w in text.split() if w.strip()])


def lint_draft(markdown: str, *, banned: list[str], min_words: int, max_words: int) -> LintReport:
    rep = LintReport(word_count=word_count(markdown))

    # Title and dek
    h1s = H1_RE.findall(markdown)
    if len(h1s) != 1:
        rep.errors.append(f"expected exactly one H1 title, found {len(h1s)}")
    else:
        if len(h1s[0]) > 90:
            rep.warnings.append("title longer than 90 characters")
        if re.match(r"^(this week in ai|issue|#)", h1s[0].strip(), re.I):
            rep.errors.append("title restates the publication name or issue number")

    # Sections
    h2s = [h.strip() for h in H2_RE.findall(markdown)]
    for req in REQUIRED_H2:
        if not any(h.startswith(req) for h in h2s):
            rep.errors.append(f"missing required section: '{req}'")
    for h in h2s:
        if not any(h.startswith(x) for x in REQUIRED_H2 + OPTIONAL_H2):
            rep.errors.append(f"unexpected section heading: '{h}'")
    if re.search(r"^### ", markdown, re.M):
        rep.errors.append("H3 headings are not allowed")
    order = [next((i for i, r in enumerate(REQUIRED_H2 + OPTIONAL_H2) if h.startswith(r)), 99) for h in h2s]
    canonical = ["The week in one paragraph", "The lead:", "Also this week", "Research corner",
                 "Signal vs. noise", "Worth your time", "Corrections"]
    pos = [next((i for i, c in enumerate(canonical) if h.startswith(c)), 99) for h in h2s]
    if pos != sorted(pos):
        rep.errors.append("sections are out of order; follow publication/format.md")
    del order

    # Length
    if rep.word_count < min_words:
        rep.errors.append(f"too short: {rep.word_count} words < {min_words}")
    if rep.word_count > max_words:
        rep.errors.append(f"too long: {rep.word_count} words > {max_words}")

    # "Also this week" items: bold headline + link in first sentence
    also = _section(markdown, "Also this week")
    if also:
        items = [p for p in re.split(r"\n\s*\n", also) if p.strip()]
        for p in items:
            if not p.lstrip().startswith("**"):
                rep.errors.append(f"'Also this week' item does not start with a bold headline: '{p[:50]}...'")
            first_sentence = re.split(r"(?<=[.!?])\s", p.strip(), maxsplit=2)
            head = " ".join(first_sentence[:2])
            if not LINK_RE.search(head):
                rep.errors.append(f"'Also this week' item lacks a link in its first sentence: '{p[:50]}...'")
        if not (5 <= len(items) <= 8):
            rep.warnings.append(f"'Also this week' has {len(items)} items; format asks for 5-8")

    # Links overall
    links = LINK_RE.findall(markdown)
    if len(links) < 8:
        rep.errors.append(f"only {len(links)} links; every claim should be sourced")
    for text, _ in links:
        if text.strip().lower() in {"here", "this", "link", "source", "read more"}:
            rep.errors.append(f"link text '{text}' is not descriptive")

    # Banned phrases
    lowered = markdown.lower()
    for phrase in banned:
        if phrase in lowered:
            rep.errors.append(f"banned phrase: '{phrase}'")

    # Sign-off, first person singular, exclamation
    if SIGNOFF_RE.search(markdown):
        rep.errors.append("closing sign-off found; end on the last item")
    if re.search(r"\bI\b (think|tested|tried|used|believe|found)", markdown):
        rep.errors.append("first-person singular claim; the publication never says 'I'")
    if "!" in re.sub(r"\[[^\]]*\]\([^)]*\)", "", markdown):
        rep.warnings.append("exclamation mark found")

    return rep


def _section(markdown: str, heading_prefix: str) -> str:
    parts = re.split(r"^## ", markdown, flags=re.M)
    for part in parts[1:]:
        title, _, body = part.partition("\n")
        if title.strip().startswith(heading_prefix):
            return body
    return ""


def extract_links(markdown: str) -> list[str]:
    return sorted({url for _, url in LINK_RE.findall(markdown)})
