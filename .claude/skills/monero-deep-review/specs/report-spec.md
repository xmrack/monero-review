<!-- Read at delivery, once the workflow has returned. The heading grammar is
     a contract with scripts/labels.py; the section names match the standard
     review's so a deep review reads like every other issue in the repo. -->

# `review.md`

**Read `.claude/references/writing.md` before you write a line of this file.**
It is the house style: Orwell's six rules, the Simplified Technical English
rules that apply, the words to cut, and the six-step pass to run over the
draft. This spec gives the structure; that file gives the prose. A deep review
buys more agents, not more words. A report that follows this spec in 3,000
words of hedged passive voice has failed.

# One reader, three questions

A Monero maintainer, mid-week, with a queue of pull requests. They open this
file to answer:

1. Is something wrong?
2. Where is it?
3. What do I change?

The order of everything below follows those three questions. Evidence comes
after the answer, never before it, because a reader who does not yet know what
you claim cannot weigh what you cite. They will check your citations. Write as
though they will.

# Sections

```markdown
# Security review of <PR title>

**Result:** <2 findings: 1 MEDIUM, 1 LOW> · <what it reaches, ≤10 words>, or
`**Result:** No findings · nothing in the diff reaches a trust boundary`
<When any finding is not this change's, say so on this line: `**Result:** 2 findings: 1 MEDIUM, 1 LOW · 1 introduced here, 1 pre-existing · a peer can stall block sync`. A maintainer deciding whether to merge needs that split before anything else.>
**Change:** <N> files, +<A>/-<B> · <subsystems touched>
**Head:** `<sha12>` · opened by <the `Opened by:` login from PR_CONTEXT.md>

## Summary

<At most 3 sentences and at most 75 words. No sentence over 25 words. What the change does, in your own words, and the one thing a maintainer needs before deciding whether to read on. ONE LINE: do not wrap it, see `writing.md`.>

## Findings

<With two or more findings, this table first. With one, skip it: the finding is already its own summary.>

| id | sev | what is wrong | where | the fix |
| --- | --- | --- | --- | --- |
| F1 | MEDIUM | <≤10 words> | `file.cpp:123` | <≤10 words> |

### [SEVERITY] Short title

`path/to/file.cpp:123` · `function_name` · <n>/3 angles agreed<, followed by ` · not introduced by this pull request` when the finding's `provenance` is `pre-existing`>
<For a finding carrying `merged`: one such line per site in `merged.sites`, each with that site's own vote, then a final line reading `Same defect because: <merged.sameDefectBecause>`. These breaks ARE deliberate: one site per line.>

**Panel split.** <Only for a finding carrying `rescued`. At most 3 sentences: that the panel rejected it two to one and an advocate restored it, what the two rejections relied on, and the line the advocate showed they were wrong about. When `rescuedMemberId` is set, say which site of the merged finding that was. Omit the line entirely on an ordinary finding. One line.>

**Defect.** <At most 5 sentences and at most 120 words: the untrusted input, what it reaches, why nothing stops it, and every frame the input crosses on the way. A citation for each. One line.>

**Impact.** <At most 2 sentences. What someone gets, and the clause that makes it worse, or narrower, than it sounds.>
**Needs:** <what has to hold: a non-default flag, an attacker position, a victim action. Write "nothing" when that is true; it is the strongest thing this line can say. One line. The break above this label is deliberate, and it is the only one in the block.>

**Fix.** <At most 4 sentences and at most 100 words. The file and the function to change, and the change. At the cause, not at one caller. One line.>

**Where it came from.** <At most 2 sentences. One of: introduced by this change, and the `+` line or the deleted guard; newly reachable, and what now reaches it; an incomplete guard, and the check it gets past; or pre-existing, and what `origin/base` reads. Take the word from the finding's `provenance`, which the panel settled. One line.>

## Refuted

- ~~<proposal>~~: <what took it apart, and the line that settled it.>

## Needs human review

<Only when the run returned `refactorDrift`. Omit the heading entirely when it is empty.>

- `path/to/file.cpp:123` · <What the head does that `origin/base` does not. One sentence, and it comes first.> **Told apart by.** <The input, state, call order, configuration or error path under which the two observably differ, from the entry's `distinguishingInput`, concrete enough that the reader could construct it.> **Presented as.** <what made the hunk look like a refactor, quoted: the title, the sentence in the description, the commit subject, or that the hunk is a move with no new caller>. <At most three more sentences of evidence, each carrying the line it rests on.> <Which behaviour was intended is a question for a human.>

## Not covered

- <What could not be settled, and why: a tool this run lacked, a claim needing a running binary, a submodule whose source was absent, an observation nobody adjudicated, a third party's report this run reached no verdict on. One line per bullet.>

## Checked and clear

- <What was examined, the check that was made, and the citation. One line each.>

## Coverage

| area | files | read for |
| --- | --- | --- |
| <plain name> | <paths, or a count> | <weakness classes> |

**Accounted for.** <N> of <N> changed files: <N> read, <N> excluded (<reason per exclusion, one clause each>).
**Not accounted for.** <each path nobody placed, named, or "none">
**Not read.** <any area a reader failed on, named, or "none">
**This tier.** deep: one reader per area per weakness class, a pass across the areas, a second look at every area, three verifiers per finding.
**Across areas.** <what the pass looking only at what crosses between areas found, including "nothing"; or that it did not run, and why>
**Second look.** <what the second pass over each area found that the first missed, including "nothing">
**Proposals.** <n> proposed, <n> stood up, <n> refuted, <n> undecided<, <n> folded into another entry>, <n> one vote short and re-looked, <n> restored by an advocate.
**Handed on.** <each observation one reader passed to another, and how it was settled, or "none">
**Refactors.** <what was read for a behaviour change inside a restructuring, and the arithmetic: <n> raised, <n> published in `## Needs human review`, the rest dropped by the reader that compared both versions -- or "nothing in this change presents itself as a refactor", or "no hunk restructures existing code">
**Corrections.** <a severity lowered, an anchor re-checked, a provenance the panel corrected or the verifiers split on, two entries that may be one defect, or omit the line>

