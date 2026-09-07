<!-- Read at delivery, once the workflow has returned. The heading grammar is
     a contract with scripts/labels.py; the section names match the default
     review's so a deep review reads like every other issue in the repo. -->

# `review.md`

One reader, and it is worth picturing them: someone who maintains Monero, has
limited time, and will decide per finding whether it is worth their afternoon.
They will check your citations. Write as though they will.

# Sections

```markdown
# Security review — <PR title>

**Scope:** <N> files, +<A>/-<B> lines · <subsystems touched>
**Boundaries:** <the trust boundaries the change reaches, or "none reachable">
**Result:** <2 findings: 1 MEDIUM, 1 LOW> — or "No findings."

## Coverage

<Units the change was split into and the weakness classes run over each.
Then the changed files deliberately excluded, with the reason given for each.
Then, if the workflow reported any, the changed files nobody accounted for --
named individually and described as neither reviewed nor excluded.
Then what the extra passes did: whether the seam pass ran (it does not on a
single-unit change) and what crossing a boundary turned up, and what the
per-unit second look found that the first round missed. Both are worth stating
even at zero -- a zero from the seam pass is evidence about the change, and its
absence is a limit on the review.
Then the counts: candidates proposed, candidates left after merging duplicates,
how many stood up, how many were one vote short and re-looked, and how many of
those the advocate rescued. Anything a researcher said it could not finish
reading is reported as that researcher's own account, not as established fact.>

## Findings

### [SEVERITY / CONFIDENCE] Short title

**Impact.** <What it gets someone. First, because it sets the priority.>

**Where.** `path/to/file.cpp:123` in `function_name`

**What.** <Two or three sentences naming the untrusted input, what it reaches,
and why nothing stops it, with a citation for each.>

**Why this diff.** <What changed to create it, and what `origin/base` shows.>

**Preconditions.** <What has to hold: a non-default flag, an attacker position,
a victim action. "None" is worth writing when it is true.>

**Fix.** <What to change, at the cause rather than at one caller.>

**Verification.** <n>/3 angles agreed (<which>). <For a finding carrying
`rescued`: say that two angles rejected it, name what each relied on, and give
the line the advocate showed they were wrong about. Its confidence stays `low`
however strong the argument reads -- it is published against the panel's
majority and the reader is entitled to know it.>

## Refuted

- ~~<candidate>~~ — <the angle that took it apart and the line that settled
  it.>

## Checked and clear

- <What was examined, the check that was made, and the evidence. A short
  Findings section is only believable when this section carries weight.>

## Not covered

- <What could not be settled and why: a tool this run lacked, a claim needing
  a running binary, a submodule whose source was absent.>

<!-- deep-scan units=<n> cells=<n> failedCells=<n> candidates=<n> confirmed=<n> refuted=<n> unverified=<n> unaccounted=<n> deferred=<n> -->
```

# Rules

**Severity and confidence come back already decided.** The workflow lowered any
severity its agreeing verifiers rated below the proposal, and capped confidence
by how many agreed. Publish what it returned. `coverage.severityLowered` lists
every one that moved, with both values -- note it in that finding's
**Verification.** line.

**Order by severity, then confidence.** People stop reading partway down.

**Check each anchor before you write it.** Read the cited line and confirm it
still says what the candidate quoted. Nothing upstream does this for you.

**Nothing was executed.** No build, no test, no proof of concept, anywhere in
this pipeline. Never phrase a finding so that it implies otherwise.

**Keep the refuted list.** It is most of what a deep review produces, and it is
how the next reviewer avoids spending a panel on the same idea. Dropping it to
look decisive throws away the expensive part.

**Nominate the durable refutations.** Where a refutation settles something about
this codebase rather than about this diff -- what epee's serializer really
bounds, what a zero scalar does, which zone a limit applies to -- say so and
name it as worth adding to `.claude/skills/monero-security-review/references/refutations.md`. That file is why the
next review does not re-propose it, and this pipeline is the cheapest place to
grow it. Do not edit it from here: propose, and let a human land it.

**"No findings" is a finished report.** It is also the common outcome on this
queue. What makes it worth reading is Coverage and Checked-and-clear having real
content. Do not pad, and do not soften something real to be kind about the code.

**Lead with a coverage gap if there is one.** Files nobody accounted for matter
more than a LOW, because they are the part a "no findings" would otherwise
overstate.

# The coverage stamp is not decoration

