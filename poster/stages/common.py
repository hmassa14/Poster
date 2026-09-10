"""Helpers shared by stages: prompt loading and the stable publication context."""

from __future__ import annotations

from ..config import Settings


def load_prompt(settings: Settings, name: str) -> str:
    return (settings.prompts_dir / f"{name}.md").read_text(encoding="utf-8").strip()


def read_pub(settings: Settings, name: str) -> str:
    path = settings.publication_dir / f"{name}.md"
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def publication_context(settings: Settings, *, include_style: bool = True, include_format: bool = True) -> str:
    """The stable, cacheable block appended to every system prompt.

    Order is fixed so the prompt-cache prefix stays byte-identical across
    calls within a run (and across runs until a file changes).
    """
    parts = ["<publication_profile>\n" + read_pub(settings, "profile") + "\n</publication_profile>"]
    if include_style:
        parts.append("<style_guide>\n" + read_pub(settings, "style") + "\n</style_guide>")
    if include_format:
        parts.append("<issue_format>\n" + read_pub(settings, "format") + "\n</issue_format>")
    return "\n\n".join(parts)
