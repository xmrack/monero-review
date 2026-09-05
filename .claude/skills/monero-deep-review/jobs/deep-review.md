# Reviewing one pull request

Resolve what is under review, start the run, write `review.md`.

## 1. Fix the range

The harness fetched the PR head and pointed `origin/base` at the branch it
targets. Confirm that instead of assuming it, one command per call:

- `git rev-parse --verify --quiet origin/base` — empty means this checkout was
  not prepared by the harness. Stop and say so. Without `origin/base` there is
  no honest range, and falling back to `master` would hand you an entire
  branch's divergence on any backport.
- `git rev-parse --short=12 HEAD` — the head under review. Quote it.

The range is `origin/base...HEAD`, three dots, never inside `$(...)`.

`PR_CONTEXT.md` opens with a `Pull request: <upstream>#<n>` line written by the
harness, outside the author-supplied fence, and then the author's own title.
Take the number and title from there and treat the rest as the author's claims.
If that line is absent — an older harness, or a checkout prepared by hand —
pass `pr: null` rather than guessing; the workflow handles it.

## 2. List the changed files

`git diff --name-only origin/base...HEAD`

Hand this list to the workflow exactly as git printed it. Do not filter it,
reorder it by what looks important, or trim it to something manageable. The
workflow's coverage check compares the mapper's answer against precisely this
list, so anything you drop here becomes a file that was never reviewed and
never reported as unreviewed — which is the one failure this job is built to
prevent.

An empty list means there is nothing to review: say so and stop.

For the report's Scope line: `git diff --shortstat origin/base...HEAD`

## 3. Confirm you can actually run it

Check that `Workflow` is among the tools available to you right now, with its
parameters. This skill's frontmatter asking for it proves nothing: the
scheduled pipeline runs with a narrow allowlist carrying neither `Workflow` nor
`Agent`, and this skill is written for a session where both are granted.

If it is missing, stop with one line — that the deep review needs the Workflow
tool, this session does not have it, so nothing ran, and `/monero-security-review`
is what to use here. Do not improvise around it. Dispatching the agents
yourself would yield a report claiming a verification nobody performed, which
is the one thing this skill must never produce.

**Say it in chat and write nothing to `review.md`.** That file is the
harness's input, not a place to leave a note. A file explaining why nothing
ran carries no severity heading, so `labels.py` reads it as a review that
found nothing, the harness files the issue that marks this pull request
reviewed, and it is never looked at again — a harness misconfiguration turned
into a permanent clean bill of health. An absent file is read correctly: the
run failed and the pull request stays in the queue.

In the CI harness the tool is granted (`.github/workflows/review.yml` appends
`Workflow` and the four `Agent(...)` grants when it is dispatched with
`mode=deep`), so reaching this stop there means the harness is misconfigured
and the run should be diagnosed rather than retried.

## 4. Start the run

```
Workflow({ name: "monero-deep-scan",
           args: { root: <absolute path of the checkout>,
                   pr: <number from PR_CONTEXT.md, or null>,
                   changedFiles: [<the list from step 2, verbatim>],
                   maxUnits: 8 } })
```

`root` has to be absolute. The agents `cd` to it before doing anything, because
the working directory is not reliably the checkout.

Send one short message before it goes quiet: what is under review, the head, the
file and line counts, that this is the deep pass, and that nothing is a finding
until the verifiers have finished. Then wait. Per-stage progress shows under
`/workflows`; do not narrate it yourself.

You get back `findings`, `refuted`, `unverified`, `coverage`, and a `next` line.
Follow `next`. Note that `unverified` is a list of candidates no panel decided,
while `coverage.candidatesUnverified` is only its count (plus any whose panel
threw, which are a count with no record) — when something has to be named, use
the list.

## 5. Write `review.md`

Read the REPORT SPEC now — not before — and write `review.md` in the repository
root with `Write`.

Severity and confidence arrive already settled: the workflow lowered any
severity its agreeing verifiers rated below the proposal, and capped confidence
by the count. Publish them as returned. `coverage.severityLowered` names each
one that moved, with both values.

Before you write a finding down, read its cited line and check it still says
what the candidate quoted. Nothing upstream does that for you, and a wrong
citation is the fastest way to lose the reader.

Coverage is not a formality. It must name:

- the units and the weakness classes run over each;
- every excluded file with its reason;
- **every path in `coverage.unaccounted`**, as neither reviewed nor excluded;
- whether the seam pass ran at all. `coverage.seamPassApplicable` is false on a
  single-unit change; `coverage.seamFailed` true means it was applicable and
  nobody looked, which is a limit on the review and must never be written up as
  a clean cross-unit result. Only when `coverage.seamRan` is true does
  `coverage.seamFresh` mean anything, and then it is worth stating at zero;
- what the per-unit second look found (`coverage.gapFresh`), and how many units
  it failed to cover (`coverage.gapFailed`);
- any id in `coverage.anchorDoubted` — a finding two verifiers could not find at
  its cited line. Re-anchor it from the code or drop the finding, and say which
  you did;
- `coverage.marginalReLooked` and `coverage.rescuedOnReLook`: how many
  candidates fell one vote short, and which the advocate saved;
- any research cell that came back empty-handed through failure rather than
  judgement — `coverage.failedCells` is the count, and the entries in
  `coverage.researchAccount` with `failed: true` name them;
- any candidate no panel decided: the `unverified` list names them, and
  `coverage.candidatesUnverified` counts them;
- `coverage.mapperFallback` when the partition was unusable and the whole change
  was read as one unit — complete, but blunter;
- `coverage.unitsAllowed` when it is below `coverage.unitCeiling`, since the cap
  scales with the size of the change.

Keep `refuted` in the report. It is most of what this pipeline produces and it
is how the next reviewer avoids buying a panel for the same idea twice.

End the file with the coverage stamp the REPORT SPEC describes — the HTML
comment carrying `cells`, `failedCells` and the rest, straight from `coverage`.
The harness reads it and refuses to publish a run whose research mostly failed,
because such a run and a genuinely clean one are otherwise indistinguishable
from the outside. Write it even when every cell failed; that is the case it
exists for.

## 6. Say what happened

A few sentences: what was reviewed, how many candidates were proposed, how many
stood up, and where `review.md` is. Claim no more verification than `coverage`
supports.

If `coverage.unaccounted` is not empty, lead with that rather than the findings.
If `coverage.failedCells` is a large share of the cells dispatched, lead with
*that*: the run did not review what it set out to, and no number of clean units
makes up for the ones nobody read.

"No findings" is a complete and ordinary result. Say it plainly.

## Out of scope for this job

Nothing is commented upstream, no branch is pushed, no code from the PR is built
or executed. The deliverable is `review.md` on disk. What becomes of it is the
harness's business.