<!-- deep-scan profile=deep units=<n> cells=<n> failedCells=<n> angles=3 candidates=<n> confirmed=<n> published=<n> merged=<n> refuted=<n> unverified=<n> unaccounted=<n> deferred=<n> -->
```

# The header is three lines

**Result first**, because it is the only line some readers finish. It carries
the count and, after a `·`, what the change reaches: the boundary in a clause,
not a paragraph. "none reachable" is a complete and valuable answer.

`Change` and `Head` are facts, not prose. Do not let either grow a clause.

# The summary: 3 sentences, 75 words, nothing over 25

The sentence cap alone does not work. Told only "two or three sentences", a
writer packs 53 words into one and calls it brief. That has happened here, and
the result was three facts in a blur. So both limits hold at once, and the
25-word ceiling is what actually forces the prose apart.

Say what the change does, in your own words. The title is the author's framing;
this is your reading of the diff. Where the two differ, that difference is
usually the most interesting sentence in the report. Then say what it means for
a maintainer: the one finding that matters, or the fact that none does.

What it must not be:

- **a restatement of `Result:`.** That line gives the counts, two lines above.
- **a description of the review.** No "I examined", no "this review covered",
  no method, no effort. Coverage says what was read.
- **hedged into meaninglessness.** "Some areas may warrant further review" is
  not a summary; it is a way of not writing one.

Two things go in the summary whatever else does: a changed file nobody
accounted for, and an area nobody read. Both matter more than a LOW, because
they are the part a "No findings" would otherwise overstate.

On a no-findings review this section does the most work in the file. "Adds a
bounds check to the RPC handler and its test. Nothing in the diff reaches a
trust boundary and no guard was removed." tells a maintainer they can stop
reading, and is worth more than three paragraphs of Checked-and-clear.

# The finding: a locator and four blocks

Seven labelled blocks per finding was the old shape, and the fix sat sixth,
below the two longest. A maintainer reads a finding to learn what is broken and
what to change, so those are now first and third of four.

**The locator line** is what a reader copies into an editor:
`` `file:line` · `symbol` · <n>/3 angles agreed ``. It replaces a **Where.**
block and a **Verification.** paragraph. The vote is a count and nothing else:
never "thoroughly verified" or "confirmed by an independent panel". The value
of this shape over one reviewer is that the number came out of a program;
adjectives are how it stops being worth more.

**A `pre-existing` finding says so on its locator line**, in those exact words:
`` · not introduced by this pull request ``, appended after the vote. Two
reasons it is fixed text rather than yours to phrase. A reader scanning a list
of findings decides whether this blocks the merge from the locator line alone,
and should not have to reach **Where it came from.** at the bottom of the block
to learn that the author did not cause it. And `labels.py` reads that exact
phrase to put a `pre-existing` label on the published issue, so a paraphrase
silently drops the label.

Only `pre-existing` gets it. A finding this change introduced, made newly
reachable, or let past a guard it added is this change's business, and marking
those as not-introduced would be false. Their **Where it came from.** block
carries the distinction in full.

**Defect.** Five sentences at most, and at most 120 words. The untrusted
input, what it reaches, why nothing stops it, each with a line you read. Spend
the room on the route rather than on adjectives: an input that crosses three
frames before it does damage needs those frames named, and a chain compressed
into one clause is a chain the reader cannot check. This is question 1 and it
is answered in plain words before any evidence: not "an analysis of the call
graph indicates" but "a peer's crafted response reads past the end of the
buffer".

**Impact.** Two sentences at most, then `Needs:`. What someone gets,
concretely: funds, a crash, a key, a chain split, a deanonymised user. The
second sentence is for the clause one sentence has to drop, which is usually
why the consequence is worse, or narrower, than the first sentence makes it
sound. `Needs:` carries the preconditions, and it is the line that decides
whether a MEDIUM is this afternoon's problem or next month's. State the
condition plainly: a flag by its real spelling, an attacker position, a victim
action.

**Fix.** Four sentences at most and at most 100 words, and it must survive
being read alone. Name the file, name the function, say what changes.
"Validate the length" is not a fix; "reject the packet in
`handle_notify_new_transactions` before the resize at `:412`, since every
other field is already checked there" is. Fix the cause: if two callers are
wrong because a helper is permissive, the helper is the fix. Where the honest
answer is that the right fix is a design question, say that in one clause and
give the local change that stops the bleeding.

**Where it came from.** Two sentences at most, opening with the finding's
`provenance` word, which the panel settled and which you publish as returned:

- *introduced by this change*: the `+` line that created it, or the `-` line
  that removed the guard, and what `origin/base` reads;
- *newly reachable*: the code is older and untouched, and this is what now
  reaches it;
- *an incomplete guard*: the check this change adds, and how the finding gets
  past it;
- *pre-existing*: what `origin/base` reads, unchanged.

The last two are published as findings like any other, because a real
vulnerability in code this change touches is worth a maintainer's time whoever
wrote it. What they are not is an accusation. Never write a pre-existing
finding as though the author caused it: the reader is deciding between "do not
merge this" and "file this against master", and that sentence is what tells
them which.

It comes last in the block because it is the audit trail: a reader who accepts
the finding never needs it, and a reader who doubts it needs nothing else.

**Panel split** is the one extra line this tier can carry, and only where the
workflow returned `rescued`. A finding the panel rejected two to one and an
advocate restored is one a maintainer must be told about, in plain words, above
the claim rather than in a footnote below it. The `<n>/3` on the locator line
says a minority agreed but not that anybody went back. Three sentences.

**Nothing else gets a block.** No **Notes.**, no **Discussion.** An exception
the reader must know about (a severity the panel brought down, an anchor you
re-checked, a duplicate that could not be merged) goes in Coverage's
**Corrections.** line, once, not appended to each finding.

## Order and length

Order findings by severity, then by how many angles agreed. People stop reading
partway down.

A finding is about eighteen lines. One that needs more is usually two
findings, or one that has not finished being reduced.

Every cap above is a ceiling, not a target. A finding that says everything in
six lines is finished at six; the room is there for a route with more than one
hop in it, not to be filled.

# Severity, and no confidence word

**Severity comes back already decided.** The workflow lowered any severity its
agreeing verifiers rated below the proposal, and caps a confidence by how many
agreed. Publish what it returned. `coverage.severityLowered` lists every one
that moved, with both values. Note it in **Corrections.**

The heading is `### [SEVERITY] Title` and nothing else. A confidence beside the
severity puts two graded words in one bracket, they read as one scale, and
`[MEDIUM / medium]` blurs the only thing severity is for. What confidence stood
in for is published instead as `<n>/3 angles agreed` on the locator line, plus
**Panel split** where a rescue happened.

