# monero-review

Automated security review of monero-project/monero pull requests.

It pulls down a PR's head commit, has Claude read the diff against a
Monero-specific review skill, and reports what it finds. Every finding is then
attacked before anything is published, since most first-pass findings turn out
to be wrong. Nothing from the PR is ever built or executed, and Claude has no
network or GitHub access — it just writes a file, and the script around it
decides what to do with that.

## Four tiers, chosen for you

A two-file typo fix and a twenty-file wire-format rewrite are not the same job,
and until recently they got the same review: one Opus reviewer at 200 turns,
whatever arrived. Cost was flat in the size of the change and coverage was not.
So `scripts/tier.py` now sizes each PR from the file listing the selector
already fetches — no extra API call — and routes it:

| tier | what runs | effort | roughly |
| --- | --- | --- | --- |
| **light** | one reviewer, 100 turns, then the adversary | `medium` | ≤2 files, <100 lines, nothing near a trust boundary |
| **standard** | one reviewer, 200 turns, then the adversary | `high` | the ordinary case |
| **medium** | the diff is mapped into units, one researcher per unit, two verifier angles per candidate, counted in code | `high` | ≥10 files, ≥800 lines, or a trust boundary in ≥4 files |
| **deep** | the same pipeline at full width: a researcher per unit *per weakness class*, a cross-unit seam pass, a second look at every unit, three verifier angles, and an advocate for anything one vote short | unset | never automatic — a human asks for it |

**Every tier reads with the same model.** What a cheaper tier buys is less
thinking and fewer turns, not a smaller reader. This is consensus-critical
financial software: a missed bug costs far more than any review, and a smaller
model reads the same diff with less of everything. Effort is also where the
money actually is — thinking tokens were 80% of the deep run's output bill — so
it is a real lever and not a token gesture. It is a *smaller* lever than
swapping models would be, and the saving on the light tier is correspondingly
modest.

`deep` passes no effort at all, on purpose. Its one real measurement was taken
without the flag, the CLI does not document its default, and naming a level
would be changing a measured pipeline blind. Set it only alongside a fresh
measurement to compare against.

Nothing routes to `light` if it touches `src/cryptonote_*`, `src/ringct`,
`src/crypto`, `src/serialization`, `src/rpc`, `src/p2p`, `src/wallet`,
`contrib/epee/` or `external/`, however small it is: a one-line change to a
bounds check in the deserialiser is exactly the diff this pipeline exists for,
and exactly the diff a size heuristic would wave through. Every routing rule
that fires moves a PR to a **heavier** review; the only one that can make a
review cheaper needs the change to be small, short *and* nowhere sensitive.

The thresholds are a first cut and are not measured. The telemetry footer on
every published issue reports real cost per run, which is where to re-derive
them.

## Review one PR

Locally — no secrets, no runner, results in `reviews/`:

```bash
./review-local.sh 11155
```

The tier is chosen the same way there. `TIER=medium ./review-local.sh 11155`
pins one; `DEEP=1` is still the deep review.

Or on GitHub Actions, which files the result as an issue here:

```bash
gh workflow run review.yml --repo xmrack/monero-review -f pr=11155
```

`-f mode=light|standard|medium|deep` pins a tier there. Everything but `deep`
also accepts `-f pr=sweep`. `-f model=` pins the model over the tier's choice;
it is `auto` by default, which is the same model on all four tiers.

## Every review says what it read

A review that opened five of forty files and wrote "No findings." used to
publish exactly like a thorough one — and the issue it files *is* the dedup
record, so that PR would never be looked at again. A coverage hole there is
permanent.

So the harness writes `PR_FILES.md` before the review starts, every report
carries a `## Coverage` section accounting for each of those paths as reviewed
or excluded-with-a-reason, and `scripts/coverage.py` checks the arithmetic
against the real list before anything is published. The fleet tiers have always
done this in JavaScript — the mapper's partition is compared against the
changed-file list and whatever it left out is published as unaccounted — and
this is the single-reviewer equivalent.

Two outcomes, deliberately different:

- a report whose account is **wrong** — the numbers do not add up, or they do
  not match the real file list — is treated as no review at all. Nothing is
  filed, and the PR stays in the queue.
