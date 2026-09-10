"""Turn the research pack into an issue brief."""

from __future__ import annotations

from ..config import Settings
from ..llm import LLMClient
from ..memory import Memory
from ..schemas import Brief, ResearchPack
from .common import load_prompt, publication_context


def make_brief(client: LLMClient, settings: Settings, memory: Memory, pack: ResearchPack) -> Brief:
    system = load_prompt(settings, "editor") + "\n\n" + publication_context(settings)
    corrections = memory.pending_corrections()
    corr_text = "\n".join(f"- ({c.get('issue_id')}) {c.get('text')}" for c in corrections) or "(none)"
    user = (
        f"RESEARCH PACK (JSON):\n{pack.model_dump_json(indent=1)}\n\n"
        f"STORIES COVERED IN RECENT ISSUES:\n{memory.coverage_text()}\n\n"
        f"PENDING CORRECTIONS TO PRINT (put them in corrections_to_run verbatim):\n{corr_text}\n\n"
        f"LESSONS FROM READER FEEDBACK:\n{memory.lessons_text()}\n\n"
        f"Target length: {settings.editorial.target_words_min}-{settings.editorial.target_words_max} words."
    )
    result = client.complete(stage="brief", system=system, user=user, output_format=Brief)
    return result.parsed
