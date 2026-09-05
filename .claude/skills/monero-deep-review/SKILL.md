---
name: monero-deep-review
description: "Deep multi-agent security review of one Monero pull request. The diff is partitioned into components, a researcher fleet hunts each component under a category lens, and every candidate faces a three-lens adversarial panel whose votes are counted in code. Far slower and more expensive than the default single-pass review -- invoke it deliberately, on a diff that earns it."
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Glob, Grep, Workflow, Agent(monero-mapper, monero-researcher, monero-verifier, monero-explore), Bash(git diff:*), Bash(git grep:*), Bash(git log:*), Bash(git show:*), Bash(git rev-parse:*), Bash(git rev-list:*), Bash(git merge-base:*), Bash(git ls-files:*), Bash(git ls-tree:*), Bash(git cat-file:*), Bash(git diff-tree:*), Bash(git name-rev:*), Bash(git describe:*), Bash(git shortlog:*), Bash(git show-ref:*), Bash(git --no-pager:*), Bash(git submodule status:*), Bash(strings:*), Bash(tac:*), Bash(cd:*), Bash(ls:*), Bash(cat:*), Bash(wc:*), Bash(rg:*), Bash(grep:*), Bash(sed:*), Bash(awk:*), Bash(head:*), Bash(tail:*), Bash(sort:*), Bash(uniq:*), Bash(cut:*), Bash(nl:*), Bash(bc:*), Bash(readtags:*), Bash(cscope:*), Bash(weggli:*), Bash(g++ -E:*), Bash(shellcheck:*), Bash(file:*), Bash(stat:*), Bash(xxd:*), Bash(od:*), Bash(echo:*), Bash(printf:*), Bash(test:*), Bash(realpath:*), Bash(basename:*), Bash(dirname:*), Bash(find:*), Bash(diff:*), Bash(cmp:*), Bash(comm:*), Bash(tr:*), Bash(jq:*)
---

# Monero deep review

**This skill never runs on its own.** `disable-model-invocation: true` keeps it
out of automatic selection: it runs when a human types `/monero-deep-review`,
or when a dispatch names it. The scheduled sweep keeps using
`monero-security-review`, and nothing here changes that skill or the pipeline
built around it.

## What this is, and when it is worth it

The default review is one reviewer reading a whole diff, then one adversary
attacking whatever it found. That shape is right for the queue: most PRs are
small, and it costs one review's worth of budget.

This is the other shape. The diff is partitioned into components, a researcher
is dispatched per component *and* per category lens, and every candidate
finding is then put to three independent verifiers -- one per refutation lens
-- whose votes are counted by the workflow's own code rather than argued out
in prose. It costs several times a normal review and takes proportionately
longer.

Use it when the diff earns that: a large or wide change, a consensus or
crypto-touching rewrite, a submodule bump with real code behind it, a PR whose
default review came back thin against an obviously risky change, or a
re-review where the first pass and a human disagreed.

Do not reach for it as a retry when a run failed for harness reasons. A
timeout, a rate limit or a refused tool call is a harness problem; re-run the
default review instead.

## The job

There is one job. Read its recipe and follow it as written:

- [Deep review of one PR](${CLAUDE_SKILL_DIR}/jobs/deep-review.md)

## Environment and paths (use verbatim)

- [FINDING SPEC — the shape of a candidate finding](${CLAUDE_SKILL_DIR}/specs/finding-spec.md)
- [REPORT SPEC — the shape of `review.md`](${CLAUDE_SKILL_DIR}/specs/report-spec.md)
- Shared Monero references, which the default review also uses and which this
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
