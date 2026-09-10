# Reviewing one pull request

Resolve what is under review, start the run, write `review.md`.

## 1. Fix the range

The harness fetched the PR head and pointed `origin/base` at the branch it
targets. Confirm that instead of assuming it, one command per call:

- `git rev-parse --verify --quiet origin/base`: empty means this checkout was
  not prepared by the harness. Stop and say so. Without `origin/base` there is
  no honest range, and falling back to `master` would hand you an entire
  branch's divergence on any backport.
- `git rev-parse --short=12 HEAD`: the head under review. Quote it.

The range is `origin/base...HEAD`, three dots, never inside `$(...)`.

`PR_CONTEXT.md` opens with a `Pull request: <upstream>#<n>` line written by the
harness, outside the author-supplied fence, and then the author's own title.
Take the number and title from there and treat the rest as the author's claims.
If that line is absent (an older harness, or a checkout prepared by hand),
pass `pr: null` rather than guessing; the workflow handles it.

## 2. List the changed files

`PR_FILES.md` already holds them, one path per line (lines starting `#` are
not paths), written by the harness from `git diff --name-only
origin/base...HEAD` before you started. Read it rather than re-deriving it, and
if it is absent run that command yourself and say in the report that the
harness did not provide the list.

Hand this list to the workflow exactly as git printed it. Do not filter it,
reorder it by what looks important, or trim it to something manageable. The
workflow's coverage check compares the mapper's answer against precisely this
list, so anything you drop here becomes a file that was never reviewed and
never reported as unreviewed, which is the one failure this job is built to
prevent.

An empty list means there is nothing to review: say so and stop.

For the report's `Change:` line: `git diff --shortstat origin/base...HEAD`

## 3. Confirm you can actually run it

Check that `Workflow` is among the tools available to you right now, with its
parameters. This skill's frontmatter asking for it proves nothing: the
scheduled pipeline runs with a narrow allowlist carrying neither `Workflow` nor
`Agent`, and this skill is written for a session where both are granted.

If it is missing, stop with one line: that the deep review needs the Workflow
tool, this session does not have it, so nothing ran, and
`/monero-security-review`, the single-reviewer fallback, is what to use here. Do not improvise around it. Dispatching the agents
yourself would yield a report claiming a verification nobody performed, which
is the one thing this skill must never produce.

**Say it in chat and write nothing to `review.md`.** That file is the
harness's input, not a place to leave a note. A file explaining why nothing
ran carries no severity heading, so `labels.py` reads it as a review that
found nothing, the harness files the issue that marks this pull request
reviewed, and it is never looked at again, so a harness misconfiguration turns
into a permanent clean bill of health. An absent file is read correctly: the
run failed and the pull request stays in the queue.

