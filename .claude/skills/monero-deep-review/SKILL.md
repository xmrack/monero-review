---
name: monero-deep-review
description: "Deep multi-agent security review of one Monero pull request. The diff is partitioned into components, a researcher fleet hunts each component under a category lens, and every candidate faces a three-lens adversarial panel whose votes are counted in code. Far slower and more expensive than the default single-pass review -- invoke it deliberately, on a diff that earns it."
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Write(./**), Edit(./**), Workflow, Agent(monero-mapper), Agent(monero-researcher), Agent(monero-verifier), Agent(monero-merger), Agent(monero-refactor-check), Agent(monero-explore), Skill, Bash(git diff:*), Bash(git fetch origin:*), Bash(git log:*), Bash(git show:*), Bash(git merge-base:*), Bash(git grep:*), Bash(git rev-parse:*), Bash(git rev-list:*), Bash(git cat-file:*), Bash(git ls-files:*), Bash(git ls-tree:*), Bash(git describe:*), Bash(git shortlog:*), Bash(git name-rev:*), Bash(git --no-pager:*), Bash(readtags:*), Bash(cscope:*), Bash(rtool:*), Bash(rg:*), Bash(grep:*), Bash(sed:*), Bash(awk:*), Bash(head:*), Bash(tail:*), Bash(wc:*), Bash(sort:*), Bash(uniq:*), Bash(cut:*), Bash(tr:*), Bash(nl:*), Bash(comm:*), Bash(diff:*), Bash(find:*), Bash(ls:*), Bash(cat:*), Bash(file:*), Bash(stat:*), Bash(xxd:*), Bash(od:*), Bash(strings:*), Bash(basename:*), Bash(dirname:*), Bash(jq:*), Bash(bc:*), Bash(shellcheck:*), Bash(g++ -E:*), Bash(weggli:*), Bash(cd:*), Bash(echo:*), Bash(printf:*), Bash(pwd:*), Bash(realpath:*), Bash(readlink:*), Bash(test:*), Bash(true:*), Bash(false:*), Bash(seq:*), Bash(date:*), Bash(tac:*), Bash(rev:*), Bash(fold:*), Bash(fmt:*), Bash(column:*), Bash(paste:*), Bash(join:*), Bash(cmp:*), Bash(md5sum:*), Bash(sha1sum:*), Bash(sha256sum:*), Bash(cksum:*), Bash(du:*), Bash(git show-ref:*), Bash(git for-each-ref:*), Bash(git symbolic-ref:*), Bash(git diff-tree:*), Bash(git submodule status:*), Bash(git count-objects:*)
---

# Monero deep review

**This skill never runs on its own.** It runs when a human types
`/monero-deep-review`, or when a dispatch names it (`mode=deep`, which must
name a PR by number). The scheduled sweep keeps using `monero-standard-review`.

It is the standard pipeline with the expensive half put back: one researcher
per unit **per weakness class** (at most 8 units), a pass across the unit
seams, a second look at every unit, and three verifier angles per candidate
rather than two. Use it on a diff that earns it: a large or wide change, a
consensus or crypto-touching rewrite, a submodule bump with real code behind
it, a thin standard review of an obviously risky change, or a re-review where
the first pass and a human disagreed. Not as a retry when a run failed for
harness reasons (timeout, rate limit, refused tool call): re-run the standard
review instead.

No separate refutation pass runs after this one. The harness publishes on the
strength of the coverage stamp, and labels the issue `deep-review`.

## The job

There is one job. Read its recipe and follow it as written:

- [Deep review of one PR](${CLAUDE_SKILL_DIR}/jobs/deep-review.md)

## Environment and paths (use verbatim)

- [FINDING SPEC: the shape of a candidate finding](.claude/specs/finding-spec.md)
- [REPORT SPEC: the shape of `review.md`](.claude/specs/report-spec.md).
  Shared by both tiers; use its `deep` column.
- [HOUSE STYLE: how the prose is written](.claude/references/writing.md).
  Read it with the REPORT SPEC: that one is the structure, this one is the
  writing.
- Shared Monero references, which every skill here uses:
  - `.claude/references/monero/` -- how the codebase works: `README.md` is the
    index, `macros.md` and `flows.md` are the two every agent should have read
    before it forms a theory.
  - `.claude/references/monero/trust-boundaries.md`
  - `.claude/references/monero/codebase-notes.md`
  - `.claude/references/monero/refutations.md`

These are the single source of Monero knowledge in this repository. When
something in them is wrong, fix it there, not in a copy.

@${CLAUDE_SKILL_DIR}/role.md
