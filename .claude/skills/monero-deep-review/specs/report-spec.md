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
Then the counts: candidates proposed, candidates left after merging duplicates,
how many stood up. Anything a researcher said it could not finish reading is
reported as that researcher's own account, not as established fact.>

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

**Verification.** <n>/3 angles agreed (<which>).

## Refuted

- ~~<candidate>~~ — <the angle that took it apart and the line that settled
  it.>

## Checked and clear

- <What was examined, the check that was made, and the evidence. A short
  Findings section is only believable when this section carries weight.>

## Not covered

- <What could not be settled and why: a tool this run lacked, a claim needing
  a running binary, a submodule whose source was absent.>
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

**"No findings" is a finished report.** It is also the common outcome on this
queue. What makes it worth reading is Coverage and Checked-and-clear having real
content. Do not pad, and do not soften something real to be kind about the code.

**Lead with a coverage gap if there is one.** Files nobody accounted for matter
more than a LOW, because they are the part a "no findings" would otherwise
overstate.

# The grammar is load-bearing

`scripts/labels.py` labels the published issue from this file. It reads finding
headings as `### [SEVERITY ...]` and stops counting at the first `## Refuted`.
So:

- headings stay `### [SEVERITY / CONFIDENCE] Title`, severity spelled
  `CRITICAL`, `HIGH`, `MEDIUM` or `LOW`;
- `## Refuted` keeps that exact spelling and stays **below** `## Findings` --
  above it, every real finding stops labelling the issue;
- a refuted entry never gets a `###` heading of its own.

Verified against `labels.py` rather than assumed: this template yields
`medium, low`, a bracketed severity inside a refuted bullet is correctly
ignored, and moving `## Refuted` above `## Findings` yields nothing at all.
