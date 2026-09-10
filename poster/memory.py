"""Cross-issue memory kept in the repository: coverage index, lessons, issue index."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings


class Memory:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.dir = settings.memory_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.coverage_path = self.dir / "coverage.jsonl"
        self.lessons_path = self.dir / "lessons.md"
        self.index_path = self.dir / "issues.json"
        self.corrections_path = self.dir / "corrections.jsonl"

    # ---- coverage ------------------------------------------------------
    def recent_coverage(self, limit: int = 120) -> list[dict[str, Any]]:
        if not self.coverage_path.exists():
            return []
        rows = [json.loads(line) for line in self.coverage_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return rows[-limit:]

    def record_coverage(self, issue_id: str, slug: str, stories: list[dict[str, Any]]) -> None:
        with self.coverage_path.open("a", encoding="utf-8") as fh:
            for s in stories:
                fh.write(json.dumps({
                    "issue_id": issue_id,
                    "slug": slug,
                    "story_id": s.get("id"),
                    "headline": s.get("headline"),
                    "category": s.get("category"),
                    "urls": [src.get("url") for src in s.get("sources", [])][:5],
                }) + "\n")

    def coverage_text(self) -> str:
        rows = self.recent_coverage()
        if not rows:
            return "(no previous issues)"
        return "\n".join(f"- [{r['issue_id']}] {r['headline']} ({r.get('category')})" for r in rows)

    # ---- lessons -------------------------------------------------------
    def lessons(self) -> list[str]:
        if not self.lessons_path.exists():
            return []
        return [ln[2:].strip() for ln in self.lessons_path.read_text(encoding="utf-8").splitlines() if ln.startswith("- ")]

    def lessons_text(self) -> str:
        items = self.lessons()[-self.settings.feedback.max_lessons_in_prompt:]
        return "\n".join(f"- {x}" for x in items) if items else "(none yet)"

    def add_lessons(self, lessons: list[str], source: str) -> None:
        if not lessons:
            return
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        header = "# Lessons learned\n\nAppended by the feedback stage. One bullet per lesson; newest last.\n\n"
        if not self.lessons_path.exists():
            self.lessons_path.write_text(header, encoding="utf-8")
        with self.lessons_path.open("a", encoding="utf-8") as fh:
            for lesson in lessons:
                fh.write(f"- {lesson} _(from {source}, {stamp})_\n")

    # ---- corrections (pending until printed) ---------------------------
    def add_corrections(self, corrections: list[dict[str, Any]]) -> None:
        with self.corrections_path.open("a", encoding="utf-8") as fh:
            for c in corrections:
                fh.write(json.dumps({**c, "printed": False}) + "\n")

    def pending_corrections(self) -> list[dict[str, Any]]:
        if not self.corrections_path.exists():
            return []
        rows = [json.loads(l) for l in self.corrections_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        return [r for r in rows if not r.get("printed")]

    def mark_corrections_printed(self) -> None:
        if not self.corrections_path.exists():
            return
        rows = [json.loads(l) for l in self.corrections_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        for r in rows:
            r["printed"] = True
        self.corrections_path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    # ---- issue index (drives the site archive, RSS, internal links) ----
    def issues(self) -> list[dict[str, Any]]:
        if not self.index_path.exists():
            return []
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def upsert_issue(self, entry: dict[str, Any]) -> None:
        rows = [r for r in self.issues() if r["issue_id"] != entry["issue_id"]]
        rows.append(entry)
        rows.sort(key=lambda r: r["issue_id"])
        self.index_path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")

    def issues_text(self) -> str:
        rows = self.issues()
        if not rows:
            return "(no past issues)"
        return "\n".join(f"- {r['slug']}: {r['title']} — {r.get('excerpt', '')}" for r in rows[-40:])
