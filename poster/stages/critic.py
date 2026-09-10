"""Fact-check and review the draft against the research pack, plus link verification."""

from __future__ import annotations

import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from ..config import Settings
from ..lint import extract_links
from ..llm import LLMClient
from ..memory import Memory
from ..schemas import Critique, Draft, ResearchPack
from .common import load_prompt, publication_context

UA = "Mozilla/5.0 (compatible; PosterBot/0.1; +https://github.com/hmassa14/poster)"


def critique_draft(client: LLMClient, settings: Settings, memory: Memory, pack: ResearchPack, draft: Draft,
                   lint_text: str, link_report: str, round_no: int) -> Critique:
    system = load_prompt(settings, "critic") + "\n\n" + publication_context(settings)
    user = (
        f"REVIEW ROUND {round_no}.\n\n"
        f"DRAFT:\n{draft.body_markdown}\n\n"
        f"WRITER NOTES: {draft.writer_notes or '(none)'}\n\n"
        f"RESEARCH PACK (JSON):\n{pack.model_dump_json(indent=1)}\n\n"
        f"DETERMINISTIC LINT REPORT (treat every ERROR as a blocker):\n{lint_text}\n\n"
        f"LINK CHECK:\n{link_report}\n\n"
        f"LESSONS FROM READER FEEDBACK:\n{memory.lessons_text()}\n\n"
        "Review the draft now."
    )
    result = client.complete(stage=f"critique-{round_no}", system=system, user=user, output_format=Critique)
    return result.parsed


def _check(url: str, timeout: float = 12.0) -> tuple[str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return url, f"{resp.status}"
    except urllib.error.HTTPError as exc:
        return url, f"HTTP {exc.code}"
    except Exception as exc:  # DNS, TLS, timeout
        return url, f"ERR {type(exc).__name__}"


def verify_links(markdown: str, pack: ResearchPack, *, enabled: bool = True) -> str:
    """Report links not present in the research pack, and (optionally) unreachable ones."""
    links = extract_links(markdown)
    pack_urls = {f.source_url for s in pack.stories for f in s.facts}
    pack_urls |= {src.url for s in pack.stories for src in s.sources}
    pack_urls |= {q.source_url for s in pack.stories for q in s.quotes}
    pack_urls |= set(pack.noise_check.source_urls)
    lines = []
    foreign = [u for u in links if u not in pack_urls and u.rstrip("/") not in {p.rstrip("/") for p in pack_urls}]
    for u in foreign:
        lines.append(f"NOT IN RESEARCH PACK: {u}")
    if enabled and links:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for url, status in pool.map(_check, links):
                if not status.startswith("2") and not status.startswith("3"):
                    lines.append(f"UNREACHABLE ({status}): {url}")
    if not lines:
        return f"All {len(links)} links are in the research pack" + (" and reachable." if enabled else ".")
    return "\n".join(lines)