- a report that gives **no account at all** is published with
  `**Coverage not stated**` in its footer, and nothing is withheld. This is a
  ratchet, not a permanent exemption: the `## Coverage` section is new, and
  this repo has watched a mandatory report element go unwritten for 51
  consecutive reviews before. Watch the footers, and once stamps are appearing
  reliably, close it:

  ```bash
  gh variable set COVERAGE_REQUIRED --body 1 --repo xmrack/monero-review
  ```


  From then on a silent report is withheld like a wrong one.

## Review one PR the hard way

The `medium` tier already runs the multi-agent pipeline on anything wide or
sensitive, at a bounded fan-out. What follows is the tier above it.

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
are never mistaken for an ordinary review in the list. `medium` issues carry
`medium-review` the same way; `light` and `standard` are unlabelled, because
an unlabelled issue is what "ordinary" looks like in the list. Everything else
about all four is the same shape: same title contract, same severity labels.

That partitions the diff, runs a researcher per component per weakness class,
and puts every candidate to three independent verifiers whose votes are counted
in code rather than argued in prose. It replaces the two-pass shape rather than
adding to it: the pipeline is its own adversary, so the refutation pass is
turned off. It must name a PR number; `mode=deep` with `pr=sweep` is refused.
A deep run that fails is never charged against the PR's place in the ordinary
queue.

**What it costs, measured once.** On the carrot_core change upstream — 50
files and +11398 lines, at the wide end of what upstream produces — it took
**3h13m and $99.79**, against $13.56 for a default Opus
review of a normal diff. It split that into 8 units and 22 research cells,
proposed 4 candidates, and refuted all 4 unanimously. The runtime caps
concurrent agents at two on any runner this repo can reach, so the fan-out is
paid for in wall clock. Budget hours and about seven times a normal review;
one sample is not a distribution, so read the telemetry footer on each run.

**The `medium` tier is unmeasured.** By construction it is the same pipeline
with the seam pass, the per-unit second look, the third verifier angle and the
top effort tier removed, and with one researcher per unit instead of one per
unit per weakness class — on 9559's partition that is 6 agents where deep
dispatched 15. Extrapolating deep's own cost split puts it somewhere around two
to three times a standard review on a diff that wide, and well under that on an
ordinary one, since unlike the flat single-reviewer shape its cost scales with
the change. **That is arithmetic on one sample, not a measurement.** Run
`TIER=medium ./review-local.sh <n>` once before trusting a number, which is the
same advice the deep tier got and the reason its figure above is real.

## Where things are

- `.claude/references/monero/` — how the Monero codebase actually works:
  architecture, six end-to-end flows, per-subsystem notes, the macro families
  that make grep lie, the coding dialects, errors and concurrency, build and
  tests. Shared by every skill and owned by none of them; `README.md` there is
  the index. The three files under
  `.claude/skills/monero-security-review/references/` are the other half —
  they say what to *suspect*, these say what the code *is*.
- `.claude/skills/monero-security-review/SKILL.md` — the single-reviewer
  review, used by the `light` and `standard` tiers. Edit this if the output
  isn't sharp enough.
- `.claude/skills/monero-medium-review/` — the `medium` tier. It runs the same
  `monero-deep-scan` workflow as the deep review, under `profile: "medium"`:
  at most 5 units, one researcher per unit carrying all of its weakness
  classes, no seam pass, no per-unit second look, two verifier angles instead
  of three, and no advocate. Its report has to say all of that out loud, so a
  clean medium review is never mistaken for a clean deep one.
- `scripts/tier.py` — which review a PR gets, and the only place that policy
  lives. `scripts/coverage.py` — whether a single-reviewer report accounted for
  every changed file.
- `.claude/skills/monero-deep-review/` — a second, much heavier review that
  **never runs on its own**. Type `/monero-deep-review` to get it, or dispatch
  it (below): the diff is partitioned into components, a researcher runs per
  component and per category lens, and every candidate faces three independent
  verifiers whose votes are counted in code. Several times the cost of the
  default review, for a diff that earns it. The router never picks it — the
  tiers it can choose stop at `medium`, and asking for the deep pass is a
  deliberate act by a human.
- `.claude/agents/` and `.claude/workflows/` — the agents and the orchestration
  the two fleet tiers dispatch. One workflow script serves both, keyed on
  `profile`: the parts they share are the coverage arithmetic, the candidate
  schema and the vote counting, which are exactly the parts that must not
  drift between them. `.claude/agents/monero-context.md` is the context
  contract every one of those agents opens with, so they start where the
  default review starts.
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
