# monero-review

Automated security review of monero-project/monero pull requests.

It fetches a PR's head commit, has Claude read the diff against a
Monero-specific skill, and files what it finds as an issue here. Every finding
is attacked by other agents before anything is published, because most
first-pass findings are wrong.

Nothing from the PR is built or executed. The reviewer has no network and no
GitHub access: it writes a file, and the script around it decides what to do
with that.

## Run a review

On GitHub Actions, which files the result as an issue:

```bash
gh workflow run review.yml --repo xmrack/monero-review -f pr=11155
```

Locally, which needs no secrets and leaves the result in `reviews/`:

```bash
./review-local.sh 11155
```

| flag | does |
| --- | --- |
| `-f pr=<n>` / `-f pr=sweep` | one PR, or the next unreviewed ones. `sweep` is the default |
| `-f mode=deep` | the escalation. Requires a PR number; `pr=sweep` is refused |
| `-f model=<id>` | pins the model. Default `auto`, the same model on both tiers |
| `DEEP=1 ./review-local.sh` | deep, locally |
| `TIER=single ./review-local.sh` | the single-reviewer fallback |

Deep issues carry a `deep-review` label. Standard reviews are unlabelled,
because unlabelled is what ordinary looks like.

To stop the scheduled sweeps:

```bash
gh variable set REVIEW_PAUSED --body 1 --repo xmrack/monero-review
```

`--body 0` resumes. Reviewing a PR by number still works while paused.

## Two tiers

Every PR the sweep picks up gets **standard**. A human escalates one to
**deep**. There is no router, no size heuristic and nothing to configure.

| | standard | deep |
| --- | --- | --- |
| units the diff is split into | at most 5 | at most 8 |
| researchers | one per unit, all its weakness classes | one per unit **per weakness class** |
| a pass across the unit seams | no | yes |
| a second look at every unit | no | yes |
| verifier angles per candidate | 2 (reachability, introduced-by-this-diff) | 3 |
| an advocate for a candidate one vote short | no | yes |
| findings that are one defect merged into one entry | yes | yes |
| chosen by | default, always | a human, by PR number |

Both run `.claude/workflows/monero-deep-scan.js` under different profiles, with
the same model at the same care. Deep buys more agents, not a better reader.

Every candidate goes to a panel whose votes are counted in JavaScript rather
than argued in prose, and the count lowers severity.

What survives is checked for duplicates. Findings sharing a file, a symbol or
nearly a title go to an agent that answers one question: would **one change at
one place fix them all**? A group that passes becomes one entry naming every
site. Most reviews nominate nothing and the stage never runs.

Each standard report names what the tier gave up, under `## Coverage`. Those
lines are how somebody decides a change has earned the deep pass.

## Every review says what it read

A review that opened five of forty files and wrote "No findings" publishes like
a thorough one. The issue it files *is* the dedup record, so that PR is never
looked at again. A coverage hole is permanent.

Both tiers settle this in JavaScript. Every changed file must land in a unit,
or in an exclusion with a reason. The workflow checks that against the real
changed-file list and returns anything left over as `unaccounted`, which the
report has to name.

Each report also ends with a machine-readable stamp. The harness refuses to
publish a run whose research mostly died, or whose panels mostly returned no
verdict — such a run is indistinguishable from a clean one, and publishing it
retires the PR for good.

The fallback reviewer has its own version of the same check, in
`scripts/coverage.py`.

## What it costs

| tier | diff | wall | cost |
| --- | --- | --- | --- |
| standard | 13 files | 16m41s | $6.62 |
| standard | 25 files, +2878/-7019 | 27m58s | $11.91 |
| deep | 50 files, +11398 | 3h13m | $99.79 |

Few samples, and both scale with the size of the change — read the telemetry
footer on each run rather than treating these as a distribution. The runner
caps concurrent agents at two, so fan-out is paid for in wall clock.

Every number in that footer is whole-run, agents included:

```
`claude-opus-5` · standard · 8 agents + lead · 20m37s wall ·
7.22M in (6.69M cached) / 150.6k out, 68% thinking · ~$10.74 at API rates ·
25 lead turns · [run]
```

`N agents + lead` is counted from the workflow journal, so it is measured
rather than claimed. `lead turns` is a signal about the orchestrator, not a
proxy for effort. If the CLI schema moves and the whole-run block goes missing,
the footer prints the Lead's own numbers marked `[lead only]` rather than
passing them off as the run.

## Where things are

**References**, shared by every skill and owned by none:

- `.claude/references/writing.md` — **how a report is written.** Orwell's six
  rules and the ASD-STE100 writing rules, applied to a security finding, with
  the words to cut and a pass to run over the draft.
- `.claude/references/monero/` — how the Monero codebase works: architecture,
  six end-to-end flows, per-subsystem notes, the macro families that make grep
  lie, errors and concurrency, build and tests. `README.md` there is the index.
- `.claude/skills/monero-security-review/references/` — the other half: what to
  *suspect*, where the tree says what the code *is*.

**Skills:**

- `monero-standard-review/` — **the review.** Every PR on the queue gets it.
  Edit this if the output is not sharp enough.
- `monero-deep-review/` — the escalation. Never runs on its own; asking for it
  is a deliberate act by a human.
- `monero-security-review/` — the single-reviewer fallback, for a session that
  cannot be granted the agent tools. Not a tier, and nothing in CI routes to
  it. `monero-review-refute/` is its adversarial second pass and runs only
  behind it.

**Agents and orchestration** — `.claude/agents/` and `.claude/workflows/`. One
workflow script serves both tiers, keyed on `profile`: what they share is the
coverage arithmetic, the candidate schema and the vote counting, which are
exactly the parts that must not drift. `.claude/agents/monero-context.md` is
the context contract every agent opens with.

**Scripts:**

- `fetch_rust_deps.py` — puts the Rust dependencies a PR pins on disk so a
  review can read them. Git-pinned crates arrive at exactly that commit;
  monero-oxide is the one that matters, since every FCMP++ change depends on it
  and it is neither a submodule nor vendored. That URL comes from the PR, so
  that half holds an owner allowlist and reports what it refuses.
  For crates.io packages it checks every lockfile sha256 against what the
  registry published; a mismatch is a finding, not a gap. It unpacks source
  only for what the PR adds or bumps, plus the registry original of anything
  `[patch.crates-io]` replaces.
- `select_prs.py` — picks the next PR, skipping ones already reviewed.
- `dispatch.sh` and `drip.sh` — run reviews unattended on a timer.
  `dispatch.sh` goes through GitHub and files issues; `drip.sh` runs locally
  and leaves results in `reviews/`. **Use one or the other:** they keep
  separate records, so running both double-reviews PRs.
- `build_index.sh` — builds a ctags/cscope symbol index so a review can answer
  "who calls this" instead of guessing from grep. Degrades silently to grep.
- `attempt.py` — reads the execution log to decide whether a failed run was the
  PR's fault or the infrastructure's, so a broken runner does not burn the PR's
  place in the queue.
- `coverage.py`, `labels.py`, `telemetry.py`, `denials.py`, `status.py` — the
  harness around a report: coverage check, severity labels, the footer, denied
  tool calls, queue state.
