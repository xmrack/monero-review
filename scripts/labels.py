#!/usr/bin/env python3
"""Print the labels a review warrants, one per line: the severities highest
first, then `pre-existing` when a surviving finding predates the pull request,
then `pipeline-update` when the report proposes a change to this repository's
own reference files.

    python3 scripts/labels.py [review.md]

Only findings that SURVIVED verification count. Refuted ones stay in the report
on purpose -- so a reader can see what was considered and dismissed -- but they
must not label the issue. Two things are therefore ignored:

  - everything from a "## Refuted ..." heading onward
  - any finding heading whose own text says REFUTED

Prints nothing when there are no surviving findings and the report proposes
nothing, which is the common case.
"""
import re
import sys

# Highest first, so the caller can take the first line as the headline severity.
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")

HEADING = re.compile(
    r"^###\s*\[\s*(CRITICAL|HIGH|MEDIUM|LOW)\b([^\]]*)\]\s*(.*)$",
    re.MULTILINE | re.IGNORECASE,
)
REFUTED_SECTION = re.compile(r"^##\s+Refuted\b", re.MULTILINE | re.IGNORECASE)

# A finding the panel settled as `pre-existing` carries this exact phrase on its
# locator line, which the REPORT SPEC fixes as literal text for that reason: it
# is both what a reader sees before opening the block and what gets the label
# onto the issue. Anchored to a locator line -- backtick, path, the middle dot
# separators -- so the phrase appearing in a summary sentence does not label the
# issue on its own.
PRE_EXISTING = re.compile(
    r"^`[^`]+`\s*·.*·\s*not introduced by this pull request\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# The last section of a report, when it has one: changes THIS repository needs,
# found while reading the Monero tree. Two kinds go in it -- a file under
# `.claude/references/monero/` that disagrees with the tree, and a refutation
# durable enough for refutations.md -- and both are proposals for this repo
# rather than statements about the reviewed code.
#
# Detected from a HEADING the REPORT SPEC fixes, not from the prose under it.
# It began as a loose paragraph below the refuted bullets, findable only by
# reading every issue. A regex over model-written prose was the other option
# and a bad one: nothing pins the wording, so it would drift silently and the
# label would stop appearing with nothing to show that it had. The heading is
# grammar, checked the same way `## Refuted` is.
NOMINATION = re.compile(r"^##\s+Workflow Updates\b", re.MULTILINE | re.IGNORECASE)
NEXT_HEADING = re.compile(r"^##\s", re.MULTILINE)
# The section is LAST, so there is no following heading to bound it and the
# coverage stamp falls inside its body. Strip HTML comments before asking
# whether the body is empty, or every omitted-but-present heading would label
# the issue on the strength of the stamp alone -- which is not content, and is
# on every report.
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def severities(text):
    cut = REFUTED_SECTION.search(text)
    if cut:
        text = text[:cut.start()]

    found = set()
    for match in HEADING.finditer(text):
        # The bracket may hold "SEVERITY / CONFIDENCE"; the tail is the title.
        tail = (match.group(2) or "") + (match.group(3) or "")
        if re.search(r"refuted", tail, re.IGNORECASE):
            continue
        found.add(match.group(1).upper())
    return [s for s in SEVERITIES if s in found]


def pre_existing(text):
    """True when a finding that survived verification was not this PR's own."""
    cut = REFUTED_SECTION.search(text)
    if cut:
        text = text[:cut.start()]
    return bool(PRE_EXISTING.search(text))


def nominates(text):
    """True when the report proposes a change to this repository's own files.

    The heading alone is not enough. The spec says to omit it when there is
    nothing to propose, but a Lead that emits it anyway with `- none` or with
    nothing under it must not put a label on the issue -- that would send
    somebody to an issue that proposes nothing, which is exactly the kind of
    wasted trip the label exists to prevent.

    The section is last in the report, so the "next `##` heading" bound below
    finds nothing and the body runs to end of file -- which means it contains
    the coverage stamp. That is why the stamp is stripped before the test.
    Without stripping, a heading followed only by the stamp reads as content
    and labels the issue, and so does `- none`, because neither is an exact
    match for "none" once an HTML comment is stuck to it. Both are the empty
    case and neither may label.
    """
    start = NOMINATION.search(text)
    if not start:
        return False
    rest = text[start.end():]
    end = NEXT_HEADING.search(rest)
    body = COMMENT.sub("", rest[:end.start()] if end else rest).strip()
    if not body:
        return False
    # `- none`, `none`, `nothing`: a section that says it has nothing.
    return not re.fullmatch(r"[-*\s]*(none|nothing)\.?", body, re.IGNORECASE)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "review.md"
    try:
        with open(path, errors="replace") as fh:
            text = fh.read()
    except OSError:
        return
    for sev in severities(text):
        print(sev.lower())
    # After the severities, so a caller taking the first line as the headline
    # severity is unaffected. Emitted only when a SURVIVING finding carries it:
    # the same cut at "## Refuted" applies, because a refuted proposal must not
    # label the issue whatever it was about.
    if pre_existing(text):
        print("pre-existing")
    # Last. Not a severity and not a property of a finding at all -- it is a
    # property of the REPORT, so it is deliberately outside the "## Refuted"
    # cut the two above share: a refutation nominated here is usually drawn
    # from a refuted proposal, and cutting there would discard those.
    if nominates(text):
        print("pipeline-update")


if __name__ == "__main__":
    main()
