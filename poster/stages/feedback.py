"""Collect feedback (files, GitHub issues, metrics) and fold it into the publication."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Settings
from ..llm import LLMClient
from ..memory import Memory
from ..publish.github import fetch_feedback_issues
from ..schemas import FeedbackDigest
from .common import load_prompt, read_pub


def collect(settings: Settings, *, pull_github: bool = True, log=print) -> list[dict[str, Any]]:
    """Gather unprocessed feedback items into a list of dicts and stage them in feedback/inbox."""
    inbox = settings.feedback_dir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    seen_path = settings.feedback_dir / "seen_github.json"
    seen: set[str] = set(json.loads(seen_path.read_text()) if seen_path.exists() else [])

    if pull_github and settings.feedback.github_repo:
        try:
            issues = fetch_feedback_issues(settings.feedback.github_repo, settings.feedback.github_label)
        except Exception as exc:
            log(f"  GitHub feedback pull failed: {exc}")
            issues = []
        for iss in issues:
            key = f"issue-{iss['number']}"
            if key in seen:
                continue
            body = f"# {iss['title']}\n\n{iss['body'] or ''}\n"
            for c in iss.get("comments", []):
                body += f"\n---\n_{c['author']} commented:_\n\n{c['body']}\n"
            (inbox / f"{key}.md").write_text(body, encoding="utf-8")
            seen.add(key)
            log(f"  pulled GitHub issue #{iss['number']}: {iss['title']}")
        seen_path.write_text(json.dumps(sorted(seen)) + "\n")

    items: list[dict[str, Any]] = []
    for path in sorted(inbox.glob("*")):
        if path.is_file() and path.suffix in {".md", ".txt", ".json"} and not path.name.lower().startswith("readme"):
            items.append({"file": path.name, "source": _source_of(path), "text": path.read_text(encoding="utf-8")})
    metrics_dir = settings.feedback_dir / "metrics"
    for path in sorted(metrics_dir.glob("*.json")) if metrics_dir.exists() else []:
        items.append({"file": path.name, "source": "metrics", "text": path.read_text(encoding="utf-8")})
    return items


def _source_of(path: Path) -> str:
    if path.name.startswith("issue-"):
        return "github-issue"
    if path.name.startswith("publisher"):
        return "publisher"
    return "reader"


def digest(client: LLMClient, settings: Settings, memory: Memory, items: list[dict[str, Any]],
           latest_issue_md: str) -> FeedbackDigest:
    system = load_prompt(settings, "feedback")
    fb = "\n\n".join(f"<feedback source=\"{i['source']}\" file=\"{i['file']}\">\n{i['text']}\n</feedback>" for i in items)
    user = (
        f"NEW FEEDBACK ITEMS:\n{fb}\n\n"
        f"CURRENT STYLE GUIDE:\n{read_pub(settings, 'style')}\n\n"
        f"CURRENT FORMAT SPEC:\n{read_pub(settings, 'format')}\n\n"
        f"CURRENT LESSONS:\n{memory.lessons_text()}\n\n"
        f"MOST RECENT ISSUE (for context):\n{latest_issue_md[:12000]}\n\n"
        "Produce the digest now."
    )
    result = client.complete(stage="feedback", system=system, user=user, output_format=FeedbackDigest)
    return result.parsed


def apply_digest(settings: Settings, memory: Memory, digest_: FeedbackDigest, items: list[dict[str, Any]],
                 log=print) -> dict[str, int]:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    counts = {"style": 0, "format": 0, "lessons": 0, "corrections": 0}

    style_path = settings.publication_dir / "style.md"
    format_path = settings.publication_dir / "format.md"
    for change in digest_.rule_changes:
        path = style_path if change.target == "style" else format_path
        text = path.read_text(encoding="utf-8")
        if change.action == "add":
            if change.target == "style":
                text = text.rstrip("\n") + f"\n- ({stamp}) {change.rule}  \n  _Why: {change.rationale}_\n"
            else:
                text = text.rstrip("\n") + f"\n- ({stamp}) {change.rule} _(why: {change.rationale})_\n"
        elif change.action in {"modify", "remove"} and change.replaces and change.replaces in text:
            replacement = change.rule if change.action == "modify" else ""
            text = text.replace(change.replaces, replacement, 1)
        else:
            # Could not locate the rule to modify; record as an addition so nothing is lost.
            text = text.rstrip("\n") + f"\n- ({stamp}) {change.rule}  \n  _Why: {change.rationale}_\n"
        path.write_text(text, encoding="utf-8")
        counts[change.target] += 1

    memory.add_lessons(digest_.lessons, source="feedback")
    counts["lessons"] = len(digest_.lessons)
    if digest_.corrections:
        memory.add_corrections([c.model_dump() for c in digest_.corrections])
        counts["corrections"] = len(digest_.corrections)

    # Archive processed inbox items and log the digest.
    processed = settings.feedback_dir / "processed" / stamp
    processed.mkdir(parents=True, exist_ok=True)
    for item in items:
        src = settings.feedback_dir / "inbox" / item["file"]
        if src.exists():
            shutil.move(str(src), str(processed / item["file"]))
        msrc = settings.feedback_dir / "metrics" / item["file"]
        if item["source"] == "metrics" and msrc.exists():
            shutil.move(str(msrc), str(processed / item["file"]))
    (processed / "digest.json").write_text(digest_.model_dump_json(indent=2), encoding="utf-8")
    with (settings.feedback_dir / "log.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"date": stamp, "items": len(items), **counts, "summary": digest_.summary}) + "\n")
    log(f"  feedback applied: {counts}")
    return counts


def latest_issue_markdown(settings: Settings) -> str:
    finals = sorted(settings.issues_dir.glob("*/final.md"))
    return finals[-1].read_text(encoding="utf-8") if finals else "(no issues yet)"


