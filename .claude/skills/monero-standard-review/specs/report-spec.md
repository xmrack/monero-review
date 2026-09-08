<!-- Read at delivery, once the workflow has returned. The heading grammar is
     a contract with scripts/labels.py; the section names match the deep
     review's so every issue in the repo reads alike. The stamp shares the deep
     review's `deep-scan` prefix on purpose -- one parser in
     .github/workflows/review.yml reads both, keyed on `profile`. -->

# `review.md`

One reader, and it is worth picturing them: someone who maintains Monero, has
limited time, and will decide per finding whether it is worth their afternoon.
They will check your citations. Write as though they will.

# Sections

```markdown
# Security review — <PR title>

**Author:** <the `Opened by:` login from PR_CONTEXT.md> · head `<sha12>`
**Scope:** <N> files, +<A>/-<B> lines · <subsystems touched>
**Boundaries:** <the trust boundaries the change reaches, or "none reachable">
**Result:** <2 findings: 1 MEDIUM, 1 LOW> — or "No findings."

## Summary

<Two or three sentences. What the change actually does, in your own words rather
than the author's title, and the one thing a maintainer needs to know before
deciding whether to read on. If nothing here matters, say that plainly — it is
the most useful summary there is.>

## Findings

### [SEVERITY] Short title

**Impact.** <What it gets someone. First, because it sets the priority.>

**Where.** `path/to/file.cpp:123` in `function_name`
<For a finding carrying `merged`: one line per site in `merged.sites`, and a
final line giving `merged.sameDefectBecause` — why these are one defect.>

**What.** <Two or three sentences naming the untrusted input, what it reaches,
and why nothing stops it, with a citation for each.>

**Why this diff.** <What changed to create it, and what `origin/base` shows.>

**Preconditions.** <What has to hold: a non-default flag, an attacker position,
a victim action. "None" is worth writing when it is true.>

**Fix.** <What to change, at the cause rather than at one caller.>

**Verification.** <n>/2 angles agreed (<which>). <For a merged finding, the
vote for each site: `src/rpc/c.cpp:42 2/2, src/rpc/c.cpp:51 2/2`.>

## Refuted

- ~~<candidate>~~ — <the angle that took it apart and the line that settled
  it.>
<Two refuted candidates killed by the same line share one bullet naming both
sites. Nothing merges the refuted list upstream, so this is yours to do — but
only for a genuinely identical refutation, and never by dropping a site.>

## Coverage

<The units the change was split into and the weakness classes run over each.
Then the changed files deliberately excluded, with the reason for each.
Then, if the workflow reported any, the changed files nobody accounted for --
named individually and described as neither reviewed nor excluded.
Then the limits of this tier, in one short paragraph and without hedging:
one researcher per unit rather than one per weakness class, no pass looking
across unit boundaries, no second look at any unit, and two verifier angles
per candidate rather than three.
Then the deferrals: every observation a researcher handed on rather than
filing, and how its adjudicator ruled. One that did not hold is reported with
the reason; one nobody could settle is named under Not covered with its file
and line.
Then the merge, when `coverage.mergeApplicable` is true: how many confirmed
candidates were read as one defect and published as a single entry, and which
ids went into each. When it is false there was nothing to nominate and there is
nothing to say. When `coverage.mergeFailed` is non-zero, say that a merge group
came back unusable and its findings are published separately — that is a
possible duplicate in the report, not a hidden one.
Then the counts: candidates proposed, candidates left after merging
duplicates, how many stood up, how many were refuted, and how many got no
verdict. Anything a researcher said it could not finish reading is reported as
that researcher's own account, not as established fact.>

## Checked and clear

- <What was examined, the check that was made, and the evidence. A short
  Findings section is only believable when this section carries weight.>

## Not covered

- <What could not be settled and why: a tool this run lacked, a claim needing
  a running binary, a submodule whose source was absent, a deferral nobody
  adjudicated.>

<!-- deep-scan profile=standard units=<n> cells=<n> failedCells=<n> angles=2 candidates=<n> confirmed=<n> published=<n> merged=<n> refuted=<n> unverified=<n> unaccounted=<n> deferred=<n> -->
```

# The summary is two or three sentences

It sits above everything and it is the only part some readers will finish, so it
carries the judgement, not the arithmetic.

Say what the change does, in your own words. The title is the author's framing
and this is your reading of the diff; where the two differ, that difference is
usually the most interesting sentence in the report. Then say what it means for
a maintainer: the one finding that matters, or the fact that nothing does.

What it must not be:

- **a restatement of `Result:`.** That line already gives the counts, one line
  above. A summary reading "2 findings: 1 MEDIUM, 1 LOW" has spent the reader's
  attention to tell them what they just read.
- **a description of the review.** No "I examined", no "this review covered",
  no method, no effort. Coverage says what was read and the footer says what ran.
- **hedged into meaninglessness.** "Some areas may warrant further review" is
  not a summary; it is a way of not writing one.
- **longer than three sentences.** A fourth sentence is a sign the finding
  belongs in `## Findings` where it can carry a citation.

On a no-findings review this section does the most work in the whole report.
"Adds a bounds check to the RPC handler and its test; nothing in the diff
reaches a trust boundary and nothing was removed" tells a maintainer they can
stop reading, and is worth more than three paragraphs of Checked-and-clear.

