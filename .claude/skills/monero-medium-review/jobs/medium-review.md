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

## 2. Take the changed-file list

`PR_FILES.md` already holds it, one path per line, written by the harness from
`git diff --name-only origin/base...HEAD` before you started. Read it rather
than re-deriving it — and if it is absent, run that command yourself and say in
the report that the harness did not provide the list.

Hand the list to the workflow exactly as it stands. Do not filter it, reorder
it by what looks important, or trim it to something manageable. The workflow's
coverage check compares the mapper's answer against precisely this list, so
anything you drop here becomes a file that was never reviewed and never
reported as unreviewed — which is the one failure this shape is built to
prevent.

An empty list means there is nothing to review: say so and stop.

For the report's Scope line: `git diff --shortstat origin/base...HEAD`

## 3. Confirm you can actually run it

Check that `Workflow` is among the tools available to you right now, with its
parameters. This skill's frontmatter asking for it proves nothing: the default
review runs with a narrow allowlist carrying neither `Workflow` nor `Agent`,
and this skill is written for a session where both are granted.

If it is missing, stop with one line — that the medium review needs the
Workflow tool, this session does not have it, so nothing ran, and
`/monero-security-review` is what to use here. Do not improvise around it.
Dispatching the agents yourself would yield a report claiming a verification
nobody performed, which is the one thing this skill must never produce.

**Say it in chat and write nothing to `review.md`.** That file is the
harness's input, not a place to leave a note. A file explaining why nothing
ran carries no severity heading, so `labels.py` reads it as a review that
found nothing, the harness files the issue that marks this pull request
reviewed, and it is never looked at again — a harness misconfiguration turned
into a permanent clean bill of health. An absent file is read correctly: the
run failed and the pull request stays in the queue.

## 4. Start the run

```
Workflow({ name: "monero-deep-scan",
           args: { root: <absolute path of the checkout>,
                   pr: <number from PR_CONTEXT.md, or null>,
                   profile: "medium",
                   changedFiles: [<the list from step 2, verbatim>],
                   maxUnits: 5 } })
```

`profile: "medium"` is not optional and not a hint. The workflow defaults an
unrecognised profile to `deep`, deliberately — a typo should cost money rather
than coverage — so omitting it here buys the full three-hour pipeline on a
budget that did not ask for it.

`root` has to be absolute. The agents `cd` to it before doing anything, because
the working directory is not reliably the checkout. Prefer passing `args` as a
real object rather than a JSON-encoded string; both work, an object is the
documented shape.

Send one short message before it goes quiet: what is under review, the head, the
file and line counts, that this is the medium pass, and that nothing is a
finding until the verifiers have finished.

## 4b. Wait for it — this is not optional

The Workflow tool **always returns immediately**. Its result says
`Workflow launched in background. Task ID: <id>` and the fleet then runs
outside your turn. If you end your turn there, the run ends with it: measured
on the first CI deep run, the Lead said "I'll wait for it to finish", stopped,
and the session exited `success` after 52 seconds having killed every agent it
had just dispatched. Nothing was refused and nothing errored. It simply walked
away from work it had already paid to start.

So take the `Task ID` from that result and block on it:

```
TaskOutput({ task_id: "<the Task ID>", block: true, timeout: 600000 })
```

600000ms is the maximum per call. If it comes back `not_ready` or still
running, **call it again**, and keep calling until it returns the workflow's
result. This tier is a smaller fleet than the deep one — on a five-unit change
it is about eight agents at an effective concurrency of two — so expect
several calls, not dozens. Do not end your turn, do not start writing
`review.md`, and do not summarise anything until that result is in your hands.

You get back `findings`, `refuted`, `unverified`, `coverage`, and a `next` line.
Follow `next`. Note that `unverified` is a list of candidates no panel decided,
while `coverage.candidatesUnverified` is only its count (plus any whose panel
threw, which are a count with no record) — when something has to be named, use
the list.

If the workflow genuinely fails rather than returning — the task dies, or
`TaskOutput` reports an error rather than a result — say so and write nothing.
A report with no pipeline behind it is the one thing this skill must never
produce.

