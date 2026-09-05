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

Or on GitHub Actions, which files the result as an issue here:

```bash
gh workflow run review.yml --repo xmrack/monero-review -f pr=11155
```

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
  **never runs on its own**. Type `/monero-deep-review` to get it: the diff is
  partitioned into components, a researcher runs per component and per category
  lens, and every candidate faces three independent verifiers whose votes are
  counted in code. Several times the cost of the default review, for a diff
  that earns it. Needs the `Workflow` and `Agent` tools, which the scheduled
  sweep does not grant, so it cannot fire from the queue.
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