# Check each anchor before you write it

Read the cited line and confirm it still says what the proposal quoted. Nothing
upstream does this for you, and a wrong citation costs more than silence: the
reader loses confidence in everything around it while chasing it.

Any id in `coverage.anchorDoubted` is a finding the verifiers could not find at
its cited line. Re-anchor it from the code or drop the finding, and say which
you did in **Corrections.**

# Nothing was executed

No build, no test, no proof of concept, anywhere in this pipeline. Never phrase
a finding so that it implies otherwise.

# Merged findings

Several confirmed proposals can be one defect: the same missing check at two
call sites, or one unvalidated field filed once as an overflow and once as a
resource exhaustion. A merge stage settles that after the panel and before you,
and a grouped finding arrives carrying a `merged` object.

Write it as **one** `### [SEVERITY]` entry:

- one locator line per site in `merged.sites`, each with that site's vote;
- a final locator line reading
  `Same defect because: <merged.sameDefectBecause>`, naming a shared cause and
  not a shared file;
- one **Fix.**, which is the point of the merge: one change at one place.

Do not split it back into one entry per site. A maintainer should see one bug
once, and `published` in the stamp would then be wrong. Do not drop a site
either: each is a place the defect is reachable and a place the fix has to
hold.

When a nominated group came back unusable its findings are published
separately. Say so in **Corrections.**, because that is a possible duplicate in
the report and the reader should be told why two entries look alike.

