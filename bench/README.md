# Recall benchmark

Seeded pull requests with a known answer. Each case is a patch on Monero
master `ef78ff3d` that either brings back a real bug or changes nothing. The
review runs on it as on an open pull request, and `score.py` checks the report.

| split | cases | measures |
| --- | --- | --- |
| `catalogued` | 14 | regressions of bugs in `past-vulnerabilities.md`, which the reviewers read |
| `held-out` | 9 | bugs in classes that file has no entry for: whether the fleet generalises |
| `control` | 4 | renames, comments and logging: false positives |

Each case has a title and description that argue for the change, as a real
author's would. None mentions the bug.

## Run

```
bench/run.sh standard                       # every case, about $180
bench/run.sh deep c09-keyimage-subgroup     # named cases; deep is about $100 each
DRY_RUN=1 bench/run.sh standard             # prepare each case, review none
python3 -I bench/score.py bench/results/<tier>-<time>
```

`run.sh` calls `review-local.sh` with `CASE` set. In that mode it applies the
patch to the case's base as one commit by `contributor`, fetches nothing about
the PR number, writes no prior findings, and keeps the report, execution log
and workflow journals in the results directory. Nothing is published.

## Scoring

- **Found:** a published finding cites a file the patch changed, within 25
  lines of a changed hunk. Refuted findings do not count.
- **Severity:** the worst matching finding against the case's `severity`.
- **Category:** whether a researcher proposed a candidate at that spot under
  one of the case's categories, read from the journals.
- **Controls:** every finding not marked pre-existing is a false positive.

A miss that cites the bug somewhere else, such as a caller, scores as a miss;
read the report before concluding.

## Adding a case

`cases/<id>/patch.diff` applies to `base` in `case.json`. Keep the patch small
and compiling, keep the description free of the answer, and give the case an
unused `number` above 99000 so it can never name a real pull request.
