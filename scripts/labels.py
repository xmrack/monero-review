#!/usr/bin/env python3
"""Print the labels a review warrants, one per line: the severities highest
first, then `pre-existing` when a surviving finding predates the pull request.

    python3 scripts/labels.py [review.md]

Only findings that SURVIVED verification count. Refuted ones stay in the report
on purpose -- so a reader can see what was considered and dismissed -- but they
must not label the issue. Two things are therefore ignored:

  - everything from a "## Refuted ..." heading onward
  - any finding heading whose own text says REFUTED

Prints nothing when there are no surviving findings, which is the common case.
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


def severities(text):
    cut = REFUTED_SECTION.search(text)
    if cut:
        text = text[:cut.start()]

    found = set()
    for match in HEADING.finditer(text):
        # Only the BRACKET is searched for a status word, never the title.
        # The bracket may hold "SEVERITY / CONFIDENCE" or a status the writer
        # added; the title is prose about Monero, and this pipeline reviews
        # code whose findings are routinely titled things like "bounds check
        # refuted by the caller". Scanning the title dropped that finding's
        # severity entirely: a CRITICAL published with no critical label, and
        # where it was the only finding the publish step went on to say the
        # panel "confirmed none" over a body that carried one.
        #
        # Everything under `## Refuted` is already gone -- the text was cut at
        # that heading above -- so this test is only about an entry marked
        # refuted in place, above the section.
        bracket = match.group(2) or ""
        if re.search(r"refuted", bracket, re.IGNORECASE):
            continue
        found.add(match.group(1).upper())
    return [s for s in SEVERITIES if s in found]


def pre_existing(text):
    """True when a finding that survived verification was not this PR's own."""
    cut = REFUTED_SECTION.search(text)
    if cut:
        text = text[:cut.start()]
    return bool(PRE_EXISTING.search(text))


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


if __name__ == "__main__":
    main()
