# monero-review

<img width="115" height="115" src="https://github.com/user-attachments/assets/7c680c34-2f05-4614-a262-857eb9aae2a7" />

Automated security review of `monero-project/monero` pull requests. Created by the MAGIC Monero Fund, please [donate](https://donate.magicgrants.org/monero) to help support this effort.

A GitHub runner fetches a new PR's head commit once every 30 minutes, has Claude read the diff against a
Monero-specific skill, and files what it finds as an issue here. Notably, there is a 90 minute waiting period in case a developer is making rapid changes to their PR. Every finding
is attacked by other agents for accuracy and reachability.

## Run a review

On GitHub Actions, which files the result as an issue:

```bash
gh workflow run review.yml --repo xmrack/monero-review -f pr=11155
```

Run locally, leaves the result in `reviews/`:

```bash
./review-local.sh 11155
```

| flag | does |
| --- | --- |
| `-f pr=<n>` / `-f pr=sweep` | one PR, or the next unreviewed ones. `sweep` is the default, and it takes only pull requests targeting `master`; by number reviews any branch |
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

Every PR the sweep picks up gets a **standard** scan. I can manually launch a 
**deep** review of a PR. 

| | standard | deep |
| --- | --- | --- |
| units the diff is split into | at most 4 | at most 8 |
| researchers | one per unit, all its weakness classes | one per unit **per weakness class** |
| a pass across the unit seams | no | yes |
| a second look at every unit | no | yes |
| verifier angles per candidate | 2 (reachability, introduced-by-this-diff) | 3 |
| an advocate for a candidate one vote short | no | yes |
| findings that are one defect merged into one entry | yes | yes |
| chosen by | default, always | a human, by PR number |

Both run `.claude/workflows/monero-deep-scan.js` under different profiles.

Every candidate goes to a panel whose votes are counted in JavaScript rather
than argued in prose, and the count lowers severity. What survives is checked for duplicates. 

## Where things are

**References**, shared by every skill:

- `.claude/references/writing.md` — **how a report is written.** Orwell's six
  rules and the ASD-STE100 writing rules, applied to a security finding, with
  the words to cut and a pass to run over the draft.
- `.claude/references/monero/` — how the Monero codebase works: architecture,
  six end-to-end flows, per-subsystem notes, the macro families that make grep
  lie, errors and concurrency, build and tests. `README.md` there is the index.
- `.claude/skills/monero-security-review/references/` — the other half: what to
  *suspect*, where the tree says what the code *is*.

**Skills:**

- `monero-standard-review/` — **the automatic review.** Every PR on the queue gets it.
- `monero-deep-review/` — A more indepth review which must be manually requested.
- `monero-security-review/` — (LEGACY) the single-reviewer fallback, for a session that
  cannot be granted the agent tools. Not a tier, and nothing in CI routes to
  it. `monero-review-refute/` is its adversarial second pass and runs only
  behind it. 

**Agents and orchestration** — `.claude/agents/` and `.claude/workflows/`. One
workflow script serves both tiers, keyed on `profile`: what they share is the
coverage arithmetic, the candidate schema and the vote counting, which are
exactly the parts that must not drift. `.claude/agents/monero-context.md` is
the context contract every agent opens with.
