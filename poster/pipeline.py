"""The weekly pipeline: checkpointed stages from feeds to a published issue.

Each stage writes its artifact into issues/<issue_id>/. A rerun skips stages
whose artifact already exists unless --force is given, so a failure late in the
run (a network error while publishing, say) costs nothing to retry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from .config import Settings
from .lint import lint_draft, load_banned
from .llm import LLMClient
from .memory import Memory
from .publish import get_email_publisher
from .render import Renderer, plain_text
from .schemas import Brief, Critique, Draft, FeedItem, ResearchPack, SEOPackage, TriageResult
from .stages import critic, editor, ingest, research, seo, writer
from .trace import Trace

STAGES = ["ingest", "triage", "research", "brief", "draft", "review", "seo", "render", "publish", "memory"]


@dataclass
class RunOptions:
    issue_id: str
    dry_run: bool = False
    force: bool = False
    start_from: str | None = None
    stop_after: str | None = None
    skip_feeds: bool = False


class Pipeline:
    def __init__(self, settings: Settings, client: LLMClient, trace: Trace, log: Callable[[str], None] = print) -> None:
        self.settings = settings
        self.client = client
        self.trace = trace
        self.log = log
        self.memory = Memory(settings)

    # ---- artifact helpers ------------------------------------------------
    def _dir(self, issue_id: str) -> Path:
        d = self.settings.issues_dir / issue_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _save(self, issue_id: str, name: str, obj: Any) -> Path:
        path = self._dir(issue_id) / name
        if isinstance(obj, BaseModel):
            path.write_text(obj.model_dump_json(indent=2) + "\n", encoding="utf-8")
        elif isinstance(obj, str):
            path.write_text(obj, encoding="utf-8")
        else:
            path.write_text(json.dumps(obj, indent=2, default=_json_default) + "\n", encoding="utf-8")
        return path

    def _load(self, issue_id: str, name: str, model: type[BaseModel] | None = None) -> Any:
        path = self._dir(issue_id) / name
        if not path.exists():
            return None
        if model is None:
            return path.read_text(encoding="utf-8") if name.endswith((".md", ".html", ".txt")) else json.loads(path.read_text(encoding="utf-8"))
        return model.model_validate_json(path.read_text(encoding="utf-8"))

    def _should_run(self, opts: RunOptions, stage: str, artifact: str) -> bool:
        if opts.start_from and STAGES.index(stage) < STAGES.index(opts.start_from):
            return False
        if opts.force and (not opts.start_from or STAGES.index(stage) >= STAGES.index(opts.start_from)):
            return True
        return not (self._dir(opts.issue_id) / artifact).exists()

    def _stop(self, opts: RunOptions, stage: str) -> bool:
        return bool(opts.stop_after and STAGES.index(stage) >= STAGES.index(opts.stop_after))

    # ---- the run -----------------------------------------------------------
    def run(self, opts: RunOptions) -> dict[str, Any]:
        s = self.settings
        iid = opts.issue_id
        window_end = datetime.strptime(iid, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(hours=23, minutes=59)
        window_start = (window_end - timedelta(days=s.research.lookback_days)).strftime("%Y-%m-%d")
        self.log(f"== Issue {iid} (window {window_start} .. {iid}) ==")
        self._save(iid, "run.json", {"issue_id": iid, "started": _now(), "dry_run": opts.dry_run,
                                     "models": {"main": s.models.main, "fast": s.models.fast}})

        # 1. ingest ---------------------------------------------------------
        if self._should_run(opts, "ingest", "01-feed.json"):
            self.log("[ingest] pulling feeds")
            items = [] if opts.skip_feeds else ingest.ingest(s, window_end=window_end, log=self.log)
            self._save(iid, "01-feed.json", [i.model_dump() for i in items])
        items = [FeedItem.model_validate(i) for i in self._load(iid, "01-feed.json") or []]
        self.log(f"[ingest] {len(items)} feed items")
        if self._stop(opts, "ingest"):
            return self._finish(iid)

        # 2. triage ---------------------------------------------------------
        if self._should_run(opts, "triage", "02-triage.json"):
            self.log(f"[triage] ranking {len(items)} items with {s.models.fast}")
            triaged = research.triage(self.client, s, items) if items else TriageResult(candidates=[], dropped_summary="no feed items")
            self._save(iid, "02-triage.json", triaged)
        triaged = self._load(iid, "02-triage.json", TriageResult)
        self.log(f"[triage] {len(triaged.candidates)} candidates")
        if self._stop(opts, "triage"):
            return self._finish(iid)

        # 3. research -------------------------------------------------------
        if self._should_run(opts, "research", "03-research.json"):
            self.log(f"[research] web research with {s.models.main} (this is the slow step)")
            notes, pack = research.research(self.client, s, self.memory, triaged, window_start, iid)
            self._save(iid, "03-research-notes.md", notes)
            self._save(iid, "03-research.json", pack)
        pack = self._load(iid, "03-research.json", ResearchPack)
        self.log(f"[research] {len(pack.stories)} verified stories; lead: {pack.lead_recommendation[:80]}")
        if not pack.stories:
            raise RuntimeError("research produced no stories; not writing an issue")
        if self._stop(opts, "research"):
            return self._finish(iid)

        # 4. brief ----------------------------------------------------------
        if self._should_run(opts, "brief", "04-brief.json"):
            self.log("[brief] editor is planning the issue")
            self._save(iid, "04-brief.json", editor.make_brief(self.client, s, self.memory, pack))
        brief = self._load(iid, "04-brief.json", Brief)
        self.log(f"[brief] '{brief.working_title}' — {brief.thesis[:100]}")
        if self._stop(opts, "brief"):
            return self._finish(iid)

        # 5. draft ----------------------------------------------------------
        if self._should_run(opts, "draft", "05-draft.json"):
            self.log("[draft] writing")
            self._save(iid, "05-draft.json", writer.write_draft(self.client, s, self.memory, pack, brief))
        draft = self._load(iid, "05-draft.json", Draft)
        if self._stop(opts, "draft"):
            return self._finish(iid)

        # 6. review loop ----------------------------------------------------
        if self._should_run(opts, "review", "final.md"):
            draft = self._review_loop(iid, pack, brief, draft)
            self._save(iid, "final.md", draft.body_markdown)
            self._save(iid, "06-final-draft.json", draft)
        final_md: str = self._load(iid, "final.md")
        draft = self._load(iid, "06-final-draft.json", Draft) or draft
        if self._stop(opts, "review"):
            return self._finish(iid)

        # 7. seo ------------------------------------------------------------
        if self._should_run(opts, "seo", "07-seo.json"):
            self.log("[seo] metadata and distribution package")
            self._save(iid, "07-seo.json", seo.make_seo(self.client, s, self.memory, draft))
        seo_pkg = self._load(iid, "07-seo.json", SEOPackage)
        self.log(f"[seo] slug={seo_pkg.slug} title_tag='{seo_pkg.title_tag}'")
        if self._stop(opts, "seo"):
            return self._finish(iid)

        # 8. render ---------------------------------------------------------
        published_at = datetime.now(timezone.utc)
        run_meta = self._load(iid, "run.json") or {}
        if run_meta.get("published_at"):
            published_at = datetime.fromisoformat(run_meta["published_at"])
        entry = {
            "issue_id": iid, "slug": seo_pkg.slug, "title": draft.title, "dek": draft.dek,
            "excerpt": seo_pkg.excerpt, "tags": seo_pkg.tags, "published_at": published_at.isoformat(),
            "url": f"{s.publication.site_url.rstrip('/')}/issues/{seo_pkg.slug}/",
        }
        if self._should_run(opts, "render", "issue.html"):
            self.log("[render] site page, email, feed, sitemap")
            renderer = Renderer(s)
            index = [r for r in self.memory.issues() if r["issue_id"] != iid] + [entry]
            out = renderer.render_issue(issue_id=iid, body_markdown=final_md, seo=seo_pkg, title=draft.title,
                                        dek=draft.dek, issues_index=index, published_at=published_at)
            self._save(iid, "issue.html", out["page"])
            self._save(iid, "email.html", out["email"])
            self._save(iid, "email.txt", plain_text(final_md))
            self._save(iid, "social.md", _social_md(seo_pkg, out["url"]))
            renderer.write_site(index, {seo_pkg.slug: out["page"]})
            # Re-render every past issue page so archive links and related lists stay current.
            for past in index[:-1]:
                past_md = self.settings.issues_dir / past["issue_id"] / "final.md"
                past_seo = self.settings.issues_dir / past["issue_id"] / "07-seo.json"
                if past_md.exists() and past_seo.exists():
                    pseo = SEOPackage.model_validate_json(past_seo.read_text(encoding="utf-8"))
                    pout = renderer.render_issue(issue_id=past["issue_id"], body_markdown=past_md.read_text(encoding="utf-8"),
                                                 seo=pseo, title=past["title"], dek=past.get("dek", ""), issues_index=index,
                                                 published_at=datetime.fromisoformat(past["published_at"]))
                    renderer.write_site(index, {pseo.slug: pout["page"]})
            self.memory.upsert_issue(entry)
            self._save(iid, "run.json", {**run_meta, "published_at": published_at.isoformat(), "url": out["url"]})
        if self._stop(opts, "render"):
            return self._finish(iid)

        # 9. publish --------------------------------------------------------
        if s.publishing.review_mode == "gate" and not opts.force:
            self.log("[publish] review_mode=gate: stopping before publish. Re-run with --force or set review_mode=auto.")
            self._save(iid, "REVIEW.md", _review_note(iid, draft, seo_pkg))
            return self._finish(iid)
        if self._should_run(opts, "publish", "08-publish.json"):
            results = []
            if s.publishing.send_email:
                publisher = get_email_publisher(s, dry_run=opts.dry_run)
                self.log(f"[publish] email via {publisher.name}")
                res = publisher.send(subject=seo_pkg.email_subject, preheader=seo_pkg.email_preheader,
                                     html=self._load(iid, "email.html"), text=self._load(iid, "email.txt"),
                                     markdown=final_md, canonical_url=entry["url"])
                self.log(f"[publish] {res.provider}: {'ok' if res.ok else 'FAILED'} — {res.detail}")
                results.append(res.__dict__)
                if not res.ok and not opts.dry_run:
                    self._save(iid, "08-publish-failed.json", results)
                    raise RuntimeError(f"email publish failed: {res.detail}")
            self._save(iid, "08-publish.json", {"site_url": entry["url"], "email": results, "at": _now()})
        if self._stop(opts, "publish"):
            return self._finish(iid)

        # 10. memory --------------------------------------------------------
        if self._should_run(opts, "memory", "09-memory.json"):
            covered = [st.model_dump() for st in pack.stories if st.id in set(draft.stories_covered)] or \
                      [st.model_dump() for st in pack.stories]
            self.memory.record_coverage(iid, seo_pkg.slug, covered)
            if "## Corrections" in final_md:
                self.memory.mark_corrections_printed()
            self._save(iid, "09-memory.json", {"coverage_recorded": len(covered), "at": _now()})
            self.log(f"[memory] recorded {len(covered)} stories")
        return self._finish(iid)

    # ---- review loop -------------------------------------------------------
    def _review_loop(self, iid: str, pack: ResearchPack, brief: Brief, draft: Draft) -> Draft:
        s = self.settings
        banned = load_banned(s.publication_dir / "banned_phrases.txt")
        best: tuple[int, Draft] | None = None
        for round_no in range(1, s.editorial.max_revision_rounds + 2):
            lint = lint_draft(draft.body_markdown, banned=banned, min_words=s.editorial.target_words_min,
                              max_words=s.editorial.target_words_max)
            links = critic.verify_links(draft.body_markdown, pack, enabled=s.editorial.verify_links)
            self.log(f"[review {round_no}] lint: {len(lint.errors)} errors, {len(lint.warnings)} warnings, {lint.word_count} words")
            crit = critic.critique_draft(self.client, s, self.memory, pack, draft, lint.as_text(), links, round_no)
            self._save(iid, f"06-critique-{round_no}.json", crit)
            self._save(iid, f"06-lint-{round_no}.txt", lint.as_text() + "\n\nLINKS:\n" + links)
            self.log(f"[review {round_no}] critic score {crit.score}/10 — {crit.summary[:120]}")
            passed = crit.score >= s.editorial.min_critic_score and lint.ok
            if best is None or crit.score > best[0]:
                best = (crit.score, draft)
            if passed or round_no > s.editorial.max_revision_rounds:
                if not passed:
                    self.log(f"[review] max rounds reached; shipping best draft (score {best[0]})")
                    draft = best[1]
                break
            self.log(f"[revise {round_no}] applying {len(crit.required_edits)} required edits")
            draft = writer.revise_draft(self.client, s, self.memory, pack, brief, draft, crit, lint.as_text(), round_no)
            self._save(iid, f"05-draft-r{round_no}.json", draft)
        return draft

    def _finish(self, iid: str) -> dict[str, Any]:
        summary = self.trace.summary()
        self._save(iid, "cost.json", summary)
        self.log(f"== done: {summary['calls']} calls, est ${summary['est_cost_usd']:.2f} ==")
        return summary


def _social_md(seo_pkg: SEOPackage, url: str) -> str:
    return (
        f"# Social posts\n\n## LinkedIn\n\n{seo_pkg.social.linkedin.replace('{url}', url)}\n\n"
        f"## X\n\n{seo_pkg.social.x.replace('{url}', url)}\n\n## Threads / Bluesky\n\n{seo_pkg.social.threads.replace('{url}', url)}\n"
    )


def _review_note(iid: str, draft: Draft, seo_pkg: SEOPackage) -> str:
    return (
        f"# Review gate for issue {iid}\n\nTitle: {draft.title}\nSlug: {seo_pkg.slug}\n"
        f"Email subject: {seo_pkg.email_subject}\n\nRead `final.md`, edit it if needed, then run:\n\n"
        f"    poster run --issue {iid} --from publish --force\n"
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"not serializable: {type(obj)}")
