---
name: monero-deep-review
description: "Deep multi-agent security review of one Monero pull request. The diff is partitioned into components, a researcher fleet hunts each component under a category lens, and every candidate faces a three-lens adversarial panel whose votes are counted in code. Far slower and more expensive than the default single-pass review -- invoke it deliberately, on a diff that earns it."
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Write, Edit, Workflow, TaskOutput, Agent(monero-mapper), Agent(monero-researcher), Agent(monero-verifier), Agent(monero-merger), Agent(monero-explore), Skill, Bash(git diff:*), Bash(git fetch origin:*), Bash(git log:*), Bash(git show:*), Bash(git merge-base:*), Bash(git grep:*), Bash(git rev-parse:*), Bash(git rev-list:*), Bash(git cat-file:*), Bash(git ls-files:*), Bash(git ls-tree:*), Bash(git describe:*), Bash(git shortlog:*), Bash(git name-rev:*), Bash(git --no-pager:*), Bash(readtags:*), Bash(cscope:*), Bash(rg:*), Bash(grep:*), Bash(sed:*), Bash(awk:*), Bash(head:*), Bash(tail:*), Bash(wc:*), Bash(sort:*), Bash(uniq:*), Bash(cut:*), Bash(tr:*), Bash(nl:*), Bash(comm:*), Bash(diff:*), Bash(find:*), Bash(ls:*), Bash(cat:*), Bash(file:*), Bash(stat:*), Bash(xxd:*), Bash(od:*), Bash(strings:*), Bash(basename:*), Bash(dirname:*), Bash(jq:*), Bash(bc:*), Bash(shellcheck:*), Bash(g++ -E:*), Bash(weggli:*), Bash(cd:*), Bash(echo:*), Bash(printf:*), Bash(pwd:*), Bash(realpath:*), Bash(readlink:*), Bash(test:*), Bash(true:*), Bash(false:*), Bash(seq:*), Bash(date:*), Bash(tac:*), Bash(rev:*), Bash(fold:*), Bash(fmt:*), Bash(column:*), Bash(paste:*), Bash(join:*), Bash(cmp:*), Bash(md5sum:*), Bash(sha1sum:*), Bash(sha256sum:*), Bash(cksum:*), Bash(du:*), Bash(git show-ref:*), Bash(git for-each-ref:*), Bash(git symbolic-ref:*), Bash(git diff-tree:*), Bash(git submodule status:*), Bash(git count-objects:*)
---

# Monero deep review

**This skill never runs on its own.** `disable-model-invocation: true` keeps it
out of automatic selection: it runs when a human types `/monero-deep-review`,
or when a dispatch names it. The scheduled sweep keeps using
`monero-standard-review`, and nothing here changes that skill or the pipeline
built around it.

## Running it on GitHub Actions

`.github/workflows/review.yml` takes a `mode` input. `mode=deep` dispatches
this skill instead of `monero-standard-review`, and it must name a PR by
number — the workflow refuses `mode=deep` with `pr=sweep`, because this is an
escalation a human chooses for a diff that earned it, not something to point
at whatever the queue surfaced.

```bash
gh workflow run review.yml --repo xmrack/monero-review -f mode=deep -f pr=11155
```

**It has to be on `main` first.** `claude-code-action` refuses to run when the
workflow file differs from the copy on the default branch -- it logs "Skipping
action due to workflow validation" and **exits 0**. A dispatch from a feature
branch would therefore write no `review.md` and the run would fail at `Assert
the review pass produced a review`, which is the loud failure that step exists
to produce. Merge, then dispatch.

A `schedule` tick carries no inputs, so `inputs.mode` is empty there and the
sweep is never deep by accident.

What the deep path does differently, and why each matters here:

- it appends `Workflow`, `TaskOutput` and five `Agent(...)` grants to the
  binding allowlist. `Workflow` is what step 3 of the job checks for;
  `TaskOutput` is what step 4b uses to hold the turn open while the fleet
  works, and without it a run starts its own agents and then exits on top of
  them;