The last line is an HTML comment, invisible when rendered, and the harness
reads it. Emit it **always**, as the final line, with every field present and
every value a plain integer taken verbatim from the returned `coverage`
object -- never a number you reasoned your way to.

| field | from |
| --- | --- |
| `units` | `coverage.units.length` |
| `cells` | `coverage.cells` |
| `failedCells` | `coverage.failedCells` |
| `candidates` | `coverage.candidatesDistinct` |
| `confirmed` | the returned `findings` array's length |
| `refuted` | the returned `refuted` array's length |
| `unverified` | `coverage.candidatesUnverified` |
| `unaccounted` | `coverage.unaccounted.length` |
| `deferred` | `coverage.deferredUnclaimed.length` |

`cells` is `coverage.cells` and **not** `coverage.researchAccount.length`.
`researchAccount` is an exception log, not a roster: a pass is recorded there
only when it failed outright or came back `notFinished`, and its entries span
cells, the seam pass and the gap pass alike, distinguished by `kind`. On a
clean run it is **empty**. `coverage.cells` is the number of research cells
dispatched and `coverage.failedCells` counts only the `kind: "cell"` failures
among them, so those two are the pair that can honestly be divided into each
other -- which is exactly what the harness does.

`confirmed + refuted + unverified` must equal `candidates`. That is not a rule
imposed on you -- every candidate ends in exactly one of those three buckets,
so it holds by construction in any real result. The harness checks it, and a
stamp that fails it is treated as fabricated and the report is not published.
If your numbers do not add up, you took them from the wrong place; go back to
`coverage` rather than adjusting one to fit.

It exists because of one failure mode the prose cannot cover, and the fleet has
**two halves that die separately**. If the researchers die, nothing was read.
If the researchers work and the verifier panels die, every candidate comes back
`unverified` and `findings` is empty -- and an honest report of either is a
report with no findings in it. To `labels.py` and to the harness that is
byte-for-byte a clean review, and publishing it files the issue that marks this
pull request reviewed forever. The stamp is the only thing that separates
"three verifiers looked and found nothing" from "nobody looked".

So the harness refuses to publish on these numbers when most cells failed, when
most candidates got no verdict, or when the arithmetic does not hold. Reporting
them accurately matters more than the report reading well.

Write it even when everything failed. Especially then.

# Never cross-reference the upstream pull request

Write `monero-project/monero PR 9559`, or just "this pull request". Never
`monero-project/monero#9559`, and never a `https://github.com/.../pull/9559`
link. GitHub turns either shape in an issue body into a reference event on the
target, which posts a notification onto a stranger's pull request. This
pipeline reads upstream and never touches it, and that has to hold for the
report as much as for the tools. The same goes for any other repository's
issues or pull requests you cite.

The harness rewrites these shapes out of `review.md` immediately before
publishing, so a slip is caught -- but it is caught by a regex over
model-written prose, which is the weakest kind of guarantee. Do not rely on it.

# The grammar is load-bearing

`scripts/labels.py` labels the published issue from this file. It reads finding
headings as `### [SEVERITY ...]` and stops counting at the first `## Refuted`.
So:

- headings stay `### [SEVERITY / CONFIDENCE] Title`, severity spelled
  `CRITICAL`, `HIGH`, `MEDIUM` or `LOW`;
- `## Refuted` keeps that exact spelling and stays **below** `## Findings` --
  above it, every real finding stops labelling the issue. Emit the heading
  even when nothing was refuted (`- none`): it is where `labels.py` stops
  reading, and a report without it has no stopping point;
- a refuted entry never gets a `###` heading of its own;
- **a bracketed-severity `###` heading appears only under `## Findings`.**
  `labels.py` reads everything ABOVE the first `## Refuted` as a finding, so
  such a heading in `## Coverage` -- a candidate no panel decided, an id in
  `coverage.anchorDoubted` -- labels the published issue as though it were a
  confirmed finding. Write those as bullets. Below `## Refuted` the risk is
  smaller, because that is where `labels.py` stops reading; it is only a
  danger in a report that omitted `## Refuted`, which is the other half of why
  the rule above says always emit it.

Measured against `labels.py`, not assumed: a report written from this template
with one MEDIUM and one LOW finding yields `medium, low`; a bracketed severity
inside a refuted bullet is correctly ignored; and moving `## Refuted` above
`## Findings` yields nothing at all. The template block itself yields nothing,
because its placeholder heading has no real severity word in it -- which is
also the check that the regex is matching severities rather than brackets.
