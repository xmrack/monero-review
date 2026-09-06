# monero-review

Automated security review of monero-project/monero pull requests.

It pulls down a PR's head commit, has Claude read the diff against a
Monero-specific review skill, and reports what it finds. A second pass then
tries to knock down every finding before anything is reported, since most
first-pass findings turn out to be wrong. Nothing from the PR is ever built or
executed, and Claude has no network or GitHub access — it just writes a file,
and the script around it decides what to do with that.

## Review one PR

Locally — no secrets, no runner, results in `reviews/`:

```bash
./review-local.sh 11155
```

`DEEP=1 ./review-local.sh 11155` runs the deep review instead — see below.

Or on GitHub Actions, which files the result as an issue here:

```bash
gh workflow run review.yml --repo xmrack/monero-review -f pr=11155
```

## Review one PR the hard way

For a diff that earns it — a wide change, a consensus or crypto rewrite, a
thin default review against something obviously risky — the same workflow runs
the multi-agent deep review instead:

```bash
gh workflow run review.yml --repo xmrack/monero-review -f mode=deep -f pr=11155
```

or locally, which is the cheaper place to find out what it costs:

```bash
DEEP=1 ./review-local.sh 11155
```

Its issues carry a `deep-review` label, so they are one click to filter for and
are never mistaken for an ordinary review in the list. Everything else about
them is the same shape: same title contract, same severity labels.

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

## Where things are

- `.claude/references/monero/` — how the Monero codebase actually works:
  architecture, six end-to-end flows, per-subsystem notes, the macro families
  that make grep lie, the coding dialects, errors and concurrency, build and
  tests. Shared by every skill and owned by none of them; `README.md` there is
  the index. The three files under
  `.claude/skills/monero-security-review/references/` are the other half —
  they say what to *suspect*, these say what the code *is*.
- `.claude/skills/monero-security-review/SKILL.md` — the review itself. Edit
  this if the output isn't sharp enough.
- `.claude/skills/monero-deep-review/` — a second, much heavier review that
  **never runs on its own**. Type `/monero-deep-review` to get it, or dispatch
  it (below): the diff is partitioned into components, a researcher runs per
  component and per category lens, and every candidate faces three independent
  verifiers whose votes are counted in code. Several times the cost of the
  default review, for a diff that earns it. The scheduled sweep never picks
  it — it grants neither `Workflow` nor `Agent`, and asking for the deep pass
  is a deliberate act.
- `.claude/agents/` and `.claude/workflows/` — the agents and the orchestration
  the deep review dispatches. `.claude/agents/monero-context.md` is the context
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
