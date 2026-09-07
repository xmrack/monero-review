<!-- Read at delivery, once the workflow has returned. The heading grammar is
     a contract with scripts/labels.py; the section names match the default
     and deep reviews' so a medium review reads like every other issue in the
     repo. The stamp shares the deep review's `deep-scan` prefix on purpose --
     one parser in .github/workflows/review.yml reads both, keyed on
     `profile`. -->

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
Then the counts: candidates proposed, candidates left after merging
duplicates, how many stood up, how many were refuted, and how many got no
verdict. Anything a researcher said it could not finish reading is reported as
that researcher's own account, not as established fact.>

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

**Verification.** <n>/2 angles agreed (<which>).

## Refuted

- ~~<candidate>~~ — <the angle that took it apart and the line that settled
  it.>

## Checked and clear

- <What was examined, the check that was made, and the evidence. A short
  Findings section is only believable when this section carries weight.>

## Not covered

- <What could not be settled and why: a tool this run lacked, a claim needing
  a running binary, a submodule whose source was absent, a deferral nobody
  adjudicated.>

<!-- deep-scan profile=medium units=<n> cells=<n> failedCells=<n> angles=2 candidates=<n> confirmed=<n> refuted=<n> unverified=<n> unaccounted=<n> deferred=<n> -->
```

# Confidence at this tier

`high` needs three agreeing angles and there are two, so the workflow caps
every surviving finding at `medium` however sure its proposer was. Publish what
it returns. Do not talk a finding up to `high` in prose because the argument
reads strongly to you — the cap is the honest statement of what two agreeing
verifiers establish, and a reader comparing a medium review against a deep one
is entitled to that difference being visible.

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
| `profile` | the literal `medium`. Checked against the mode the harness dispatched: if they disagree, the run is treated as not having happened, because the wrong pipeline ran on this tier's budget |
| `units` | `coverage.units.length` |
| `cells` | `coverage.cells` |
| `failedCells` | `coverage.failedCells` |
| `angles` | the literal `2` |
| `candidates` | `coverage.candidatesDistinct` |
| `confirmed` | the number of entries in `findings` |
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

Write the stamp even when everything failed. That is the case it exists for.
A medium run whose researchers all died returns no findings, and from outside
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
