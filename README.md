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
| `-f pr=<n>` / `-f pr=sweep` | one PR, or the next unreviewed ones. `sweep` is the default: pull requests targeting `master`, then merged ones whose final head was never reviewed, then `release-v*` backports. By number reviews any branch |
| `-f mode=deep` | the escalation. Requires a PR number; `pr=sweep` is refused |
| `-f model=<id>` | pins the model. Default `auto`, the same model on both tiers |
| `DEEP=1 ./review-local.sh` | deep, locally |
| `TESTS=1 ./review-local.sh` | also build the head with ASan+UBSan and run its unit tests offline (needs docker; `TESTS=core` adds the consensus suite) |

When the PR is merged, every confirmed finding is also read against upstream
master and the branch it merged into. Ones a later commit fixed on both move to
a `## Fixed on master` section and the issue gets a `fixed-on-master` label.

Deep issues carry a `deep-review` label. Standard reviews are unlabelled.

To stop the scheduled sweeps:

```bash
gh variable set REVIEW_PAUSED --body 1 --repo xmrack/monero-review
```

`--body 0` resumes. Reviewing a PR by number still works while paused.

Deep reviews first build the PR head with ASan and UBSan and run its unit
tests, plus `core_tests` when consensus code moved, in an offline container in
a job that holds no secrets. The result reaches the reviewers as
`PR_TESTS.md`: a lead to read, never a finding. A failing test is run again on
base, so the file says which failures the PR brought. Standard reviews get it
too when the variable is set (about an hour of runner time per PR):

```bash
gh variable set PR_TESTS --body 1 --repo xmrack/monero-review
```

### Transcripts

A run's report, execution log, agent journals and diagnostics are uploaded as
one artifact, `transcript-<pr>`, encrypted to an OpenPGP public key.

```bash
gpg --armor --export you@example.org | gh variable set TRANSCRIPT_PUBLIC_KEY --repo xmrack/monero-review
gh run download <run-id> -n transcript-<pr> --repo xmrack/monero-review
gpg -d transcript.tar.gz.gpg | tar xz
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
| an advocate for a candidate one vote short | yes (1-1) | yes (2-1) |
| sanitizer build and tests | when `PR_TESTS=1` | yes |
| findings that are one defect merged into one entry | yes | yes |
| chosen by | default, always | a human, by PR number |

Both run `.claude/workflows/monero-deep-scan.js` under different profiles.

Every candidate goes to a panel whose votes are counted in code, and the count
settles severity at what the panel actually found, moving a proposer's guess up
or down. Consensus, crypto and privacy candidates get a specialist angle
(divergence, spec, observer) in reachability's place, and every verifier says
what the defect buys; one that buys nothing is refuted. What survives is
checked for duplicates.

## Where things are

**References**, shared by every skill:

- `.claude/references/writing.md` — **how a report is written.** Orwell's six
  rules and the ASD-STE100 writing rules, applied to a security finding, with
  the words to cut and a pass to run over the draft.
- `.claude/references/monero/` — how the Monero codebase works: architecture,
  six end-to-end flows, per-subsystem notes, the macro families that make grep
  lie, errors and concurrency, build and tests, and `lenses.md`, where each
  weakness class lives in the tree. `README.md` there is the index.
  Its judgement files are the other half: what to *suspect*, where the rest
  says what the code *is*.

**Skills:**

- `monero-standard-review/` — **the automatic review.** Every PR on the queue gets it.
- `monero-deep-review/` — A more indepth review which must be manually requested.

**Agents and orchestration** — `.claude/agents/` and `.claude/workflows/`. One
workflow script serves both tiers, keyed on `profile`: what they share is the
coverage arithmetic, the candidate schema and the vote counting, which are
exactly the parts that must not drift. `.claude/agents/monero-context.md` is
the context contract every agent opens with. `scripts/rtool` gives the agents
read-only git inside submodules and `rust-deps/`, caller lists, and weggli with
the right flags; `scripts/callers.py` writes `PR_CALLERS.md` before a review.
