# monero-review

Automated security review of monero-project/monero pull requests.

It pulls down a PR's head commit, has Claude read the diff against a
Monero-specific review skill, and reports what it finds. Every finding is then
attacked before anything is published, since most first-pass findings turn out
to be wrong. Nothing from the PR is ever built or executed, and Claude has no
network or GitHub access — it just writes a file, and the script around it
decides what to do with that.

## Two tiers

Every pull request the sweep picks up gets the **standard** review. A human can
escalate one to **deep**. That is the whole of it — there is no router, no size
heuristic and nothing to configure.

| | standard | deep |
| --- | --- | --- |
| units the diff is split into | at most 5 | at most 8 |
| researchers | one per unit, carrying all of its weakness classes | one per unit **per weakness class** |
| a pass across the unit seams | no | yes |
| a second look at every unit | no | yes |
| verifier angles per candidate | 2 (reachability, introduced-by-this-diff) | 3 |
| an advocate for a candidate one vote short | no | yes |
| findings that are one defect merged into one entry | yes | yes |
| highest confidence it can publish | `medium` | `high` |
| chosen by | default, always | a human, by PR number |

Both are the same pipeline — `.claude/workflows/monero-deep-scan.js` under two
profiles — and both read with the same model at the same care. Deep buys more
agents, not a better reader. Every candidate either tier proposes goes to a
panel whose votes are counted in JavaScript rather than argued in prose, with
severity lowered and confidence capped by the count.

What survives the panel then goes through one more stage at both tiers. Several
researchers reaching the same defect from different directions produce several
confirmed findings, and publishing each under its own heading shows a maintainer
one bug three times — which also makes the real finding read as one of three.
Findings sharing a file, a symbol or nearly a title are put to an agent that
decides whether **one change at one place would fix them all**, and a group that
passes becomes a single entry naming every site. The grouping is a partition
checked in JavaScript and the severity is the worst member's, so the stage can
cost the report a heading but never a finding: `published + merged == confirmed`
is in the coverage stamp and the harness refuses to publish a report that fails
it. Most reviews nominate nothing and the stage never runs.

What the standard tier gives up is named in every report it writes, under
`## Coverage`, without hedging: no cross-unit trace, no second look at a unit
whose weakness classes were picked before anyone had read the code, one fewer
angle on every candidate. Those lines are the basis on which somebody decides a
change has earned the deep pass.

The queue used to run a single reviewer over the whole diff and then a second
session to attack whatever it found. That shape is gone from CI. It survives at
`.claude/skills/monero-security-review/` as the fallback for a session that
cannot be granted the agent tools — `TIER=single ./review-local.sh <n>` — and
nothing routes to it.

## Review one PR

Locally — no secrets, no runner, results in `reviews/`:

```bash
./review-local.sh 11155
```

That is the standard review. `DEEP=1 ./review-local.sh 11155` is the deep one,
and `TIER=single` is the fallback reviewer.

Or on GitHub Actions, which files the result as an issue here:

```bash
gh workflow run review.yml --repo xmrack/monero-review -f pr=11155
```

`-f mode=deep` escalates, and requires a PR number. `-f model=` pins the model
over the tier's choice; it is `auto` by default, which is the same model on
both tiers.

## Every review says what it read

A review that opened five of forty files and wrote "No findings." publishes
exactly like a thorough one — and the issue it files *is* the dedup record, so
that PR is never looked at again. A coverage hole there is permanent.

Both tiers settle this in JavaScript rather than in prose. The mapper has to
place every changed file in a unit or in an exclusion with a reason; the
workflow compares its answer against the real changed-file list and returns
whatever it left out as `unaccounted`, which the report must name as neither
reviewed nor excluded. The report ends with a machine-readable stamp — cells
dispatched, cells that failed, candidates, confirmed, refuted, unverified — and
the harness refuses to publish a run whose research mostly died or whose panels
mostly returned no verdict. Such a run and a genuinely clean one are otherwise
indistinguishable from outside, and publishing the first files the marker that
retires the pull request for good.

The harness also writes `PR_FILES.md` before the review starts, so the list is
authoritative and nobody has to re-derive it. The single-reviewer fallback has
its own version of the same idea — a `## Coverage` section and a stamp checked
by `scripts/coverage.py` — which only `review-local.sh` runs.

## Review one PR the hard way

The standard review already runs the multi-agent pipeline on everything, at a
bounded fan-out. What follows is the tier above it.

For a diff that earns it — a consensus or crypto rewrite, a submodule bump with
real code behind it, a review that came back thin against something obviously
risky, or a re-review where the first pass and a human disagreed — the same
workflow runs the full deep review:

```bash
gh workflow run review.yml --repo xmrack/monero-review -f mode=deep -f pr=11155
```

or locally, which is the cheaper place to find out what it costs:

```bash
DEEP=1 ./review-local.sh 11155
```

Its issues carry a `deep-review` label, so they are one click to filter for and
are never mistaken for an ordinary review in the list. Standard reviews are
unlabelled, because an unlabelled issue is what "ordinary" looks like. Both are
otherwise the same shape: same title contract, same severity labels.

It runs a researcher per component *per weakness class*, adds a pass across the
unit seams and a second look at every unit, and puts every candidate to three
verifiers rather than two. It must name a PR number; `mode=deep` with
`pr=sweep` is refused. A deep run that fails is never charged against the PR's
place in the ordinary queue.

