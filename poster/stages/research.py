"""Triage feed items, then run the web-enabled research desk and structure its notes."""

from __future__ import annotations

from ..config import Settings
from ..llm import LLMClient, web_tools
from ..memory import Memory
from ..schemas import FeedItem, ResearchPack, TriageResult
from .common import load_prompt, publication_context


def triage(client: LLMClient, settings: Settings, items: list[FeedItem]) -> TriageResult:
    system = load_prompt(settings, "triage") + "\n\n" + publication_context(settings, include_style=False)
    lines = []
    for it in items:
        lines.append(f"- [{it.source} | {it.kind} | {it.published[:10]}] {it.title}\n  {it.link}\n  {it.summary}")
    user = (
        f"Issue window: the past {settings.research.lookback_days} days.\n"
        f"Return at most {settings.research.max_candidates} candidates, ranked by significance.\n\n"
        "FEED ITEMS:\n" + "\n".join(lines)
    )
    result = client.complete(stage="triage", system=system, user=user, output_format=TriageResult,
                             model=settings.models.fast, effort="medium")
    return result.parsed


def research(client: LLMClient, settings: Settings, memory: Memory, triaged: TriageResult,
             window_start: str, window_end: str) -> tuple[str, ResearchPack]:
    system = load_prompt(settings, "researcher") + "\n\n" + publication_context(settings, include_style=False)
    cand_lines = []
    for c in triaged.candidates:
        cand_lines.append(
            f"- {c.id} [{c.category} | sig {c.significance} | {c.event_date}] {c.headline}\n"
            f"  main: {c.main_url}\n  others: {', '.join(c.other_urls[:4]) or '-'}\n  {c.summary}\n  why: {c.why_candidate}"
        )
    user = (
        f"ISSUE WINDOW: {window_start} to {window_end} (inclusive). Today is {window_end}.\n\n"
        f"CANDIDATES FROM THE FEEDS:\n" + "\n".join(cand_lines) + "\n\n"
        f"STORIES COVERED IN RECENT ISSUES (do not repeat unless materially new):\n{memory.coverage_text()}\n\n"
        f"LESSONS FROM READER FEEDBACK:\n{memory.lessons_text()}\n\n"
        "Produce the research notes now. Use web_search and web_fetch liberally; "
        "every fact you write down must come from a page you fetched or a search result you read."
    )
    notes = client.complete(
        stage="research", system=system, user=user,
        tools=web_tools(settings.research.max_web_searches, settings.research.max_web_fetches),
        effort=settings.models.effort,
    )

    struct_system = load_prompt(settings, "structurer")
    struct_user = (
        f"ISSUE WINDOW: {window_start} to {window_end}.\n\nRESEARCH NOTES:\n\n{notes.text}"
    )
    pack = client.complete(stage="structure", system=struct_system, user=struct_user,
                           output_format=ResearchPack, effort="medium")
    return notes.text, pack.parsed
