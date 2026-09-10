# Content safety policy

The publication covers AI news for practitioners. Most weeks that is routine
industry reporting. This policy exists for the weeks when it is not.

## Prohibited content (blocks publishing)

The policy stage fails the run when an issue contains:

- Personal data: email addresses, phone numbers, home addresses, or other
  identifiers of private individuals.
- Defamatory characterisation of a person or company in the publication's
  own voice ("X is a fraud"). Reporting that a court or regulator found
  something is permitted with a link to the finding.
- Claims that the system itself tested, used, or experienced a product.
- Reproduced copyrighted text beyond the quotation limits.

## Sensitive topics (require a human before publishing)

The escalation classifier and a keyword backstop flag these categories. A
flag forces the review gate for that run; a human reads the flagged passages
and publishes with `--acknowledge-escalation` or edits `final.md` first.

| Category | Definition | Why a human |
|---|---|---|
| `legal_named_individual` | Allegations, lawsuits, or investigations concerning a named private individual | Defamation exposure; the publisher's name is on it |
| `death_or_injury` | A death, serious injury, or suicide connected to an AI product | Tone, accuracy, and care for those involved |
| `security_exploit` | Operational detail of an unpatched exploit, jailbreak, or vulnerability | Could enable harm; coordinate with disclosure norms |
| `election_or_political_persuasion` | Content that could influence voting or takes a partisan position | The publication is not a political outlet |
| `medical_legal_financial_advice` | Specific advice to readers in a regulated domain | Liability; readers may act on it |
| `minors` | Content involving minors in a harmful context | Care and legal exposure |
| `unverified_major_claim` | A lead story resting on a single unverified or anonymous source | Editorial policy 5 |

Public figures acting in their public roles (a CEO announcing a product, a
regulator issuing a decision) are not "private individuals". Executives named
in a lawsuit are. When in doubt the classifier is instructed to escalate.

## Handling of people

- Named individuals appear only in their public roles and only with claims
  sourced to their own statements or to official records.
- The publication does not speculate about anyone's motives, health, or
  private life.
- Quotes from private individuals (forum posts, social media) are not used
  without a link to the public post and a public role that makes them
  relevant.

## Security research

Vulnerabilities and jailbreaks are covered at the level of "what was found,
who found it, what was fixed, what to update". Operational detail sufficient
to reproduce an unpatched issue is not published; the classifier escalates
and the publisher decides.

## What the system does not publish at all

- Instructions for causing harm, in any domain.
- Content sexualising anyone, or involving minors in a harmful context.
- Harassment of, or targeted content about, a private individual.
- Political endorsements or persuasion.

These are enforced by the escalation gate and, if a draft ever reaches them,
by the model's own refusal behaviour, which the pipeline treats as a hard
stop rather than something to route around.
