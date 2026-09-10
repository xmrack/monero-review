#!/usr/bin/env python3
"""Print the labels a review warrants, one per line: the severities highest
first, then `pre-existing` when a surviving finding predates the pull request,
then `pipeline-update` when the report proposes a change to this pipeline's own
reference material.

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

# A report that nominates a refutation as durable -- true of the codebase
# rather than of this diff, and so worth adding to refutations.md so the next
# review does not buy a panel for it again.
#
# Detected from a HEADING the REPORT SPEC fixes, not from the prose under it.
# The nomination used to be a loose paragraph below the refuted bullets, and
# the only way to find one was to read every issue. A regex over model-written
# prose would have been the other option and a bad one: nothing pins the
# wording, so it would drift silently and the label would quietly stop
# appearing. The heading is grammar, checked the same way `## Refuted` is.
#
# The label is named for the general case rather than for refutations. Today
# this section is the only thing a report can propose, but anything else the
# pipeline learns to nominate about its OWN material belongs under the same
# label, and renaming a label that maintainers have started filtering on is
# worse than choosing the wider word now.
NOMINATION = re.compile(r"^##\s+Nominated refutations\b", re.MULTILINE | re.IGNORECASE)
NEXT_HEADING = re.compile(r"^##\s", re.MULTILINE)


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
    """True when the report proposes an addition to the pipeline's references.

    The heading alone is not enough. The spec says to omit it when there is
    nothing to nominate, but a Lead that emits it anyway with `- none` or with
    nothing under it must not put a label on the issue -- that would send a
    maintainer to an issue that proposes nothing, which is exactly the kind of
    wasted trip the label exists to prevent.
    """
    start = NOMINATION.search(text)
    if not start:
        return False
    rest = text[start.end():]
    end = NEXT_HEADING.search(rest)
    body = (rest[:end.start()] if end else rest).strip()
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
    # cut the two above share: a nomination drawn from a refuted proposal is
    # the normal case, and cutting there would discard almost all of them.
    if nominates(text):
        print("pipeline-update")


if __name__ == "__main__":
    main()
