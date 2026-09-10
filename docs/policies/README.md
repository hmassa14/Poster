# Policies

These documents govern how *This Week in AI* is produced by the Poster system.
Wherever a rule can be checked by code, it is: `policy.yaml` is the
machine-readable version, `poster/policy.py` enforces it on every run, and the
eval suite (`docs/policies/eval-policy.md`) verifies the model-driven parts.
A rule that exists only in prose is a rule that will drift; when you change a
policy, change the code and the evals in the same commit.

| Policy | Covers | Enforced by |
|---|---|---|
| [Editorial policy](editorial-policy.md) | Sourcing, attribution, quotes, rumours, corrections, disclosure | critic stage, linter, `check_content`, renderer |
| [Content safety policy](content-safety-policy.md) | Prohibited content, sensitive topics, named individuals, escalation to a human | `check_content`, escalation classifier, review gate |
| [AI use and transparency policy](ai-use-policy.md) | Which models, disclosure, provenance, prompt injection, data handling, logging, cost | model allowlist, disclosure check, PII scrub, cost cap, traces |
| [Copyright and attribution policy](copyright-policy.md) | Quotation limits, linking not copying, images | `check_content` quote limits, linter link rules |
| [Evaluation policy](eval-policy.md) | What must be measured before and after changes ship | `poster eval`, CI thresholds, `evals/production.jsonl` |

## Governance

- **Owner.** The publisher (Haley Massa) owns these policies and is the human
  of record for the publication. The system has no authority to change them;
  the feedback stage may only append to the style guide, the format spec, and
  the lessons file, never to `policy.yaml` or this directory.
- **Human oversight levels.** `review_mode: auto` publishes without a human
  unless the policy stage escalates. `review_mode: gate` requires a human to
  approve every issue. Escalations always require a human regardless of mode.
  The `--acknowledge-escalation` flag is the record that a human read the
  flagged passages.
- **Kill switch.** Disable the `Weekly issue` workflow in the Actions tab, or
  set `publishing.send_email: false` in `poster.yaml` to stop email while
  keeping the site. Either takes effect on the next run.
- **Corrections.** A correction is any change to a published fact. It is
  filed as a GitHub issue labeled `feedback`, folded in by the feedback stage,
  printed in the next issue's "Corrections" section, and the original page
  is updated with the correction appended, never silently rewritten.
- **Incident procedure.** If a published issue contains a policy violation
  (defamation, PII, an unverified claim about a person, copyrighted text):
  1. Unpublish the page (delete `site/issues/<slug>/` and push) and, if the
     email went out, send a correction email the same day.
  2. File the correction as feedback so the next issue acknowledges it.
  3. Write the failure into the eval suite as a new case so it is measured
     from then on. An incident that does not produce an eval case is not
     closed.
- **Change control.** Prompt, style, format, policy, and model changes go
  through a pull request that runs the eval suite. A change that lowers any
  metric below its threshold in `policy.yaml` does not merge. The feedback
  stage's automated edits are committed directly but are reviewable and
  revertible in git; a quarterly read of `publication/style.md`'s
  "Learned rules" is part of the publisher's routine.
- **Review cadence.** Policies are reviewed quarterly and after any incident.
  Eval thresholds are reviewed when the production trend in
  `evals/production.jsonl` moves for three consecutive issues.