# Needs human review

A hunk that presents itself as behaviour-preserving and is not. The claim can
be the pull request's title, a sentence in its description, a commit subject,
or nothing said at all where the code is plainly a move of something that
already existed.

**This is not a finding and it is not a refutation.** It faced no panel, it
carries no severity and no vote, and it never gets a `### [SEVERITY]` heading:
that would label the published issue as though a panel had confirmed a security
defect, which nobody did. It is an observation for a human to check, and the
entry says so.

## Everything under this heading was checked

The run does not publish what a researcher raised. Every observation went to a
reader that did not propose it, with both versions of the file in front of it
and one question: name the input under which they observably differ. Three
answers drop an entry before the report is written, and what the section is
worth to a maintainer is that all three already happened:

- nothing tells the two versions apart, so the restructuring was faithful;
- the checker could not name what does, which is the same answer held less
  firmly;
- the hunk was never presented as behaviour-preserving, so the difference is
  the pull request doing what its description says.

Write the entries as checked, because they were. The **Told apart by.** clause
is the load-bearing half and belongs in every bullet: it is what lets a
maintainer decide in one line whether this is worth opening the file for, and
it is the difference between this section and a list of hunches.

Where a checker returned nothing usable its entries are NOT here. Nobody read
them, and "nobody checked" must never arrive looking like "checked and clear".
They are in `coverage.driftUnchecked`, and they go under **Not covered** with
their file and line.

## What never goes in an entry

- a severity, a confidence, or a guess at whether anybody can reach it. That
  question belongs to the candidate path, and where the drift IS attacker
  reachable it is a finding as well, published normally above. The bullet here
  is not a substitute for it;
- a fix. Which behaviour was intended is the maintainer's to say, and a fix
  written before that is settled is a guess at what somebody meant;
- a difference in a comment, a log message's wording, a symbol name, or
  formatting;
- a difference only a different compiler, ABI or optimisation setting could
  show;
- a restatement of the diff. "The loop moved into a helper" is what the reader
  can already see. What the helper does differently is the entry.

