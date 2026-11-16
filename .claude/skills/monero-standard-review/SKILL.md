---
name: monero-standard-review
description: "The review every pull request on this queue gets. The diff is partitioned into units, one researcher takes each unit with all of its weakness classes, and every candidate faces a two-angle panel whose votes are counted in code. The bounded half of the pair: far cheaper than the deep review, and it reads the change in pieces rather than all at once."
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Write(./**), Edit(./**), Workflow, Agent(monero-mapper), Agent(monero-researcher), Agent(monero-verifier), Agent(monero-merger), Agent(monero-refactor-check), Agent(monero-explore), Skill, Bash(git diff:*), Bash(git fetch origin:*), Bash(git log:*), Bash(git show:*), Bash(git merge-base:*), Bash(git grep:*), Bash(git rev-parse:*), Bash(git rev-list:*), Bash(git cat-file:*), Bash(git ls-files:*), Bash(git ls-tree:*), Bash(git describe:*), Bash(git shortlog:*), Bash(git name-rev:*), Bash(git --no-pager:*), Bash(readtags:*), Bash(cscope:*), Bash(rtool:*), Bash(rg:*), Bash(grep:*), Bash(sed:*), Bash(awk:*), Bash(head:*), Bash(tail:*), Bash(wc:*), Bash(sort:*), Bash(uniq:*), Bash(cut:*), Bash(tr:*), Bash(nl:*), Bash(comm:*), Bash(diff:*), Bash(find:*), Bash(ls:*), Bash(cat:*), Bash(file:*), Bash(stat:*), Bash(xxd:*), Bash(od:*), Bash(strings:*), Bash(basename:*), Bash(dirname:*), Bash(jq:*), Bash(bc:*), Bash(shellcheck:*), Bash(g++ -E:*), Bash(weggli:*), Bash(cd:*), Bash(echo:*), Bash(printf:*), Bash(pwd:*), Bash(realpath:*), Bash(readlink:*), Bash(test:*), Bash(true:*), Bash(false:*), Bash(seq:*), Bash(date:*), Bash(tac:*), Bash(rev:*), Bash(fold:*), Bash(fmt:*), Bash(column:*), Bash(paste:*), Bash(join:*), Bash(cmp:*), Bash(md5sum:*), Bash(sha1sum:*), Bash(sha256sum:*), Bash(cksum:*), Bash(du:*), Bash(git show-ref:*), Bash(git for-each-ref:*), Bash(git symbolic-ref:*), Bash(git diff-tree:*), Bash(git submodule status:*), Bash(git count-objects:*)
---

# Monero standard review

**This is the review.** Every pull request the sweep picks up gets this one,
and every dispatch that does not say `mode=deep`. `/monero-deep-review` is the
escalation above it; there is nothing below it. A session that cannot dispatch
the fleet stops and says so: there is no single-reviewer fallback.

It runs the `monero-deep-scan` workflow under `profile: "standard"`: at most
**5** units checked against the real changed-file list, **one researcher per
unit** with all its weakness classes, **no seam pass and no per-unit second
look**, an adjudicator for every observation a researcher hands on, **two**
verifier angles per candidate (REACHABILITY, or a specialist DIVERGENCE, SPEC
or OBSERVER in its place, and GUARD; both required, and a `none` consequence
counts as a rejection), an advocate on a 1-1 split, a re-read of every earlier
review's findings at this head, and a merge of surviving findings that one
change at one place would fix (severity the worst member's, every member's
line and vote kept). The role below names who does what.

No separate refutation pass runs after this one.

## The job

There is one job. Read its recipe and follow it as written:

- [Standard review of one PR](${CLAUDE_SKILL_DIR}/jobs/standard-review.md)

## Environment and paths (use verbatim)

- [REPORT SPEC -- the shape of `review.md`](.claude/specs/report-spec.md).
  Shared by both tiers; use its `standard` column.
- [HOUSE STYLE -- how the prose is written](.claude/references/writing.md).
  Read it with the REPORT SPEC: that one is the structure, this one is the
  writing.
- [FINDING SPEC -- the shape of a candidate](.claude/specs/finding-spec.md),
  shared with the deep review and enforced as a schema in the workflow.
- Shared Monero references, which every skill here uses:
  - `.claude/references/monero/` -- how the codebase works. `README.md` is the
    index; `macros.md` and `flows.md` are the two every agent should have read
    before it forms a theory.
  - `.claude/references/monero/trust-boundaries.md`
  - `.claude/references/monero/codebase-notes.md`
  - `.claude/references/monero/refutations.md`

@${CLAUDE_SKILL_DIR}/role.md
