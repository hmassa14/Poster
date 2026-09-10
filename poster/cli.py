"""Command-line entry point: `poster run`, `poster feedback`, `poster lint`, ..."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings, load_settings
from .lint import lint_draft, load_banned
from .memory import Memory
from .pipeline import STAGES, Pipeline, RunOptions
from .trace import Trace


def _client(settings: Settings, trace: Trace):
    from .llm import Claude

    return Claude(settings, trace)


def cmd_run(args: argparse.Namespace) -> int:
    settings = load_settings(args.root)
    issue_id = args.issue or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    trace = Trace(settings.issues_dir / issue_id / "trace.jsonl")
    pipeline = Pipeline(settings, _client(settings, trace), trace)
    opts = RunOptions(issue_id=issue_id, dry_run=args.dry_run, force=args.force, start_from=args.start_from,
                      stop_after=args.stop_after, skip_feeds=args.skip_feeds)
    pipeline.run(opts)
    return 0


def cmd_feedback(args: argparse.Namespace) -> int:
    from .stages import feedback as fb

    settings = load_settings(args.root)
    memory = Memory(settings)
    items = fb.collect(settings, pull_github=not args.no_github)
    print(f"{len(items)} feedback item(s) in the inbox")
    if not items or args.pull_only:
        return 0
    trace = Trace(settings.feedback_dir / "trace.jsonl")
    client = _client(settings, trace)
    digest = fb.digest(client, settings, memory, items, fb.latest_issue_markdown(settings))
    print(digest.summary)
    for ch in digest.rule_changes:
        print(f"  [{ch.target}/{ch.action}] {ch.rule}  ({ch.rationale})")
    for lesson in digest.lessons:
        print(f"  [lesson] {lesson}")
    for c in digest.corrections:
        print(f"  [correction {c.issue_id}] {c.text}")
    if args.dry_run:
        print("dry run: nothing written")
        return 0
    fb.apply_digest(settings, memory, digest, items)
    if args.close_issues and settings.feedback.github_repo:
        from .publish.github import close_issue

        for item in items:
            if item["source"] == "github-issue":
                number = int(item["file"].split("-")[1].split(".")[0])
                close_issue(settings.feedback.github_repo, number,
                            "Thanks. This feedback has been folded into the publication's style guide, format, or lessons "
                            "and will shape the next issue.\n\n---\n_Automated by the Poster feedback stage._")
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    settings = load_settings(args.root)
    text = Path(args.file).read_text(encoding="utf-8")
    rep = lint_draft(text, banned=load_banned(settings.publication_dir / "banned_phrases.txt"),
                     min_words=settings.editorial.target_words_min, max_words=settings.editorial.target_words_max)
    print(rep.as_text())
    return 0 if rep.ok else 1


def cmd_render(args: argparse.Namespace) -> int:
    """Rebuild the whole static site from stored issues (no model calls)."""
    from .render import Renderer
    from .schemas import SEOPackage

    settings = load_settings(args.root)
    memory = Memory(settings)
    renderer = Renderer(settings)
    index = memory.issues()
    pages = {}
    for entry in index:
        d = settings.issues_dir / entry["issue_id"]
        if (d / "final.md").exists() and (d / "07-seo.json").exists():
            seo = SEOPackage.model_validate_json((d / "07-seo.json").read_text(encoding="utf-8"))
            out = renderer.render_issue(issue_id=entry["issue_id"], body_markdown=(d / "final.md").read_text(encoding="utf-8"),
                                        seo=seo, title=entry["title"], dek=entry.get("dek", ""), issues_index=index,
                                        published_at=datetime.fromisoformat(entry["published_at"]))
            pages[seo.slug] = out["page"]
    written = renderer.write_site(index, pages)
    print(f"wrote {len(written)} files to {settings.site_dir}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    settings = load_settings(args.root)
    memory = Memory(settings)
    print(f"publication: {settings.publication.name}")
    print(f"models: main={settings.models.main} fast={settings.models.fast} effort={settings.models.effort}")
    print(f"email provider: {settings.publishing.email_provider}; review_mode: {settings.publishing.review_mode}")
    issues = memory.issues()
    print(f"issues published: {len(issues)}")
    for r in issues[-5:]:
        print(f"  {r['issue_id']}  {r['slug']}  {r['title']}")
    print(f"lessons: {len(memory.lessons())}; pending corrections: {len(memory.pending_corrections())}")
    inbox = list((settings.feedback_dir / 'inbox').glob('*')) if (settings.feedback_dir / 'inbox').exists() else []
    print(f"feedback inbox: {len([p for p in inbox if p.is_file()])} item(s)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="poster", description="AI-written weekly AI newsletter pipeline")
    p.add_argument("--root", default=None, help="project root (default: nearest poster.yaml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="produce and publish an issue")
    r.add_argument("--issue", help="issue id / window end date YYYY-MM-DD (default: today UTC)")
    r.add_argument("--dry-run", action="store_true", help="do everything except send email")
    r.add_argument("--force", action="store_true", help="re-run stages even if artifacts exist")
    r.add_argument("--from", dest="start_from", choices=STAGES, help="start at this stage")
    r.add_argument("--to", dest="stop_after", choices=STAGES, help="stop after this stage")
    r.add_argument("--skip-feeds", action="store_true", help="skip RSS ingestion (research from web search only)")
    r.set_defaults(fn=cmd_run)

    f = sub.add_parser("feedback", help="pull feedback and fold it into the publication")
    f.add_argument("--no-github", action="store_true", help="do not pull GitHub issues")
    f.add_argument("--pull-only", action="store_true", help="stage feedback into the inbox without digesting")
    f.add_argument("--dry-run", action="store_true", help="show the digest without writing")
    f.add_argument("--close-issues", action="store_true", help="close processed GitHub issues with a comment")
    f.set_defaults(fn=cmd_feedback)

    l = sub.add_parser("lint", help="run the deterministic checks on a markdown file")
    l.add_argument("file")
    l.set_defaults(fn=cmd_lint)

    sub.add_parser("render", help="rebuild the static site from stored issues").set_defaults(fn=cmd_render)
    sub.add_parser("status", help="show publication state").set_defaults(fn=cmd_status)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # surface the failure plainly for CI logs
        print(f"error: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    sys.exit(main())
