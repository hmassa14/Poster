# Evaluation policy

The system publishes without a human in the drafting loop, so the evals are
where quality is guaranteed. This policy says what is measured, when, and
what happens when a number moves.

## What is measured

Offline evals (`poster eval`) run the real stage entry points on synthetic
fixtures under `evals/cases/`. Fixtures use fictional companies and products
so nothing is answerable from the model's memory and no real person can be
defamed by a test.

| Flow | Question | Grader | Primary metrics |
|---|---|---|---|
| `critic` | Does the fact-checker catch seeded errors, and leave clean drafts alone? | Programmatic: seeded mutations matched against the critic's issues by location | recall on seeded errors; specificity on clean drafts; score calibration |
| `writer` | Does the writer stay inside the research pack and follow the format and style? | Programmatic grounding (every number and URL in the draft is in the pack) + linter + model-graded rubric of checkable criteria | grounded rate; lint pass rate; rubric mean |
| `triage` | Does triage keep consequential stories, drop noise, and merge duplicates? | Programmatic against labeled items | recall; precision; merge accuracy |
| `escalation` | Does the standards classifier escalate what it should and not what it should not? | Programmatic against labeled drafts | recall; specificity |
| `seo` | Does the SEO package satisfy hard constraints and use only facts from the issue? | Programmatic | constraint pass rate; keyword grounding |

Every flow records per-case status (`ok`, `truncated`, `refused`), the
model that served each call, token usage, judge usage separately, and the
full transcript in `traces/`. Infra errors go to `errors.jsonl`, never into
the scores.

## When evals run

- **Before merge:** the `Evals` workflow runs on pull requests that touch
  `prompts/`, `publication/`, `policy.yaml`, `poster/`, or `templates/`. A
  metric below its threshold in `policy.yaml` fails the check.
- **Before a model change:** run all flows with `--model <new>` and compare
  against the stored baseline before changing `poster.yaml`.
- **Weekly, in production:** every real run appends its quality signals
  (critic scores, revision rounds, lint errors, link failures, policy
  flags, cost, served models) to `evals/production.jsonl`.
  `poster eval report` summarises the trend.
- **After feedback edits:** the feedback stage's automated rule changes are
  covered by the next PR-triggered or manual eval run; a quarterly full run
  is part of the publisher's routine.

## Thresholds

Thresholds live in `policy.yaml` under `evals.thresholds` and are the
minimum, not the target. They were set from the first baseline run and are
raised, never lowered, without a written rationale in the PR.

## Harness health

Before trusting a number, the harness itself is checked (`poster eval
--smoke`): an oracle output must score near 100% and a null output near 0%
on every programmatic grader. The offline test suite (`tests/test_evals.py`)
runs the same oracle/null checks without an API key.

## Variance

Model outputs vary run to run. Reps are configurable (`--reps`); a
difference smaller than the spread across reps is not a result. The report
shows the mean and the standard deviation per metric.

## Human evaluation

Once a quarter the publisher reads three issues end to end against the
editorial policy and files anything they would not have shipped as feedback.
That reading is the ground truth the automated rubric is calibrated to; when
the two disagree, the rubric changes.