Keep the bullet to what a maintainer needs in order to decide: the difference,
the input that shows it, and the claim it contradicts. Five sentences is
plenty, and most of these take three.

Omit the heading when nothing survived the check. The Coverage **Refactors.**
line carries the arithmetic either way, so an absent section reads as "nothing
drifted" rather than "nobody looked".

Why it gets its own section rather than a place among the findings: most of
these have no untrusted input behind them, so the four-part candidate test
throws them out and is right to. That test is asking whether an attacker can do
something. This section is asking a different question, which is whether the
change does what it says. A maintainer wants the answer to both, and only one
of them is a severity.

# Refuted stays in

It is most of what a deep review produces, and it is how the next reviewer
avoids spending a panel on the same idea twice. Dropping it to look decisive
throws away the expensive part.

One line each: the proposal, what killed it, the `file:line`. Not the story of
how it was considered. Two proposals killed by the same line may share one
bullet naming both sites, but only when the refutation is genuinely the same
one, and never by dropping a site. Nothing merges the refuted list upstream,
so that is yours to do.

Emit the heading even when nothing was refuted (`- none`). `labels.py` stops
reading there, and a report without it has no stopping point.

# Coverage is a table and ten lines

It used to be an essay, and most of it was the same essay every time. The
structure above is the whole of it: a table of areas, then those labelled
lines, each one line long. Never a paragraph.

- **Not accounted for** is always present, `none` included. It is the one fact
  a thin review has an incentive to omit, so it gets its own line rather than a
  clause inside another.
- **Not read** names any area whose reader failed.
- **This tier** is the fixed sentence in the template. Do not rewrite it per
  report.
- **Across areas** and **Second look** are worth stating even at zero. A zero
  from the pass that read only what crosses between areas is evidence about the
  change; that pass not running at all is a limit on the review. It does not
  run on a single-area change, and that is the reason to give.
- **Proposals** is counts only. Anything a reader said it could not finish
  reading is reported as that reader's own account, not as established fact.
- **Handed on** covers every observation one reader passed to another rather
  than filing. One that did not hold is reported with the reason. One nobody
  could settle goes in **Not covered** with its file and line.
- **Corrections** is omitted when there is nothing to correct.

Give the file arithmetic so it can be checked: every area's file list either
names every path or gives a count and names none, and **Accounted for** states
the total against the changed-file list.

**No workflow field names in this section.** `seamPassApplicable`,
`coverage.unaccounted`, `mergeApplicable`, `reLookApplicable`, "cells",
"lenses", "the mapper": none of these mean anything to a maintainer. Read the
value and write the fact: "every changed file is accounted for", "no pass
looked across areas", "nothing was nominated as a duplicate". The stamp is
where field names belong, and it is invisible when rendered.

# "No findings" is a finished report

It is also the common outcome on this queue. What makes it worth reading is
**Not covered** and **Checked and clear** having real content. Do not pad, and
do not soften something real to be kind about the code.

# Nominate the durable refutations

Where a refutation settles something about this codebase rather than about this
diff (what epee's serializer really bounds, what a zero scalar does, which zone
a limit applies to), say so, and name it as worth adding to
`.claude/skills/monero-security-review/references/refutations.md`. That file is
why the next review does not re-propose it, and this pipeline is the cheapest
place to grow it. Do not edit it from here: propose, and let a human land it.

# The coverage stamp is not decoration

The last line is an HTML comment, invisible when rendered, and the harness
reads it. Emit it **always**, as the final line, with every field present and
every value a plain integer taken verbatim from the returned `coverage` object,
never a number you reasoned your way to.

