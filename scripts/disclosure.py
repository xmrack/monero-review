#!/usr/bin/env python3
"""Decide where a review is published: this public repository, or the private
disclosure repository.

    python3 scripts/disclosure.py [review.md]          # decide
    python3 scripts/disclosure.py --strip review.md    # body for the issue

Deciding prints two lines and nothing else:

    route=public|private
    reason=<why, or empty>

--strip prints the report with every disclosure marker removed, using the same
pattern that decided the route, so a marker that routed a review private can
never survive into the issue it files.

NEVER echo the decision into the job log, and never hand it to a later step
through `env:` or a step output: GitHub prints a step's `env:` block in the
public log. This repository is public, and so are its run logs, step
summaries and artifacts. The workflow writes it to a file outside the
workspace, and each consumer reads that file inside its own `run:`.

A review goes private when any of these holds:

  pre-existing  a CRITICAL or HIGH finding that survived the panel and is not
                this pull request's own. It is in code that is already live,
                so publishing it is publishing a zero-day.
  security-fix  the review carries `<!-- disclosure reason=security-fix -->`:
                the pull request is an obvious fix, by Monero developers, for a
                critical or high severity security bug -- a cryptographic flaw,
                a consensus bug, a remote crash. A public review of the patch
                points at the hole before the release ships.
  live-code     the review carries `<!-- disclosure reason=live-code -->`: a
                CRITICAL or HIGH finding that this pull request did not add to
                the surviving list as pre-existing, but which still affects
                code that is live (the change is already merged, or the same
                defect sits in the base branch or a release).

Anything else is public. A finding the pull request introduces, in code that is
not live yet, is reported normally: that is the whole point of reviewing a pull
request before it merges.

FAILS CLOSED. A report that is missing, empty or unreadable, or a marker with
a reason this script does not know, routes private. Missing is the important
one: a run that died before writing its report still left a transcript full
of candidate findings, and "public" would let that reach a public artifact.
Filing a harmless review in the private repository costs a maintainer a
minute; filing a harmful one in public cannot be undone.
"""
import re
import sys

REFUTED_SECTION = re.compile(r"^##\s+Refuted\b", re.MULTILINE | re.IGNORECASE)

# The shapes labels.py reads, but looser on purpose. There a paraphrase costs a
# label; here it publishes a live zero-day. So bold or stray spacing around the
# bracket still counts as a finding heading.
HEADING = re.compile(
    r"^###\s*\**\s*\[\s*(CRITICAL|HIGH|MEDIUM|LOW)\b([^\]]*)\]",
    re.MULTILINE | re.IGNORECASE,
)
# Where a finding's block ends: the next finding, or the next section.
BLOCK_END = re.compile(r"^##", re.MULTILINE)
# Anywhere in the finding's block, not only on an exact locator line: a
# trailing full stop or a bolded path must not send a finding public. The
# `Where it came from.` block opening on "pre-existing" counts too.
PRE_EXISTING = re.compile(
    r"not\s+introduced\s+by\s+this\s+pull\s+request"
    r"|\*\*Where it came from\.?\*\*\s*\**\s*pre-?existing",
    re.IGNORECASE,
)
# Searched over the WHOLE file: the marker sits at the foot, below
# `## Refuted`, beside the other stamps. Lazy and across lines, so neither a
# line break nor a `>` inside the comment hides it.
MARKER = re.compile(r"<!--\s*disclosure\b(.*?)-->", re.IGNORECASE | re.DOTALL)
MARKER_REASON = re.compile(r"\breason\s*=\s*([a-z-]+)", re.IGNORECASE)
KNOWN_REASONS = ("security-fix", "live-code")


def severe_pre_existing(text):
    """True when a surviving CRITICAL or HIGH finding predates the PR."""
    cut = REFUTED_SECTION.search(text)
    if cut:
        text = text[:cut.start()]
    for match in HEADING.finditer(text):
        if match.group(1).upper() not in ("CRITICAL", "HIGH"):
            continue
        if re.search(r"refuted", match.group(2) or "", re.IGNORECASE):
            continue
        end = BLOCK_END.search(text, match.end())
        block = text[match.end():end.start() if end else len(text)]
        if PRE_EXISTING.search(block):
            return True
    return False


def marker_reason(text):
    """The reason on the first disclosure marker, `unknown` for a marker whose
    reason is missing or not one we know, or None when there is no marker."""
    match = MARKER.search(text)
    if not match:
        return None
    reason = MARKER_REASON.search(match.group(1))
    if reason and reason.group(1).lower() in KNOWN_REASONS:
        return reason.group(1).lower()
    return "unknown"


def route(text):
    reason = marker_reason(text)
    if reason:
        return "private", reason
    if severe_pre_existing(text):
        return "private", "pre-existing"
    return "public", ""


def strip(text):
    """The report with every marker, and the line it sat on when alone, cut."""
    text = re.sub(r"(?m)^[ \t]*" + MARKER.pattern + r"[ \t]*\n?", "", text,
                  flags=re.IGNORECASE | re.DOTALL)
    return MARKER.sub("", text)


def main():
    args = sys.argv[1:]
    if args[:1] == ["--strip"]:
        path = args[1] if len(args) > 1 else "review.md"
        with open(path, errors="replace") as fh:
            sys.stdout.write(strip(fh.read()))
        return
    path = args[0] if args else "review.md"
    try:
        with open(path, errors="replace") as fh:
            text = fh.read()
    except OSError:
        # Missing included. See FAILS CLOSED above.
        where, why = "private", "none"
    else:
        if not text.strip():
            where, why = "private", "none"
        else:
            try:
                where, why = route(text)
            except Exception:  # noqa: BLE001 -- any parsing failure fails closed
                where, why = "private", "unreadable"
    print(f"route={where}")
    print(f"reason={why}")


if __name__ == "__main__":
    main()