# There is no confidence word, on purpose

The heading is `### [SEVERITY] Title` and nothing else. It used to carry a
confidence beside the severity, and two graded words in one bracket read as one
scale: `[MEDIUM / medium]` tells a reader almost nothing and actively muddies
how bad the finding is, which is the only thing severity is for.

What confidence was standing in for is published instead, as a count the reader
can weigh: **`<n>/2 angles agreed`** on the Verification line. Two agreeing
verifiers on two angles is exactly as strong as that sentence sounds, and a
reader comparing this against a deep review's `<n>/3` can see the difference
without being told a word for it.

The workflow still computes a confidence internally — it orders findings and
decides which near-misses an advocate revisits. Do not publish it.

# The Verification line is a count, not a claim

`<n>/2 angles agreed` and the names of the angles that did. That is all. Do not
write that a finding was "thoroughly verified", "confirmed by an independent
panel", or anything else that describes the pipeline rather than reports its
output. The value of this shape over a single reviewer is that the number came
out of a program; dressing it up in adjectives is how it stops being worth
more.

# The coverage stamp is not decoration

The last line of the file, an HTML comment, invisible in the rendered issue and
read by `.github/workflows/review.yml` before it publishes anything.

| field | source |
| --- | --- |
| `profile` | the literal `standard`. Checked against the mode the harness dispatched: if they disagree, the run is treated as not having happened, because the wrong pipeline ran on this tier's budget |
| `units` | `coverage.units.length` |
| `cells` | `coverage.cells` |
| `failedCells` | `coverage.failedCells` |
| `angles` | the literal `2` |
| `candidates` | `coverage.candidatesDistinct` |
| `confirmed` | `coverage.confirmed` — CANDIDATES whose panel said holds, **not** the number of entries in `findings`. Those two used to be the same number and the merge stage separated them |
| `published` | `coverage.published` — the number of `###` entries you write under `## Findings` |
| `merged` | `coverage.merged` — confirmed candidates folded into another entry |
| `refuted` | the number of entries in `refuted` |
| `unverified` | `coverage.candidatesUnverified` |
| `unaccounted` | `coverage.unaccounted.length` |
| `deferred` | `coverage.deferred.length` |

`cells` is `coverage.cells` and **not** `coverage.researchAccount.length`.
The account holds one entry per pass that had something to report -- research
cells and the deferral adjudicators alike, distinguished by `kind`. On a clean
run it is **empty**. `coverage.cells` is the number of researchers dispatched
and `coverage.failedCells` counts only the ones that came back unusable.

`confirmed + refuted + unverified` must equal `candidates`, because every
candidate ends in exactly one of those buckets. The harness checks that
identity: a stamp failing it was not copied from a real result, and the report
is not published.

`published + merged` must equal `confirmed`, for the same kind of reason: every
confirmed candidate either gets an entry of its own or is folded into somebody
else's, and there is no third place for it to go. The harness checks this one
too. It is what makes the merge stage auditable from outside — a report with
five confirmed candidates and two entries has to say that three were folded, and
cannot quietly publish three fewer findings than the panel confirmed.

# Merged findings

Several confirmed candidates can turn out to be one defect: the same missing
check reported at two call sites, or one unvalidated field filed once as an
overflow and once as a resource exhaustion. A merge stage runs after the panel
and before you, and a finding it grouped arrives carrying a `merged` object.

Write it as **one** `### [SEVERITY]` entry. Its **Where.** lists every site in
`merged.sites`, its Verification line gives the vote per site, and one line says
why they are one defect — `merged.sameDefectBecause`, which names a shared
cause rather than a shared file.

Two things not to do with it. Do not split it back into one entry per site: the
whole point is that a maintainer sees one bug once, and `published` in the stamp
would then be wrong. And do not drop a site to shorten the entry — each one is a
place the defect is reachable and a place the fix has to hold.

Everything the merge did is in `coverage`: `mergeGroups` names the groups and
their member ids, `mergeClusters` how many groups were examined, and
`mergeFailed` how many came back unusable. A non-zero `mergeFailed` means those
findings are published unmerged, which may leave a duplicate in the report. Say
so in Coverage rather than leaving the reader to wonder why two entries look
alike.

Write the stamp even when everything failed. That is the case it exists for.
A run whose researchers all died returns no findings, and from outside
that is indistinguishable from a clean change — except by these numbers. The
harness refuses to publish on them, which leaves the pull request in the queue
to be reviewed again, instead of filing the issue that retires it forever.

# Length

The reader finishes a page and skims two. Findings around a dozen lines each;
`Refuted` one line each; `Checked and clear` one line per area, each ending in
a citation; `Coverage` a short table or list, not an essay. A mechanism that
needs more than a dozen lines is usually two findings or one that has not
finished being reduced.

# Never cross-reference the upstream pull request

Write `monero-project/monero PR 9559` or "this pull request" — never
`monero-project/monero#9559`, and never a github.com pull URL. Either shape in
a published issue body makes GitHub file a reference event on the upstream pull
request, putting a notification on a stranger's work. This pipeline reads
upstream and never touches it. The harness strips these shapes before
publishing, but that is a regex over prose; do not lean on it.

# Do not write a Verification footer

The harness appends one, from what actually happened. A claim of your own about
whether an adversarial pass ran will contradict the record and has done.