| field | from |
| --- | --- |
| `profile` | the literal `deep`. Checked against the mode the harness dispatched: the same stamp shape carries `profile=standard` for the cheaper tier, and a report claiming the wrong one is treated as not having happened |
| `units` | `coverage.units.length` |
| `cells` | `coverage.cells` |
| `failedCells` | `coverage.failedCells` |
| `angles` | the literal `3`. The standard profile runs two, and the harness reads this rather than assuming |
| `candidates` | `coverage.candidatesDistinct` |
| `confirmed` | `coverage.confirmed`: proposals whose panel said holds. **Not** the returned `findings` array's length: those two were the same number until the merge stage separated them |
| `published` | `coverage.published`: the number of `###` entries you write under `## Findings`, which is the `findings` array's length |
| `merged` | `coverage.merged`: confirmed proposals folded into another entry |
| `refuted` | the returned `refuted` array's length |
| `unverified` | `coverage.candidatesUnverified` |
| `unaccounted` | `coverage.unaccounted.length` |
| `deferred` | `coverage.deferredUnclaimed.length`: the ones nobody settled, **not** `coverage.deferred.length`. The harness publishes this number as "observation(s) ... never settled by anyone" |

`cells` is `coverage.cells` and **not** `coverage.researchAccount.length`.
`researchAccount` is an exception log, not a roster: a pass is recorded there
only when it failed outright or came back `notFinished`, and its entries span
readers, the pass across areas, the second look and the adjudicators alike,
distinguished by `kind`. On a clean run it is **empty**. `coverage.cells` is
the number of readers dispatched and `coverage.failedCells` counts only the
`kind: "cell"` failures among them, so those two are the pair that can honestly
be divided into each other, which is what the harness does.

`confirmed + refuted + unverified` must equal `candidates`, and
`published + merged` must equal `confirmed`. Neither is a rule imposed on you:
every proposal ends in exactly one of those three buckets, and every confirmed
one either gets an entry of its own or is folded into somebody else's, so both
hold by construction in any real result. The harness checks it, and a stamp
that fails it is treated as fabricated and the report is not published. If your
numbers do not add up, you took them from the wrong place; go back to
`coverage` rather than adjusting one to fit.

It exists because of one failure mode the prose cannot cover, and the fleet has
**two halves that die separately**. If the readers die, nothing was read. If
the readers work and the verifier panels die, every proposal comes back
`unverified` and `findings` is empty, and an honest report of either is a
report with no findings in it. To `labels.py` and to the harness that is
byte-for-byte a clean review, and publishing it files the issue that marks this
pull request reviewed forever. The stamp is the only thing that separates
"three verifiers looked and found nothing" from "nobody looked".

So the harness refuses to publish on these numbers when most readers failed,
when most proposals got no verdict, or when the arithmetic does not hold.
Reporting them accurately matters more than the report reading well.

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
publishing, so a slip is caught, but it is caught by a regex over
model-written prose, which is the weakest kind of guarantee. Do not rely on it.

# Do not write a Verification footer

The harness appends one, from what actually happened. A claim of your own about
whether an adversarial pass ran will contradict the record and has done.

# The grammar is load-bearing

`scripts/labels.py` labels the published issue from this file. It reads finding
headings as `### [SEVERITY ...]` and stops counting at the first `## Refuted`.
So:

- headings stay `### [SEVERITY] Title`, severity spelled `CRITICAL`, `HIGH`,
  `MEDIUM` or `LOW`;
- `## Refuted` keeps that exact spelling and stays **directly below**
  `## Findings`. Above it, every real finding stops labelling the issue;
- a refuted entry never gets a `###` heading of its own;
- **a bracketed-severity `###` heading appears only under `## Findings`.**
  Everything above the first `## Refuted` is read as a finding, so such a
  heading anywhere else there labels the issue as though a panel had confirmed
  it. The triage table is safe, because it has no `###` heading, and so is a
  bracketed severity in a table cell or a bullet;
- `## Summary` sits above `## Findings` and holds prose only;
- `## Needs human review`, `## Not covered`, `## Checked and clear` and
  `## Coverage` sit below `## Refuted`, where `labels.py` has already stopped
  reading. That is why they can be reordered and the three sections above them
  cannot. It is also why `## Needs human review` is safe where it is and would
  not be one line higher: its entries are observations nobody graded for severity, and above
  `## Refuted` a bracketed severity in one would label the issue.

Measured against `labels.py`, not assumed: a report written from this template
with one MEDIUM and one LOW finding yields `medium, low`; a bracketed severity
in a triage-table cell or a refuted bullet is correctly ignored; and moving
`## Refuted` above `## Findings` yields nothing at all.
