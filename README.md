# Poster

An AI-written, AI-maintained weekly AI newsletter and blog. Every week the
system pulls the news, researches it from primary sources with web search,
plans the issue, writes it, fact-checks it against its own research, generates
the SEO and social package, renders a static site and an email, publishes
both, and remembers what it covered. Reader and publisher feedback is folded
back into the style guide and format so the next issue is better.

This is a separate publication from Attainable AI. It is never written in a
human voice and it says so in every issue.

- Pipeline design and rationale: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- What the publication is: [`publication/profile.md`](publication/profile.md)
- House style and format: [`publication/style.md`](publication/style.md), [`publication/format.md`](publication/format.md)

## How an issue gets made

```
poster run
```

1. **ingest** reads the feeds in `publication/feeds.yaml` for the past 8 days.
2. **triage** (Claude Sonnet 5) merges duplicates and ranks candidate stories.
3. **research** (Claude Opus 5 with web search and web fetch) verifies each
   candidate at its primary source, hunts for what the feeds missed, and
   checks past coverage. A second call structures the notes into a typed
   research pack: every fact with the URL it came from.
4. **brief**: the editor picks the lead, writes the thesis, and plans sections.
5. **draft**: the writer produces the issue from the brief and the pack only.
   It has no web access, so it cannot invent a source.
6. **review loop**: a deterministic linter (headings, length, banned
   vocabulary, link text, sign-offs) and an HTTP link check run first; then a
   critic fact-checks the draft against the pack and scores it. Under 8/10 or
   any lint error sends it back for revision, up to two rounds.
7. **seo**: slug, title tag, meta description, Open Graph, JSON-LD, keywords,
   internal links to past issues, email subject and preheader, and LinkedIn,
   X, and Threads posts. Hard limits are enforced in code, not trusted.
8. **render**: the issue page, the archive index, RSS, sitemap, robots.txt,
   and an inline-styled email.
9. **publish**: the site is committed to `site/` and deployed by GitHub Pages;
   the email goes out through Buttondown or Resend (or a dry run).
10. **memory**: coverage and the issue index are recorded for future issues.

Every stage writes its artifact to `issues/<date>/`. A rerun skips finished
stages, so a failure at publish costs nothing to retry:
`poster run --issue 2026-09-10 --from publish`.

## Setup

1. **Secrets** (repository settings → Secrets and variables → Actions):
   - `ANTHROPIC_API_KEY` (required)
   - `BUTTONDOWN_API_KEY` if `publishing.email_provider: buttondown`
   - `RESEND_API_KEY`, `RESEND_FROM`, `RESEND_AUDIENCE_ID` if `resend`
   - Variable `POSTER_SITE_URL` if the site is not at the default GitHub Pages URL
2. **GitHub Pages**: Settings → Pages → Source: *GitHub Actions*. The
   `Deploy site` workflow publishes `site/` on every push that changes it.
3. **Edit `poster.yaml`**: publication name, tagline, site URL, email provider,
   `review_mode` (`auto` publishes directly; `gate` opens a PR with the draft
   for a human to approve before publishing).
4. **Schedule**: `.github/workflows/weekly-issue.yml` runs Thursdays 13:00 UTC.
   Change the cron to move publication day. Run it manually from the Actions
   tab with `dry_run` checked to see a full issue without sending email.

Local:

```
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in ANTHROPIC_API_KEY, then export it
poster run --dry-run   # full issue, no email
poster status
python -m pytest -q    # offline tests with a fake model
```

## Feedback loop

Three inputs, one mechanism:

- **GitHub Issues** labeled `feedback` (there is an issue template). Pulled
  automatically by the `Feedback` workflow on open/comment and nightly, and
  again right before each weekly run.
- **Files** dropped in `feedback/inbox/` (`publisher-*.md` outranks readers).
- **Metrics** exports dropped in `feedback/metrics/*.json`.

`poster feedback` sends the new items plus the current style guide, format
spec, lessons, and latest issue to Claude, which returns a digest: concrete
rule changes (appended to `publication/style.md` under "Learned rules" or
edited into `publication/format.md`), durable lessons (`memory/lessons.md`),
and corrections to print in the next issue's "Corrections" section. Every
edit lands in git with a dated rationale, so you can read exactly what the
system learned and revert anything you disagree with. Processed GitHub
issues are closed with a comment.

Every editorial prompt reads the style guide, format spec, and lessons, so
feedback changes research priorities, editing, writing, and review together.

## Changing the publication

- Sections, order, lengths: `publication/format.md` (the linter enforces the
  required headings listed in `poster/lint.py`; update both together).
- Voice: `publication/style.md`. Vocabulary: `publication/banned_phrases.txt`.
- Sources: `publication/feeds.yaml`. The research stage searches the open web
  as well, so this list is a seed, not a boundary.
- Prompts: `prompts/*.md`, one per stage.
- Look of the site and email: `templates/`.
- Models, effort, budgets, thresholds: `poster.yaml`.

## Cost

Roughly 8 to 10 model calls per issue; the web research call dominates.
`issues/<date>/cost.json` and `trace.jsonl` record real token usage and an
estimated USD figure per stage after every run. Tune `models.effort` and the
`research.*` limits in `poster.yaml` from those numbers rather than guessing.

## Layout

```
poster/            the pipeline (config, llm wrapper, stages, lint, render, publish, memory, cli)
prompts/           one system prompt per stage
publication/       profile, style guide, format spec, banned phrases, feeds
templates/         Jinja2 templates for the site, RSS, sitemap, and email
issues/<date>/     every artifact of every run (research pack, drafts, critiques, final.md, html)
site/              the generated static site, deployed by GitHub Pages
memory/            coverage index, issue index, lessons, pending corrections
feedback/          inbox, metrics, processed digests, log
tests/             offline tests with a fake model client
.github/workflows/ weekly issue, feedback, site deploy, tests
```
