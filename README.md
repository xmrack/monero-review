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
