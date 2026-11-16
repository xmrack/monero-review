# Reviewing one pull request

Resolve what is under review, start the run, write `review.md`.

## 1. Fix the range

Confirm the harness's setup, one command per call:

- `git rev-parse --verify --quiet origin/base`: empty means this checkout was
  not prepared by the harness. Stop and say so. Never fall back to `master`.
- `git rev-parse --short=12 HEAD`: the head under review. Quote it.

The range is `origin/base...HEAD`, three dots, never inside `$(...)`.

`PR_CONTEXT.md` opens with a `Pull request: <upstream>#<n>` line written by the
harness, outside the author-supplied fence, and then the author's own title.
Take the number and title from there and treat the rest as the author's claims.
If that line is absent, pass `pr: null` rather than guessing.

The harness also writes a `PR state:` line: `open`, `merged` or `closed`.
On `merged`, confirm `git rev-parse --verify --quiet origin/master` and pass
`masterRef: "origin/master"` in step 4. If the ref is missing, pass no
`masterRef` and say under **Not covered** that the findings were not checked
against master. On `closed`, pass no `masterRef` and say in the summary that
its code did not land. On anything else, pass no `masterRef`.

## 2. Take the changed-file list

`PR_FILES.md` already holds it, one path per line. Read it rather than
re-deriving it. If it is absent, run `git diff --name-only origin/base...HEAD`
yourself and say in the report that the harness did not provide the list.

Hand the list to the workflow exactly as it stands. Do not filter it, reorder
it, or trim it: anything you drop becomes a file never reviewed and never
reported as unreviewed.

An empty list means there is nothing to review: say so and stop.

For the report's `Change:` line: `git diff --shortstat origin/base...HEAD`

## 3. Confirm you can actually run it

Check that `Workflow` is among the tools available to you right now, with its
parameters. This skill's frontmatter and the workflow's allowlist prove
nothing. There is no second tool to check for: the result arrives as a
completion notification (step 4b).

If `Workflow` is missing, stop with one line saying this session does not have
it, so nothing ran. There is no lesser reviewer to fall back to. Do not
improvise around it, and do not dispatch the agents yourself.

**Say it in chat and write nothing to `review.md`.** A file there is read as a
review that found nothing, and retires the pull request. An absent file keeps
it in the queue.

## 4. Start the run

```
Workflow({ name: "monero-deep-scan",
           args: { root: <absolute path of the checkout>,
                   pr: <number from PR_CONTEXT.md, or null>,
                   profile: "standard",
                   changedFiles: [<the list from step 2, verbatim>],
                   maxUnits: 5,
                   changedLines: <the sum of the counts in PR_NUMSTAT.txt>,
                   lineCounts: <an object from PR_NUMSTAT.txt: each path to its count>,
                   priorFindings: <the array in PR_PRIOR.json, verbatim; [] when absent>,
                   masterRef: <"origin/master" when step 1 says merged, else omit> } })
```

`profile: "standard"` is required: the workflow defaults an unrecognised
profile to `deep`.

`root` has to be absolute. Pass `args` as a real object rather than a
JSON-encoded string.

`PR_NUMSTAT.txt` holds `<changed lines><TAB><path>` per file. Pass the sum as
`changedLines` and the pairs as `lineCounts`. `PR_PRIOR.json` holds the
findings earlier reviews of this pull request published at older heads. Pass
the array exactly as it is; the report must account for every entry the
workflow returns in `priorFindings`.

Send one short message before it goes quiet: what is under review, the head, the
file and line counts, and that nothing is a finding until the verifiers have
finished.

## 4b. End your turn, and write nothing until you are woken

The Workflow tool **always returns immediately**:
`Workflow launched in background. Task ID: <id>`. The fleet then runs outside
your turn.

**End the turn right after the message above.** Call nothing else: no polling,
no `sleep`, no reading the fleet's transcripts. When the workflow finishes, a
new turn starts with a `<task-notification>` for that Task ID.

Do not write `review.md`, and do not summarise anything, before that
notification arrives.

The notification's `<status>` should be `completed`, and `<result>` carries the
workflow's return value. If `<result>` is missing, cut short, or not valid JSON,
Read the file named in `<output-file>`. If that fails too, Read the journal
named in `<diagnostics>`, which has one line per agent. Do not rebuild the
result from memory.

You get back `findings`, `refuted`, `unverified`, `coverage`, and a `next` line.
Follow `next`. `unverified` is the list of candidates no panel decided;
`coverage.candidatesUnverified` is only its count. When something has to be
named, use the list.

