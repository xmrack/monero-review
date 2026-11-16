# Design notes

Why the review prompts are shaped as they are. No agent reads this file; the
rules themselves live in `.claude/specs/`, `.claude/skills/` and
`.claude/references/writing.md`.

## Tiers

- The standard tier replaced a single reviewer holding the whole change in one
  context. That shape degrades as a diff widens: every tool result stays in the
  window, so the files read last are read worst, and nothing checked they were
  read at all. It is not kept as a fallback because its report was
  indistinguishable from the fleet's; a session without `Workflow` stops
  instead of publishing a weaker review that reads the same.
- Standard drops the seam pass and the per-unit second look. On the one
  measured deep run those two were 28.1% of the fleet's cost and produced one
  candidate, which the panel refuted unanimously. Standard runs on every
  upstream pull request, twice an hour.
- The 1-1 advocate exists because a tie used to be filed as refuted on one
  verifier's word, and `## Refuted` then told a maintainer the idea had been
  checked and was wrong. At deep, a real defect usually dies to a verifier
  citing a guard it assumed rather than read, so near misses get re-read.
- The merge stage exists because one defect reached from two directions,
  published twice, shows the same bug twice and makes the real finding read as
  one of three. Nothing is nominated on most reports, and the stage then costs
  nothing.
- Measured once: deep on the carrot_core change (50 files, +11398/-3) took
  3h13m and $99.79 at API rates, 8 units, 22 research cells, 4 candidates, all
  refuted. Standard measured $6.62 on 13 files; the old single reviewer ran
  $1.10 to $18.10. One sample each; read the telemetry footer instead.
- `profile` defaults to `deep` on an unrecognised value so a typo costs money
  rather than coverage.

## Running deep on GitHub Actions

`mode=deep` must name a PR number; `pr=sweep` is refused, and a `schedule`
tick carries no inputs, so the sweep is never deep by accident.

```bash
gh workflow run review.yml --repo xmrack/monero-review -f pr=11155
gh workflow run review.yml --repo xmrack/monero-review -f mode=deep -f pr=11155
```

- The workflow file must be on `main`: `claude-code-action` logs "Skipping
  action due to workflow validation" and exits 0 when it differs, so the run
  then fails at `Assert the review pass produced a review`.
- Both tiers get `Workflow` and five `Agent(...)` grants appended. Waiting
  needs `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`, or print mode kills the fleet
  after ten minutes. Measured on CLI 2.1.280: the Lead ends its turn and the
  workflow result arrives as a new turn. `TaskOutput` no longer exists.
- Deep sets `CLAUDE_CODE_RETRY_WATCHDOG=1` so a usage limit is waited out
  (headless runs never wait by default), raises the job timeout to 350
  minutes (concurrent agents are capped at `min(16, max(2, vCPUs - 2))`, which
  is 2 on these runners), never records a failed attempt against the PR, and
  labels the issue `deep-review`. The title is left alone: it is the dedup
  contract `select_prs.py` and `status.py` parse.
- No separate refutation pass runs on either tier: it would rewrite
  `review.md` in place and drop `## Coverage`.
- The first two CI deep runs passed `args` as a JSON string; the harness parses
  it, but an object is the documented shape.

## Report format

- Section order is a contract with `scripts/labels.py`, which counts
  `### [SEVERITY]` headings until `## Refuted`. Anything carrying a bracketed
  severity stays above it; ungraded sections stay below, which is why the
  summary points to them. Measured: a template report with one MEDIUM and one
  LOW yields `medium, low`; bracketed severities in a table cell or refuted
  bullet are ignored; `## Refuted` above `## Findings` yields nothing.
- The summary has a 25-word sentence cap as well as a sentence count because
  "two or three sentences" once produced a 53-word sentence.
- A finding used to have seven labelled blocks with the fix sixth. It is now a
  locator and four blocks, the fix third.
- `· not introduced by this pull request` is fixed text because `labels.py`
  and `disclosure.py` match it literally.
- No confidence word: two graded words in one bracket read as one scale.
  `<n>/2` and `<n>/3` angles agreed carry the same information as counts that
  compare across tiers.
- Refuted entries stay because they are most of what the pipeline produces and
  stop the next review buying a panel for the same idea.
- Coverage was an essay, then eight (standard) or ten (deep) labelled lines
  that mostly said `none`; readers learned to skip it. Lines now appear only
  when they carry a fact. The fixed `This tier.` sentence and the `Proposals.`
  line were removed: the stamp and locator lines carry both. The Verification
  footer was removed; the states it reported now publish no issue at all.
- The coverage stamp exists because the fleet has two halves that die
  separately. Dead readers or dead panels both yield a report with no
  findings, which `labels.py` would publish as a clean review, retiring the
  pull request. The harness refuses on failed cells, unverified panels, or
  broken identities. `published + fixedOnMaster + merged = confirmed` makes
  the merge stage auditable. `deferred` stamps only unclaimed observations
  because the harness publishes that number as never settled.
- A failed run writes no `review.md`: a file explaining the failure has no
  severity heading and would be filed as a clean review.
- Disclosure: the repository, run logs and artifacts are public. A report that
  says it is about a critical fix leaks the moment it is copied, even from the
  private repository. A fix on master is not a fix in a release.
- `owner/repo#N` and github.com pull links make GitHub post a reference event
  on the upstream pull request. `scripts/neutralise.py` strips them, as a
  regex over prose.
- Workflow updates are typed JSON fields, not prose, because everything a
  review reads is untrusted and the job that edits this repository must see
  only a small quotable claim. A stale reference claim sends the next review
  past the place a bug lives.

## Finding standard

- Provenance used to be a fourth requirement. On PR 11196 the fleet traced an
  unauthenticated cross-site `GET` reaching `/stop_daemon` on a default daemon
  and published nothing because the exposure predated the change (also false:
  the unguarded line was the PR's). Pre-existing candidates were the largest
  group of dismissals. Now they are published with the label.
- `fix` is required from the researcher because, when absent, the Lead
  invented "validate the length". The panel never sees the fix: a plausible
  remedy is a cue that the finding must be real.
- `refactorDrift` and `commentDiscrepancy` have their own channels because
  most would fail test 1 for want of an untrusted input, yet both matter to a
  maintainer and neither is a security claim. Comments are read rather than
  hidden: without them every terse guard reads as missing, and a wrong one
  talks a reviewer out of a real bug.
- Severity is re-rated by the panel in both directions, so neither inflating
  nor lowballing works.

## House style

- ASD-STE100 Part 2 (the approved dictionary) is not used: it is built for
  aircraft maintenance. The specification is licensed, so its Part 1 rules are
  restated, not copied.
- GitHub renders a single newline in an issue body as a line break, so prose
  wrapped at 78 columns arrived as ragged short lines. It shipped that way
  once.
- The dash is banned because it lets a sentence avoid deciding how its halves
  relate; a colon promises the explanation follows.
