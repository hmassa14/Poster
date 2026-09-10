# Issue format

The writer produces Markdown that follows this structure. The linter checks the
section headings. The feedback stage may edit this file.

```
# {Title}                          <- short, evocative, specific. Not "This Week in AI #12".
*{Dek}*                            <- one sentence, the thesis of the week.

## The week in one paragraph
{120-180 words. What happened, why the lead story leads, what the pattern is.}

## The lead: {lead headline}
{350-550 words. What happened (sourced), what is actually new, what it changes
for practitioners, what is still unknown. At least three links. Ends with a
one-sentence "what to watch".}

## Also this week
{5-8 items. Each item:}
**{Item headline}.** {70-130 words. Link in the first sentence. Fact, context,
implication. Vendor claims labeled as such.}

## Research corner
{1-3 papers or technical reports. Each: what it shows, the benchmark or
evidence, why a practitioner should care. Skip the section if nothing qualifies
this week; write the heading followed by one sentence saying so is NOT allowed.
Simply omit it.}

## Signal vs. noise
{One claim that circulated this week and what the evidence actually supports.
120-200 words.}

## Worth your time
{2-4 links with one-line descriptions: a talk, a thread, a doc, a tool.}

## Corrections
{Only when the feedback file for this issue contains corrections. Otherwise omit.}
```

Rules:
- Total length 1400-2400 words, excluding the footer the renderer adds.
- Required headings: "The week in one paragraph", "The lead:", "Also this week",
  "Signal vs. noise", "Worth your time". Optional: "Research corner", "Corrections".
- No other H2 sections. H3 is not used.
- Do not write a closing sign-off, a "see you next week", or a summary. The
  renderer appends the disclosure and subscription footer.
