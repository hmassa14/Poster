# AI use and transparency policy

## Models and configuration

- Only models on the allowlist in `policy.yaml` (`operations.allowed_models`)
  may run any stage. The pipeline refuses to start otherwise.
- The editorial model (`models.main`) writes, edits, and reviews. A cheaper
  model handles bulk triage. The eval judge is a different model from the
  one under test (`evals.judge_model`).
- Thinking is adaptive; effort is set per stage and recorded in the trace.
- Every model call is streamed, traced (`issues/<id>/trace.jsonl`) with
  token usage, the model that actually served it, stop reason, and cost.

## Transparency to readers

- Every issue carries the disclosure in `poster.yaml`. The page's JSON-LD
  names the editorial system as author and the human as publisher. The
  `generator` meta tag identifies the system.
- Readers are told how to send feedback and corrections, and that feedback
  changes how the system writes.
- The publication never claims experiences it did not have.

## External text is data, not instructions

- Web pages fetched during research, RSS content, and reader feedback are
  untrusted. Prompts wrap them in tags and instruct the model to treat them
  as data. Feedback that looks like an instruction injection is flagged to
  the model as such.
- The writer stage has no tools, so a compromised web page cannot cause a
  side effect beyond text in a draft, which the critic and policy stage then
  check against the research pack.
- The feedback stage can edit only `publication/style.md`,
  `publication/format.md`, `memory/lessons.md`, and `memory/corrections.jsonl`.
  It cannot touch prompts, code, policy, or workflows.

## Data handling

- Reader feedback is scrubbed of email addresses and phone numbers before
  any model sees it. Raw feedback stays in the repository's `feedback/`
  directory, which is private to the publisher.
- Issues never contain personal data (content safety policy).
- Model traces contain prompts and outputs but no reader data beyond the
  scrubbed feedback text. They are retained in git with the issue.
- No reader data is sent to any service other than the model provider and
  the email provider the publisher configured.

## Cost and operational limits

- A per-issue cost cap and a per-feedback-run cap are set in `policy.yaml`.
  A run that exceeds the cap stops before publishing and writes `REVIEW.md`.
- Web search and fetch calls per research pass are capped in `poster.yaml`.
- Output truncation and model refusals are hard errors, never silently
  shipped.

## Human oversight

- Level 0 (default, `review_mode: auto`): a human reads the published issue
  and the feedback; the policy stage escalates sensitive content to a human
  before publication.
- Level 1 (`review_mode: gate`): a human approves every issue.
- Level 2 (`BUTTONDOWN_STATUS=draft` or `send_email: false`): the site
  publishes automatically; email waits for a human.
- The publisher can stop the system at any time (kill switch in the policies
  README).
