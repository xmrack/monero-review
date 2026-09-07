---
name: monero-medium-review
description: "Bounded multi-agent security review of one Monero pull request. The diff is partitioned into units, one researcher takes each unit with all of its weakness classes, and every candidate faces a two-angle panel whose votes are counted in code. The middle tier: several times cheaper than the deep review, and it reads the change in pieces rather than all at once the way the default review must."
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Write, Edit, Workflow, TaskOutput, Agent(monero-mapper), Agent(monero-researcher), Agent(monero-verifier), Agent(monero-explore), Skill, Bash(git diff:*), Bash(git fetch origin:*), Bash(git log:*), Bash(git show:*), Bash(git merge-base:*), Bash(git grep:*), Bash(git rev-parse:*), Bash(git rev-list:*), Bash(git cat-file:*), Bash(git ls-files:*), Bash(git ls-tree:*), Bash(git describe:*), Bash(git shortlog:*), Bash(git name-rev:*), Bash(git --no-pager:*), Bash(readtags:*), Bash(cscope:*), Bash(rg:*), Bash(grep:*), Bash(sed:*), Bash(awk:*), Bash(head:*), Bash(tail:*), Bash(wc:*), Bash(sort:*), Bash(uniq:*), Bash(cut:*), Bash(tr:*), Bash(nl:*), Bash(comm:*), Bash(diff:*), Bash(find:*), Bash(ls:*), Bash(cat:*), Bash(file:*), Bash(stat:*), Bash(xxd:*), Bash(od:*), Bash(strings:*), Bash(basename:*), Bash(dirname:*), Bash(jq:*), Bash(bc:*), Bash(shellcheck:*), Bash(g++ -E:*), Bash(weggli:*), Bash(cd:*), Bash(echo:*), Bash(printf:*), Bash(pwd:*), Bash(realpath:*), Bash(readlink:*), Bash(test:*), Bash(true:*), Bash(false:*), Bash(seq:*), Bash(date:*), Bash(tac:*), Bash(rev:*), Bash(fold:*), Bash(fmt:*), Bash(column:*), Bash(paste:*), Bash(join:*), Bash(cmp:*), Bash(md5sum:*), Bash(sha1sum:*), Bash(sha256sum:*), Bash(cksum:*), Bash(du:*), Bash(git show-ref:*), Bash(git for-each-ref:*), Bash(git symbolic-ref:*), Bash(git diff-tree:*), Bash(git submodule status:*), Bash(git count-objects:*)
---

# Monero medium review

The middle of three. It exists because the two shapes either side of it are
both wrong for a wide-but-ordinary diff:

- the **default review** is one reviewer holding the entire change in one
  context. That is right for a three-file patch and it degrades as the diff
  widens -- every tool result stays in the window, and the files read last are
  read by the most diluted context.
- the **deep review** partitions the change and buys a researcher per unit per
  weakness class and three verifiers per candidate. Measured once at 3h13m and
  $99.79. That is an escalation a human chooses, not something to point at the
  queue.

This is the deep pipeline with the expensive parts removed. It runs the same
`monero-deep-scan` workflow under `profile: "medium"`, which:

- maps the change into at most **5** units and checks the partition against
  the real changed-file list, exactly as the deep pass does;
- dispatches **one researcher per unit**, carrying all of that unit's weakness
  classes, instead of one per unit per class;
- runs **no seam pass and no per-unit second look**. On the one measured deep
  run those two were 28.1% of the fleet's cost and produced one candidate
  between them, which the panel then refuted unanimously;
- still adjudicates every observation a researcher hands on rather than files.
  That stage is cheap and it is the only thing standing between an
  observation somebody wrote down and nobody ever reading it;
- puts each candidate to **two** verifier angles, REACHABILITY and INTRODUCED,
  and requires both. No candidate can reach three agreeing votes, so nothing
  here publishes at `high` confidence -- which is the honest reading of a
  two-angle panel, not a defect;
- runs no advocate re-look. That stage is defined on a two-to-one split, and a
  two-angle panel cannot produce one.

What you give up is real and the report has to say so: no cross-unit trace, no
second look at a unit whose lens assignment was made before anyone read the
code, one fewer angle on every candidate, and no rescue for a candidate a
verifier refuted with a guard it assumed rather than read.

## How it is reached

The sweep routes here on its own. `scripts/tier.py` classifies each PR from
the file listing the selector already fetches, and a change that is wide, or
long, or reaches a trust boundary in more than a few files, comes here instead
of to the default review. A human can also pin it:

```bash
gh workflow run review.yml --repo xmrack/monero-review -f mode=medium -f pr=11155
```

Unlike `mode=deep`, `mode=medium` accepts `pr=sweep`: this tier is affordable
enough that pointing it at the queue is a reasonable thing to want.

The workflow appends `Workflow`, `TaskOutput` and the four `Agent(...)` grants
when it dispatches this skill, exactly as it does for the deep pass, and turns
the `/monero-review-refute` pass off -- this pipeline is its own adversary, and
that pass would rewrite `review.md` in place and throw `## Coverage` away.

## The job

There is one job. Read its recipe and follow it as written:

- [Medium review of one PR](${CLAUDE_SKILL_DIR}/jobs/medium-review.md)

## Environment and paths (use verbatim)

- [REPORT SPEC -- the shape of `review.md`](${CLAUDE_SKILL_DIR}/specs/report-spec.md)
- [FINDING SPEC -- the shape of a candidate](.claude/skills/monero-deep-review/specs/finding-spec.md),
  shared with the deep review and enforced as a schema in the workflow. Not
  duplicated here: the candidate standard does not change with the tier, only
  how many agents apply it.
- Shared Monero references, which every skill here uses:
  - `.claude/references/monero/` -- how the codebase works. `README.md` is the
    index; `macros.md` and `flows.md` are the two every agent should have read
    before it forms a theory.
  - `.claude/skills/monero-security-review/references/trust-boundaries.md`
  - `.claude/skills/monero-security-review/references/codebase-notes.md`
  - `.claude/skills/monero-security-review/references/refutations.md`

@${CLAUDE_SKILL_DIR}/role.md