If the workflow genuinely fails rather than returning (the notification's
status is `failed` or `killed`, or neither `<result>` nor `<output-file>`
yields a result), say so and write nothing.

## 5. Write `review.md`

Read the REPORT SPEC now, not before, and use its `standard` column. Then read
the house style, `.claude/references/writing.md`. Then write `review.md` in the
repository root with `Write`. The `next` line in the workflow result maps each
returned field onto the template. Follow it.

**Publish the fix that came back.** Check it names a real file and function
and that it covers the defect; correct it and say so where reading the code
contradicts it. Do not replace it with a restatement of the defect.

Severity arrives already settled. Publish it as returned, and put every entry
in `coverage.severityChanged` on Coverage's **Corrections.** line with both
values.

So does `provenance` (`introduced`, `newly-reachable` or `pre-existing`):
publish it exactly as returned, in the finding's **Where it came from.** block
and, whenever any finding is not this change's, on the Result line. Put
`coverage.provenanceCorrected` (proposers the panel overruled) and
`coverage.provenanceDisputed` (confirming verifiers that split; the proposer's
label stands if any of them backs it, otherwise the weakest any would defend)
on **Corrections.** Where a merged entry carries `provenanceMixed`, give each
site its own answer instead of one label for all of them.

Coverage follows the REPORT SPEC: a table, then a labelled line only for each
thing that actually happened, never a field name from the returned object.
Where a value below is a gap in the review, its line goes in:

- the areas and the weakness classes read over each;
- every excluded file with its reason;
- **every path in `coverage.unaccounted`**, named, as neither read nor
  excluded;
- **any area whose reader failed.** `coverage.failedCells` is the count and the
  `failed: true` entries in `coverage.researchAccount` name them. If this is
  not zero it goes in the summary too;
- any proposal no panel decided, named under **Not covered** with its file and
  line, from the `unverified` list;
- **the observations one reader handed to another.** `coverage.deferred` holds
  every one, each with a `ruling`. `filed` became a proposal and needs no
  separate mention; for `did-not-hold`, say what it was and give the
  adjudicator's reason from `coverage.researchAccount` under the matching
  `deferred/<n>` tag. Quote every entry in `coverage.deferredUnclaimed` in
  **Not covered** with its file and line: nothing ever looked at it;
- any id in `coverage.anchorDoubted`: re-anchor it from the code or drop the
  finding, and say which you did in **Corrections.**;
- `coverage.mapperFallback` when the partition was unusable and the whole
  change was read as one area by one reader;
- `coverage.unitsAllowed` when it is below `coverage.unitCeiling`;
- the merge, when `coverage.mergeApplicable` is true: how many confirmed
  proposals were read as one defect, from `coverage.mergeGroups` and
  `coverage.mergeClusters`. A non-zero `coverage.mergeFailed` means a group
  came back unusable and its findings publish separately: say so in
  **Corrections.**

**Accounted for** carries the file total against `coverage.unaccounted`, only
when it does not come out even.

Write `findings` (including `merged` and `rescued` ones), `refuted`,
`refactorDrift` and `commentDiscrepancy` as the REPORT SPEC describes. Give the
**Refactors.** arithmetic only when `coverage.driftProposed` is non-zero. Where
a `refactorDrift` entry carries `lineCorrected` the checker moved the citation;
put that on **Corrections.** `commentDiscrepancy` gets no Coverage line.

End the file with the coverage stamp the REPORT SPEC describes, from
`coverage`, even when everything failed. `profile=standard` has to be the
profile you passed in step 4.

## 6. Say what happened

A few sentences: what was reviewed, how many candidates were proposed, how many
stood up, how many of those were published as one entry with another, and where
`review.md` is. Claim no more verification than `coverage` supports, and say
plainly that this was the standard tier, not the deep one.

If the report goes private (see "Some reviews must not be published in public"
in the REPORT SPEC), this message names `review.md` and the count of findings,
and nothing else: no titles, files, functions or bug classes.

If `coverage.unaccounted` is not empty, lead with that rather than the findings.
If `coverage.failedCells` is a large share of the cells dispatched, lead with
*that*: the run did not review what it set out to.

"No findings" is a complete and ordinary result. Say it plainly.

## Out of scope for this job

Nothing is commented upstream, no branch is pushed, no code from the PR is built
or executed. The deliverable is `review.md` on disk.
