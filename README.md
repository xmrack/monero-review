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

Deep issues carry a `deep-review` label. Standard reviews are unlabelled,
because unlabelled is what ordinary looks like.

To stop the scheduled sweeps:

```bash
gh variable set REVIEW_PAUSED --body 1 --repo xmrack/monero-review
```

`--body 0` resumes. Reviewing a PR by number still works while paused.

## Private disclosure

This repository is public, and so are its run logs, step summaries and
artifacts. Some reviews are filed in the private
`xmrack/monero-review-disclosure` repository instead:

- a surviving CRITICAL or HIGH finding that the pull request did not introduce,
  which means it is already in live code
- a CRITICAL or HIGH finding the pull request introduced that still affects
  live code (the reviewer marks it)
- an obvious fix by Monero developers for a critical or high security bug
  (the reviewer marks it)

`scripts/disclosure.py` makes the decision. For a private review, this
repository gets no issue, no review text in the run summary, no review or
transcript artifact, and no reference-correction pull request. A finding the
pull request introduces, in code that is not live yet, is reported here as
usual.

This needs a `DISCLOSURE_TOKEN` secret: a fine-grained token with Issues
read/write on the disclosure repository. If the secret is missing, nothing is
reviewed.

```bash
gh secret set DISCLOSURE_TOKEN --repo xmrack/monero-review
```

## Two tiers

Every PR the sweep picks up gets a **standard** scan. I can manually launch a 
**deep** review of a PR. 

| | standard | deep |
| --- | --- | --- |
| units the diff is split into | at most 4 | at most 8 |
| researchers | one per unit, all its weakness classes | one per unit **per weakness class** |
| a pass across the unit seams | no | yes |
| a second look at every unit | no | yes |
| verifier angles per candidate | 2 (reachability, guard) | 3 (reachability, guard, impact) |
| an advocate for a candidate one vote short | no | yes |
| findings that are one defect merged into one entry | yes | yes |
| chosen by | default, always | a human, by PR number |

Both run `.claude/workflows/monero-deep-scan.js` under different profiles.

Every candidate goes to a panel whose votes are counted in JavaScript rather
than argued in prose, and the count settles severity at what the panel actually
found, moving a proposer's guess up or down. What survives is checked for duplicates. 

## Where things are

**References**, shared by every skill:

- `.claude/references/writing.md` — **how a report is written.** Orwell's six
  rules and the ASD-STE100 writing rules, applied to a security finding, with
  the words to cut and a pass to run over the draft.
- `.claude/references/monero/` — how the Monero codebase works: architecture,
  six end-to-end flows, per-subsystem notes, the macro families that make grep
  lie, errors and concurrency, build and tests. `README.md` there is the index.
  Its last three files are the other half: what to *suspect*, where the rest
  says what the code *is*.

**Skills:**

- `monero-standard-review/` — **the automatic review.** Every PR on the queue gets it.
- `monero-deep-review/` — A more indepth review which must be manually requested.

There is no third skill. A single-reviewer fallback and its adversarial second
pass used to sit below these; both tiers are the agent fleet now, so a session
that cannot dispatch agents stops and says so rather than reviewing worse.

**Agents and orchestration** — `.claude/agents/` and `.claude/workflows/`. One
workflow script serves both tiers, keyed on `profile`: what they share is the
coverage arithmetic, the candidate schema and the vote counting, which are
exactly the parts that must not drift. `.claude/agents/monero-context.md` is
the context contract every agent opens with.