## 5. Write `review.md`

Read the REPORT SPEC now — not before — and write `review.md` in the repository
root with `Write`.

Severity and confidence arrive already settled: the workflow lowered any
severity its agreeing verifiers rated below the proposal, and capped confidence
by the count. Publish them as returned. Nothing at this tier reaches `high`
confidence, because that needs three agreeing angles and there are two —
`coverage.angles` names them. `coverage.severityLowered` names each finding
whose severity moved, with both values.

Before you write a finding down, read its cited line and check it still says
what the candidate quoted. Nothing upstream does that for you, and a wrong
citation is the fastest way to lose the reader.

Coverage is not a formality, and at this tier it carries more weight than at
any other, because the reader has to be able to tell a thin result from a
thorough one. It must name:

- the units and the weakness classes run over each;
- every excluded file with its reason;
- **every path in `coverage.unaccounted`**, as neither reviewed nor excluded;
- **the three things this profile does not do**, plainly and without apology:
  no cross-unit pass (`coverage.seamPassApplicable` is false and
  `coverage.roundTwoRan` says why), no per-unit second look, and two verifier
  angles rather than three. A reader who does not know that will read a clean
  medium report as a clean deep one;
- any id in `coverage.anchorDoubted` — a finding both verifiers could not find
  at its cited line. Re-anchor it from the code or drop the finding, and say
  which you did;
- any research cell that came back empty-handed through failure rather than
  judgement — `coverage.failedCells` is the count, and the entries in
  `coverage.researchAccount` with `failed: true` name them. One failed cell
  matters more here than at the deep tier: it is a whole unit that nobody
  read, and there is no second pass behind it;
- any candidate no panel decided: the `unverified` list names them, and
  `coverage.candidatesUnverified` counts them;
- **the deferrals.** `coverage.deferred` holds every observation a researcher
  noticed, judged somebody else's unit, and handed on instead of filing. Each
  got an adjudicator and carries a `ruling`: `filed` means it became a
  candidate and needs no separate mention; `did-not-hold` means somebody read
  the code and it did not survive — say what it was and give the reason the
  adjudicator returned, which is in `coverage.researchAccount` under the
  matching `deferred/<n>` tag. Every entry in `coverage.deferredUnclaimed` is
  one whose adjudicator came back unusable, so nothing ever looked at it:
  quote those with their file and line under *Not covered*;
- `coverage.mapperFallback` when the partition was unusable and the whole
  change was read as one unit by one researcher — complete, but the bluntest
  thing this tier can do, and barely better than the default review;
- `coverage.unitsAllowed` when it is below `coverage.unitCeiling`.

Give the file arithmetic so it can be checked: every unit's file list either
names every path or gives a count and names none, and Coverage states the total
accounted for against `coverage.unaccounted`.

Keep `refuted` in the report. It is most of what this pipeline produces and it
is how the next reviewer avoids buying a panel for the same idea twice.

End the file with the coverage stamp the REPORT SPEC describes. The harness
reads it and refuses to publish a run whose research mostly failed, or whose
panels mostly returned no verdict, because such a run and a genuinely clean one
are otherwise indistinguishable from the outside. Write it even when everything
failed; that is the case it exists for. `profile=medium` in that stamp is
checked against the mode the harness dispatched, so it has to be the profile
you actually passed in step 4.

## 6. Say what happened

A few sentences: what was reviewed, how many candidates were proposed, how many
stood up, and where `review.md` is. Claim no more verification than `coverage`
supports, and say plainly that this was the medium tier.

If `coverage.unaccounted` is not empty, lead with that rather than the findings.
If `coverage.failedCells` is a large share of the cells dispatched, lead with
*that*: the run did not review what it set out to, and no number of clean units
makes up for the ones nobody read.

"No findings" is a complete and ordinary result. Say it plainly.

## Out of scope for this job

Nothing is commented upstream, no branch is pushed, no code from the PR is built
or executed. The deliverable is `review.md` on disk. What becomes of it is the
harness's business.