- it sets `CLAUDE_CODE_RETRY_WATCHDOG=1`, so a Claude usage limit is waited
  out rather than fatal. Headless runs never wait by default -- the
  interactive "continuing when your limit resets" behaviour is gated on an
  interactive session, and every Actions run is non-TTY -- so without this a
  limit reached three hours in throws the whole run away. The wait counts
  against the job timeout, so it can still lose;
- it turns the `/monero-review-refute` pass **off**, because this pipeline
  already puts every candidate to a counted three-angle panel. Left on, that
  pass would rewrite `review.md` in place and throw away `## Coverage`;
- it raises the job timeout to 350 minutes. The runtime caps concurrent agents
  at `min(16, max(2, vCPUs - 2))`, which is 2 on any runner reachable from
  this repo, so a wide diff is hours of wall clock, not minutes;
- it never records a failed attempt against the pull request. `MAX_ATTEMPTS`
  governs the *default* queue, and a deep run that times out must not be able
  to retire a PR from it;
- it publishes on the strength of the coverage stamp this skill's REPORT SPEC
  requires, not on the refutation pass having run;
- it labels the published issue `deep-review`. The title is left alone -- it
  is the dedup contract `select_prs.py` and `status.py` parse -- so the label
  is the only thing that tells a deep review from a standard one at a glance.

**Measured once**, on the carrot_core change upstream (50 files, +11398/-3):
3h13m wall, $99.79 at API rates, 8 units, 22 research cells, 4 candidates, all
four refuted unanimously. The standard tier's one measurement is $6.62 on 13
files, and the single reviewer that preceded it ran $1.10 to $18.10 depending
on the width of the diff -- so budget an order of magnitude above either, and
hours rather than minutes. 9559 is at the wide end of what upstream produces,
and one sample is not a distribution -- read the telemetry footer on each run
rather than treating this as the number.

## What this is, and when it is worth it

The standard review already partitions the diff and counts its verifiers'
votes -- it is this same pipeline, run under `profile: "standard"`. What it
does not do is the expensive half: it sends one researcher per unit rather than
one per unit per weakness class, looks at no seams, takes no second pass over
any unit, and asks two verifier angles rather than three.

This is that half, put back. It costs several times the standard review and
takes proportionately longer, and the things it adds are precisely the ones
whose absence a standard report has to declare.

Use it when the diff earns that: a large or wide change, a consensus or
crypto-touching rewrite, a submodule bump with real code behind it, a PR whose
standard review came back thin against an obviously risky change, or a
re-review where the first pass and a human disagreed.

Do not reach for it as a retry when a run failed for harness reasons. A
timeout, a rate limit or a refused tool call is a harness problem; re-run the
standard review instead.

## The job

There is one job. Read its recipe and follow it as written:

- [Deep review of one PR](${CLAUDE_SKILL_DIR}/jobs/deep-review.md)

## Environment and paths (use verbatim)

- [FINDING SPEC — the shape of a candidate finding](${CLAUDE_SKILL_DIR}/specs/finding-spec.md)
- [REPORT SPEC — the shape of `review.md`](${CLAUDE_SKILL_DIR}/specs/report-spec.md)
- [HOUSE STYLE — how the prose is written](.claude/references/writing.md).
  Orwell's six rules, the Simplified Technical English rules that apply, the
  words to cut, and the pass to run over the draft. Read it with the REPORT
  SPEC: that one is the structure, this one is the writing.
- Shared Monero references, which every skill here uses and which this
  skill deliberately does not duplicate:
  - `.claude/references/monero/` -- how the codebase works: `README.md` is the
    index, `macros.md` and `flows.md` are the two every agent should have read
    before it forms a theory.
  - `.claude/skills/monero-security-review/references/trust-boundaries.md`
  - `.claude/skills/monero-security-review/references/codebase-notes.md`
  - `.claude/skills/monero-security-review/references/refutations.md`

Those are the single source of Monero knowledge in this repository: the
`references/monero/` directory for what the code IS, the three files under
`monero-security-review/references/` for what to SUSPECT. When something in
either is wrong, fix it there -- every skill improves at once, and a second
copy would drift.

@${CLAUDE_SKILL_DIR}/role.md
