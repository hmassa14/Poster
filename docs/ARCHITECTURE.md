# Architecture

Poster is a code-controlled workflow, not a single open-ended agent. Each
stage is one focused model call with a fixed role, a stable cached system
prompt, and a typed (pydantic) structured output. The orchestrator owns the
control flow, checkpoints every artifact to disk, and decides when to loop.

```
                 feeds.yaml                         GitHub Issues (label: feedback)
                     │                                  feedback/inbox/*.md
                     ▼                                  feedback/metrics/*.json
 ┌──────────┐   ┌──────────┐   ┌───────────────┐              │
 │  ingest  │──▶│  triage  │──▶│   research    │              ▼
 │ RSS/Atom │   │ sonnet-5 │   │ opus-5 + web  │      ┌──────────────┐
 └──────────┘   └──────────┘   │ search/fetch  │      │   feedback   │
                               └───────┬───────┘      │   opus-5     │
                                       │              └──────┬───────┘
                                       ▼                     │ edits
                               ┌───────────────┐             ▼
                               │   structure   │   publication/style.md
                               │  ResearchPack │   publication/format.md
                               └───────┬───────┘   memory/lessons.md
                                       │           memory/corrections.jsonl
                                       ▼                     │
                               ┌───────────────┐             │ read by every
                               │     brief     │◀────────────┤ editorial stage
                               │    (editor)   │             │
                               └───────┬───────┘             │
                                       ▼                     │
                               ┌───────────────┐             │
                        ┌─────▶│     draft     │◀────────────┤
                        │      │   (writer)    │             │
                        │      └───────┬───────┘             │
                        │              ▼                     │
                        │      ┌───────────────┐  lint +     │
                        │      │   critique    │  link check │
                        │      │ (fact-check)  │◀────────────┘
                        │      └───────┬───────┘
                        │   score < 8  │  score ≥ 8 and lint clean
                        └──────────────┤
                                       ▼
                               ┌───────────────┐
                               │    policy     │ policy.yaml: quote/PII/defamation rules block;
                               │  + escalation │ escalation classifier forces human review
                               └───────┬───────┘
                                       ▼
                               ┌───────────────┐
                               │      seo      │ slug, title tag, meta, OG,
                               └───────┬───────┘ JSON-LD, internal links, social
                                       ▼
                               ┌───────────────┐
                               │    render     │ site/ (HTML, RSS, sitemap), email.html
                               └───────┬───────┘
                                       ▼
                               ┌───────────────┐
                               │    publish    │ GitHub Pages (commit) + Buttondown/Resend
                               └───────┬───────┘
                                       ▼
                               ┌───────────────┐
                               │    memory     │ coverage.jsonl, issues.json
                               └───────────────┘
```

## Stages

| Stage | Model | Tools | Input | Output artifact |
|---|---|---|---|---|
| ingest | none | RSS/Atom over HTTP | `publication/feeds.yaml` | `01-feed.json` |
| triage | fast (`claude-sonnet-5`) | none | feed items | `02-triage.json` (`TriageResult`) |
| research | main (`claude-opus-5`) | `web_search_20260209`, `web_fetch_20260209` | candidates, past coverage, lessons | `03-research-notes.md` |
| structure | main | none | research notes | `03-research.json` (`ResearchPack`) |
| brief | main | none | pack, coverage, pending corrections, lessons | `04-brief.json` (`Brief`) |
| draft | main | none | brief, pack, lessons | `05-draft.json` (`Draft`) |
| critique | main | none (deterministic lint + HTTP link check run first) | draft, pack, lint, links | `06-critique-N.json` (`Critique`) |
| revise | main | none | critique, lint, draft, pack | `05-draft-rN.json` |
| policy | main (classifier) | none (deterministic rules run first) | final markdown, `policy.yaml` | `06b-policy.json`, `REVIEW.md` on escalation |
| seo | main | none | final markdown, past issues | `07-seo.json` (`SEOPackage`) |
| render | none | Jinja2 + Markdown | final.md, seo | `issue.html`, `email.html`, `email.txt`, `social.md`, `site/**` |
| publish | none | email provider API | email.html | `08-publish.json` |
| memory | none | files | pack, seo | `memory/coverage.jsonl`, `memory/issues.json` |
| feedback | main | GitHub REST | inbox, style, format, lessons, last issue | edits to `publication/*.md`, `memory/lessons.md` |

## Why this shape

- **Separation of research and writing.** The writer never has web access.
  It can only use facts in the research pack, and the critic checks the
  draft against that same pack. This is what makes "everything is sourced"
  enforceable rather than aspirational.
- **Deterministic checks before model checks.** The linter (headings, length,
  banned vocabulary, link text, sign-offs) and the link verifier run in code.
  Their output is handed to the critic as ground truth. Cheap, reproducible,
  and they never hallucinate.
- **Structured outputs everywhere.** Every stage's contract is a pydantic
  model sent as `output_format`. Downstream code never parses prose.
- **Prompt caching by construction.** The system prompt for each stage is
  `role prompt + profile + style + format`, byte-identical across calls, with
  a cache breakpoint. Volatile content (the pack, the draft, dates) goes in
  the user turn.
- **Checkpoints on disk, repo as database.** Every artifact is a file under
  `issues/<id>/`. A rerun skips finished stages. The archive, RSS feed, and
  internal links are generated from `memory/issues.json`. There is no
  database to operate.
- **Feedback is a first-class stage with a durable target.** Feedback does
  not go into a prompt once; it edits the style guide, the format spec, and
  the lessons file that every subsequent run reads. The publisher can read
  and revert those edits in git.

## Policy and evals

`policy.yaml` is read by `poster/policy.py` (run-time enforcement) and by
`poster/evals/runner.py` (thresholds). The written policies in
`docs/policies/` explain each rule. The eval suite runs the real stage entry
points on synthetic fixtures under `evals/cases/` and writes results in the
hillclimb layout under `evals/results/`; every real run appends its quality
signals to `evals/production.jsonl`. See `docs/policies/eval-policy.md`.

## Safety rails

- `review_mode: gate` stops before publishing and writes `REVIEW.md`; the
  workflow opens a PR instead of pushing. A policy escalation does the same
  regardless of mode; a policy violation fails the run.
- A per-issue cost cap (`policy.yaml`) stops the run before publishing.
- Only allowlisted models can run any stage.
- `--dry-run` runs everything except the email send.
- The pipeline refuses to write an issue when research returns zero stories,
  and refuses to publish when the email provider fails (the site still
  renders; rerun with `--from publish`).
- `stop_reason: refusal` raises immediately; server-side fallbacks
  (`fallbacks: "default"`) are on by default so a classifier decline on one
  model is retried on another inside the same request.
- Truncated outputs (`max_tokens`) raise instead of being silently shipped.

## Cost and time

Per issue, expect roughly 8 to 10 model calls. The research call dominates
(web results are large) and can take several minutes. `issues/<id>/cost.json`
and `trace.jsonl` record the actual token usage and estimated USD per stage;
check them after the first few runs and tune `models.effort`,
`research.max_web_searches`, and `research.max_feed_items` from real numbers.