**What it costs, measured once.** On the carrot_core change upstream — 50
files and +11398 lines, at the wide end of what upstream produces — it took
**3h13m and $99.79**. It split that into 8 units and 22 research cells,
proposed 4 candidates, and refuted all 4 unanimously. The runtime caps
concurrent agents at two on any runner this repo can reach, so the fan-out is
paid for in wall clock. Budget hours, and read the telemetry footer on each
run rather than treating one sample as a distribution.

**What the standard tier costs.** One measurement so far — the first fleet run
on the queue, 13 files, **$6.62 and 16m41s**, 5 units and 5 research cells with
none failed. Set against the single reviewer it replaced, whose published
footers run **$1.10** (1 file), **$2.18** (2), **$3.27** (5), **$4.12** (7) and
**$18.10** (147 files, +8436/-6419), a 13-file diff at $6.62 sits about where
that curve would put it. Both scale with the size of the change.

Two caveats worth keeping. That is one run at one diff size, and it is now the
cost of *every* pull request upstream opens rather than of the handful a human
escalates — so watch the footers as more land. And the wall clock roughly
doubled, 7m32s to 16m41s: still inside the 30-minute tick, with less slack if
the queue is deep.

The dollar figure in the footer is the whole run, agents included — it comes
from the CLI's `total_cost_usd`, not from the token columns beside it, which
show only the Lead's own conversation.

## Where things are

- `.claude/references/writing.md` — **how a report is written.** Orwell's six
  rules and the Simplified Technical English writing rules, applied to a
  security finding, with the words to cut and a five-step pass to run over the
  draft. Every skill here points at it, and so do the agents whose prose ends
  up in front of a reader. The reports were the thing people complained
  about — too long, and not saying plainly what was broken or what to change —
  so the structure answers three questions in order (is something wrong, where
  is it, what do I change) and this file is what keeps the prose inside it.
- `.claude/references/monero/` — how the Monero codebase actually works:
  architecture, six end-to-end flows, per-subsystem notes, the macro families
  that make grep lie, the coding dialects, errors and concurrency, build and
  tests. Shared by every skill and owned by none of them; `README.md` there is
  the index. The three files under
  `.claude/skills/monero-security-review/references/` are the other half —
  they say what to *suspect*, these say what the code *is*.
- `.claude/skills/monero-standard-review/` — **the review.** Every PR on the
  queue gets it. It runs the `monero-deep-scan` workflow under
  `profile: "standard"`: at most 5 units, one researcher per unit carrying all
  of its weakness classes, no seam pass, no per-unit second look, two verifier
  angles instead of three, and no advocate. Its report has to say all of that
  out loud, so a clean standard review is never mistaken for a clean deep one.
  Edit this if the output isn't sharp enough.
- `.claude/skills/monero-security-review/SKILL.md` — the single-reviewer
  fallback, for a session that cannot be granted the agent tools. Not a tier;
  nothing in CI routes to it. `.claude/skills/monero-review-refute/` is its
  adversarial second pass, and runs only behind it.
  `scripts/coverage.py` checks that its report accounted for every changed
  file — the fleet tiers do that in JavaScript instead.
- `.claude/skills/monero-deep-review/` — the escalation, which
  **never runs on its own**. Type `/monero-deep-review` to get it, or dispatch
  it (below): the diff is partitioned into components, a researcher runs per
  component and per category lens, and every candidate faces three independent
  verifiers whose votes are counted in code. Several times the cost of the
  standard review, for a diff that earns it. Nothing selects it automatically;
  asking for the deep pass is a deliberate act by a human.
- `.claude/agents/` and `.claude/workflows/` — the agents and the orchestration
  the two fleet tiers dispatch. One workflow script serves both, keyed on
  `profile`: the parts they share are the coverage arithmetic, the candidate
  schema and the vote counting, which are exactly the parts that must not
  drift between them. `.claude/agents/monero-context.md` is the context
  contract every one of those agents opens with, so they start where the
  standard review starts.
- `scripts/fetch_rust_deps.py` — puts the Rust dependencies a PR pins on disk,
  so a review can read them. For **git-pinned** crates that means the source at
  exactly that commit; monero-oxide is the one that matters, since every FCMP++
  change depends on it and it is neither a submodule nor vendored, so it used to
  be unreadable and cost real coverage. The URL comes from the pull request, so
  that half holds an owner allowlist and reports anything it refuses in
  `RUST_DEPS.md` rather than fetching it.
  For **crates.io** packages it does two different things. Every registry
  package's lockfile sha256 is checked against the crates.io index, which says
  what was actually published for that version — a mismatch is a finding, not a
  gap. Source is unpacked only for what the PR adds or bumps, plus the registry
  original of any crate `[patch.crates-io]` replaces, since a patch swaps in
  somebody's fork with nothing in the lockfile recording what it replaced. The
  registry host is fixed rather than attacker-chosen, so that half is guarded by
  a pinned host, a sanitised name and version, and a mandatory digest match
  before anything is unpacked.
- `scripts/select_prs.py` — picks the next PR, skipping ones already reviewed.
- `scripts/dispatch.sh` and `scripts/drip.sh` — run reviews unattended on a
  timer. `dispatch.sh` runs the review on GitHub and files results as issues;
  `drip.sh` runs it locally and leaves results in `reviews/`. Use one or the
  other: they keep separate records of what has been reviewed, so running both
  double-reviews PRs.

To stop the GitHub Actions sweeps:

```bash
gh variable set REVIEW_PAUSED --body 1 --repo xmrack/monero-review
```

`--body 0` resumes. Reviewing a specific PR by number still works while paused.
