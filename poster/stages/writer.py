"""Draft and revise the issue."""

from __future__ import annotations

from ..config import Settings
from ..llm import LLMClient
from ..memory import Memory
from ..schemas import Brief, Critique, Draft, ResearchPack
from .common import load_prompt, publication_context


def _pack_for_writer(pack: ResearchPack) -> str:
    return pack.model_dump_json(indent=1)


def write_draft(client: LLMClient, settings: Settings, memory: Memory, pack: ResearchPack, brief: Brief) -> Draft:
    system = load_prompt(settings, "writer") + "\n\n" + publication_context(settings)
    user = (
        f"EDITOR'S BRIEF (JSON):\n{brief.model_dump_json(indent=1)}\n\n"
        f"RESEARCH PACK (JSON):\n{_pack_for_writer(pack)}\n\n"
        f"LESSONS FROM READER FEEDBACK:\n{memory.lessons_text()}\n\n"
        f"Length: {settings.editorial.target_words_min}-{settings.editorial.target_words_max} words. "
        "Write the complete issue now."
    )
    result = client.complete(stage="draft", system=system, user=user, output_format=Draft)
    return result.parsed


def revise_draft(client: LLMClient, settings: Settings, memory: Memory, pack: ResearchPack, brief: Brief,
                 draft: Draft, critique: Critique, lint_text: str, round_no: int) -> Draft:
    system = load_prompt(settings, "reviser") + "\n\n" + publication_context(settings)
    user = (
        f"REVISION ROUND {round_no}.\n\n"
        f"CRITIQUE (JSON):\n{critique.model_dump_json(indent=1)}\n\n"
        f"DETERMINISTIC LINT REPORT:\n{lint_text}\n\n"
        f"CURRENT DRAFT:\n{draft.body_markdown}\n\n"
        f"EDITOR'S BRIEF (JSON):\n{brief.model_dump_json(indent=1)}\n\n"
        f"RESEARCH PACK (JSON):\n{_pack_for_writer(pack)}\n\n"
        f"LESSONS FROM READER FEEDBACK:\n{memory.lessons_text()}\n\n"
        "Return the complete revised issue."
    )
    result = client.complete(stage=f"revise-{round_no}", system=system, user=user, output_format=Draft)
    return result.parsed