In the CI harness the tool is granted (`.github/workflows/review.yml` appends
`Workflow` and the five `Agent(...)` grants when it is dispatched with
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

Prefer passing `args` as a real object rather than a JSON-encoded string. Both
work, and that is measured: the first two CI deep runs both serialised it to a
string, and the one that got as far as running the fleet partitioned all 50
changed files correctly, so the harness parses it. An object is simply the documented shape
and one less thing between you and the script.

Send one short message before it goes quiet: what is under review, the head, the
file and line counts, that this is the deep pass, and that nothing is a finding
until the verifiers have finished.

## 4b. Wait for it: this is not optional

The Workflow tool **always returns immediately**. Its result says
`Workflow launched in background. Task ID: <id>` and the fleet then runs
outside your turn. If you end your turn there, the run ends with it: measured
on the first CI deep run, the Lead said "I'll wait for it to finish", stopped,
and the session exited `success` after 52 seconds having killed every agent it
had just dispatched. Nothing was refused and nothing errored. It simply walked
away from three hours of work it had already paid to start.

So take the `Task ID` from that result and block on it:

```
TaskOutput({ task_id: "<the Task ID>", block: true, timeout: 600000 })
```

600000ms is the maximum per call, so one call is not enough. If it comes back
`not_ready` or still running, **call it again**, and keep calling until it
returns the workflow's result. A wide diff is a few hours, which is a couple
of dozen calls; that is expected and it is far cheaper than the alternative.
Do not end your turn, do not start writing `review.md`, and do not summarise
anything until that result is in your hands.

Per-stage progress shows under `/workflows` when a human is watching; do not
narrate it yourself.

You get back `findings`, `refuted`, `unverified`, `coverage`, and a `next` line.
Follow `next`. Note that `unverified` is a list of candidates no panel decided,
while `coverage.candidatesUnverified` is only its count (plus any whose panel
threw, which are a count with no record). When something has to be named, use
the list.

If the workflow genuinely fails rather than returning (the task dies, or
`TaskOutput` reports an error rather than a result), say so and write nothing.
A report with no pipeline behind it is the one thing this skill must never
produce.

## 5. Write `review.md`

Read the REPORT SPEC now, not before. Then read the house style,
`.claude/references/writing.md`: Orwell's six rules, the Simplified Technical
English rules that apply, the words to cut, and the six-step pass to run over
the draft. Then write `review.md` in the repository root with `Write`.

The reader is a Monero maintainer with a queue and an afternoon, answering
three questions: is something wrong, where is it, what do I change. The
structure follows those three, and the `next` line in the workflow result maps
each returned field onto the template. Follow it. A deep review buys more
agents, not more words.

**Publish the fix that came back.** Each finding carries a `fix` written by the
researcher that read the guards and the callers. Check it names a real file and
function and that it covers the defect; correct it and say so where reading the
code contradicts it. Do not replace it with a restatement of the defect:
"validate the length" is what this field exists to stop. On a merged finding
there is one **Fix.** for the whole entry, because one change at one place
fixing them all is what the merge decided.

Severity arrives already settled: the workflow lowered any severity its
agreeing verifiers rated below the proposal. Publish it as returned, and put
every entry in `coverage.severityLowered` on Coverage's **Corrections.** line
with both values.

So does `provenance`, and it is the other thing you publish exactly as
returned: `introduced`, `newly-reachable` or `pre-existing`, settled by the
panel against `origin/base` rather than by the agent that proposed it. It says
where the vulnerable code sits relative to this change, not how old the code
is: a line the change adds is the change's own, and only `pre-existing` means
the code is outside what the pull request touched. It goes in the finding's **Where it came from.** block
and, whenever any finding is not this change's, on the Result line too, because
a maintainer is deciding between "do not merge this" and "file this against
master" and that split is the first thing they need.

A `pre-existing` finding is a finding. The run traced a real weakness in code
this change touches, and it is published like any other. What it is not is an
accusation: never write it as though the author caused it, and end its locator
line with ` · not introduced by this pull request`, in those exact words. That
phrase is what a reader scanning the findings sees before reaching **Where it
came from.**, and `labels.py` matches it literally to put a `pre-existing`
label on the issue, so a paraphrase drops the label silently. Only
`pre-existing` gets it: a finding this change introduced, made newly reachable,
or let past a guard it added is this change's business. Put
`coverage.provenanceCorrected` (proposers the panel overruled) and
`coverage.provenanceDisputed` (verifiers that split, each settled at the
weakest label any of them would defend)
on **Corrections.**, and where a merged entry carries `provenanceMixed`, give
each site its own answer instead of one label for all of them.

**Do not publish a confidence.** The heading is `### [SEVERITY] Title`. The
workflow returns a confidence and uses it internally, but two graded words in
one bracket read as one scale and blur how bad a finding is. The locator line
carries `<n>/3 angles agreed` instead, which is the same information as a
number.

Before you write a finding down, read its cited line and check it still says
what the proposal quoted. Nothing upstream does that for you, and a wrong
citation is the fastest way to lose the reader.

A finding carrying `rescued` gets a **Panel split.** line above **Defect.**:
the real split from its vote record, what the two rejections relied on, and the
line the advocate showed they were wrong about. When `rescuedMemberId` is set,
name which site of the merged finding that was. Say it plainly, because this is a
finding a majority of the panel rejected, and the reader is entitled to know
that before the claim rather than after it.

Coverage is a table, then one labelled line for each thing below that
actually happened -- never a paragraph, and never a field name from the
returned object in front of the reader. **A line whose answer is "none",
"nothing" or arithmetic that comes out even is omitted entirely**, so on a
clean review Coverage is the table alone. That is the point: a block of `none`s
teaches a maintainer to scroll past the run where one of them is not `none`.
Omitting a line is never omitting a fact, so where a value below is a gap in
the review, its line is how the gap gets said, and it goes in:

- the areas and the weakness classes read over each;
- every excluded file with its reason;
- **every path in `coverage.unaccounted`**, named, as neither read nor
  excluded;
- **what the pass across the areas did, when it did not do it.**
  `coverage.seamPassApplicable` false on a single-area change, and
  `coverage.seamFailed` true meaning it was applicable and nobody looked, are
  both limits on the review and both get the line, with the reason. A pass that
  ran and found nothing (`coverage.seamRan` true, `coverage.seamFresh` zero)
  needs no line: the stamp records that it ran. Never write a pass that did not
  run up as a clean cross-area result;
- what the second look over each area found (`coverage.gapFresh`) when it found
  something, and any area it failed to cover (`coverage.gapFailed`);
- any id in `coverage.anchorDoubted`: a finding two verifiers could not find
  at its cited line. Re-anchor it from the code or drop the finding, and say
  which you did in **Corrections.**;
- `coverage.marginalReLooked` and `coverage.rescuedOnReLook`: how many
  proposals fell one vote short, and which the advocate saved;
- **any area whose reader failed.** `coverage.failedCells` is the count and the
  `failed: true` entries in `coverage.researchAccount` name them. If this is
  not zero it goes in the summary too;
- any proposal no panel decided, named under **Not covered** with its file and
  line: the `unverified` list holds them and `coverage.candidatesUnverified`
  counts them. There is no longer a counts line to hide one in, and a digit was
  never enough for a reader to do anything with;
- **the observations one reader handed to another, all of them.**
  `coverage.deferred` holds every one, each with its own adjudicator and a
  `ruling`. `filed` became a proposal and is already accounted for among the
  findings or the refutations. `did-not-hold` means somebody read the code and
  it did not survive, so say what it was and give the adjudicator's reason, which
  is in `coverage.researchAccount` under the matching `deferred/<n>` tag. Do
  not drop a `did-not-hold` silently: an observation somebody wrote down and
  somebody else disposed of is exactly what the next reviewer will otherwise
  propose again;
- **every entry in `coverage.deferredUnclaimed`**, quoted with its file and
  line, in **Not covered**. Their adjudicator came back unusable, so nothing
  ever looked at them. They were not refuted; they were missed. On the first CI
  deep run, before that stage existed, exactly this happened to both
  observations the run produced: one named a file, a line, a mechanism and an
  impact, reached no panel, and appeared nowhere in the report;
- `coverage.mapperFallback` when the partition was unusable and the whole
  change was read as one area: complete, but blunter;
- `coverage.unitsAllowed` when it is below `coverage.unitCeiling`, since the
  cap scales with the size of the change;
- the merge, from `coverage.mergeGroups` and `coverage.mergeClusters`. A
  non-zero `coverage.mergeFailed` means a group came back unusable and its
  findings publish separately, so say so in **Corrections.**, because that is a
  possible duplicate in the report rather than a hidden one.

When Coverage names what a reader could not finish and promises the reader
what is in it ("three things it could not read to the bottom"), reproduce
those items. Do not point at an account and then print a different, more
general list; that sentence is a promise a reader will try to cash.

Give the file arithmetic so it can be checked: every area's file list either
names every path or gives a count and names none. "4 x CMakeLists.txt" when
there are five makes the table sum to 49 of 50, and a reader adding it up
cannot tell a prose slip from a coverage hole. **Accounted for** carries the
total against `coverage.unaccounted`, and is written only when that arithmetic
does not come out even -- a file excluded, or a changed file the table does not
cover. Every file read and none excluded, no line: the table is the account.

A finding carrying `merged` is several confirmed proposals a merge agent read
as **one defect**. Write it as one `### [SEVERITY]` entry: a locator line per
site in `merged.sites` with that site's vote, a final line giving
`merged.sameDefectBecause`, and one **Fix.** Never split it back into one entry
per site and never drop a site: the first makes the stamp's `published` wrong,
the second loses a place the fix has to hold.

`refactorDrift` is not a finding and not a refutation. Each entry is a hunk
that presents itself as behaviour-preserving and does not behave that way: no
panel graded it, it has no severity and no vote, and it must never get a
`### [SEVERITY]` heading. Write the entries under `## Needs human review`,
below `## Refuted`, one bullet each leading with what the head does that
`origin/base` does not, then the entry's `distinguishingInput` as a **Told
apart by.** clause, then the quoted claim that made the hunk look like a
refactor. Leave which behaviour was intended to the reader, and give no
severity, no fix and no guess at reachability. Omit the heading when the array
is empty.

What arrives in that array has already been checked: every observation a
researcher raised went to a reader that did not propose it, and the ones
nothing could tell apart were dropped before you saw them. Two things follow.
Publish `distinguishingInput` in every bullet, because a maintainer decides
whether to open the file on that clause alone and it is what separates this
section from a list of hunches. Stamp `drift=coverage.driftProposed` and
`driftPublished=coverage.driftPublished` always, and give the same arithmetic on
the Coverage **Refactors.** line only when `coverage.driftProposed` is non-zero:
raised, published, the rest dropped by the check. Nothing raised, no line -- the
stamp already separates "nothing drifted" from "nobody looked". Where an entry
carries `lineCorrected` the checker moved the citation, which goes on
**Corrections.**

`coverage.driftUnchecked` is the other half of the honesty. Those are entries
whose checker returned nothing usable, so nobody read them. They are not in the
section and they must not be silently absent: name each one under **Not
covered** with its file and line. An absent section reads as "nothing drifted",
which is only true if that list is empty.

Keep `refuted` in the report, one line each. It is most of what this pipeline
produces and it is how the next reviewer avoids buying a panel for the same
idea twice. Nothing merges that list upstream, so two proposals killed by the
same line may share one bullet naming both sites, but only when the refutation
is genuinely the same one, and never by dropping a site.

End the file with the coverage stamp the REPORT SPEC describes: the HTML
comment carrying `cells`, `failedCells`, `drift`, `driftPublished` and the
rest, straight from `coverage`.
The harness reads it and refuses to publish a run whose research mostly failed,
or whose panels mostly returned no verdict, because such a run and a genuinely
clean one are otherwise indistinguishable from the outside. Write it even when
everything failed; that is the case it exists for.


## 6. Say what happened

A few sentences: what was reviewed, how many candidates were proposed, how many
stood up, how many of those were published as one entry with another, and where
`review.md` is. Claim no more verification than `coverage` supports.

If `coverage.unaccounted` is not empty, lead with that rather than the findings.
If `coverage.failedCells` is a large share of the cells dispatched, lead with
*that*: the run did not review what it set out to, and no number of clean units
makes up for the ones nobody read.

"No findings" is a complete and ordinary result. Say it plainly.

## Out of scope for this job

Nothing is commented upstream, no branch is pushed, no code from the PR is built
or executed. The deliverable is `review.md` on disk. What becomes of it is the
harness's business.
