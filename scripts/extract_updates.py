#!/usr/bin/env python3
"""Lift the `<!-- workflow-updates ... -->` stamp out of a review and drop it.

The review run reads a stranger's pull request and is read-only by
construction. It cannot open a pull request against this repository, and it
must not: everything it read this run is untrusted by assumption, and a change
to the files that tell the reviewer what to think is this pipeline's own
supply chain. So the Lead writes what it found into a JSON stamp, this script
lifts it out into a file for a later job that has write access and has never
seen the Monero tree, and the stamp is REMOVED from the review before the
issue is published -- a Monero maintainer has no use for our housekeeping.

Both halves matter. Not extracting loses the finding; not stripping publishes
JSON into somebody else's issue.

Exit status is always 0 and the review is left publishable whatever happens.
A malformed stamp costs one correction, and no correction is worth failing a
review that already cost half an hour of Opus.

Usage: extract_updates.py <review.md> <out.json>
"""
import json
import os
import re
import sys

# Non-greedy to the first `-->`, so prose containing the closing marker
# truncates its own entry rather than swallowing the coverage stamp below it.
STAMP = re.compile(r"<!--[ \t]*workflow-updates\b(.*?)-->",
                   re.DOTALL | re.IGNORECASE)
# The same thing anchored to its own line, which is where the REPORT SPEC puts
# it and how it is normally written. Stripping with this one first takes the
# trailing newline too, so removing a stamp that stood alone does not leave a
# blank line behind.
#
# Matching was ANCHORED before, and that was the bug: a stamp with any text
# before it on the line matched nothing, so the corrections were never
# extracted AND the raw JSON was never stripped -- it published verbatim into
# a Monero maintainer's issue, which is the one outcome this script exists to
# prevent. Exit status is 0 either way, so nothing downstream noticed.
STAMP_LINE = re.compile(r"^[ \t]*<!--[ \t]*workflow-updates\b.*?-->[ \t]*\r?\n?",
                        re.DOTALL | re.MULTILINE | re.IGNORECASE)

FIELDS = ("file", "says", "correction", "evidence")

# Where the observation was made, stamped onto every entry from the harness's
# own environment. NOT taken from the model's stamp, and a `source` key in the
# stamp is dropped: the whole point is to tell a human which tree a line number
# came from, and a field the reviewed pull request's author could influence
# answers the opposite question.
#
# It matters because the two trees disagree. A reviewer reads the PR's HEAD --
# master plus that author's unmerged changes, or release-v0.18 plus them for a
# backport -- while the references describe the branch the PR targets. A
# citation lifted from the head can name a line the change itself moved, or a
# symbol that exists only on that branch. Merging it then writes the pull
# request's private state into a file that claims to describe Monero.
SOURCE_KEYS = ("upstream", "pr", "head", "base")


def source_from_env():
    """The reviewed pull request, as the workflow knows it. None when unset."""
    got = {
        "upstream": os.environ.get("UPSTREAM", ""),
        "pr": os.environ.get("PR_NUMBER", ""),
        "head": os.environ.get("HEAD_SHA", ""),
        "base": os.environ.get("BASE_REF", ""),
    }
    # All or nothing. A half-filled stamp reads like a provenance claim while
    # answering none of the question, which is worse than saying nothing: the
    # later job prints "could not be determined" and a reader knows to check.
    if not all(got.values()):
        return None
    return {k: " ".join(str(got[k]).split())[:200] for k in SOURCE_KEYS}

# Where a correction is allowed to land. An entry naming anything else is
# dropped here rather than passed to a job that can write: the proposer is a
# model that has spent half an hour reading attacker-controlled text, and the
# one thing it must not be able to choose is which file gets rewritten.
ALLOWED_PREFIXES = (
    ".claude/references/monero/",
)


def clean(entry):
    """Return a sanitised entry, or None when it may not be acted on."""
    if not isinstance(entry, dict):
        return None
    out = {}
    for k in FIELDS:
        v = entry.get(k)
        if not isinstance(v, str) or not v.strip():
            return None
        # One line each and bounded: these are quoted into a pull request body.
        out[k] = " ".join(v.split())[:2000]
    # NOT `lstrip("./")`: that strips a character SET, so `.claude/...` loses
    # its leading dot and every legitimate entry is refused. Measured -- it
    # rejected all eight valid fixtures before this was caught.
    path = out["file"]
    while path.startswith("./"):
        path = path[2:]
    if not path.startswith(ALLOWED_PREFIXES) or not path.endswith(".md"):
        print("extract: refusing entry outside the reference files: %r" % out["file"],
              file=sys.stderr)
        return None
    # No traversal, no absolute paths, nothing clever.
    if ".." in path.split("/") or path != os.path.normpath(path):
        print("extract: refusing suspicious path: %r" % out["file"], file=sys.stderr)
        return None
    out["file"] = path
    return out


def main():
    review = sys.argv[1] if len(sys.argv) > 1 else "review.md"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "workflow-updates.json"
    try:
        with open(review, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return

    source = source_from_env()
    if source is None:
        print("extract: no reviewed-PR context in the environment; corrections "
              "will carry no provenance", file=sys.stderr)

    entries = []
    for match in STAMP.finditer(text):
        try:
            parsed = json.loads(match.group(1).strip())
        except ValueError as exc:
            print("extract: unparseable workflow-updates stamp, dropped: %s" % exc,
                  file=sys.stderr)
            continue
        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list):
            continue
        for entry in parsed:
            got = clean(entry)
            if got:
                # After clean(), so a `source` the model wrote is already gone:
                # clean() copies only FIELDS.
                if source is not None:
                    got["source"] = dict(source)
                entries.append(got)

    # Strip whether or not anything parsed. A stamp that failed to parse is
    # still not something to publish into a maintainer's issue.
    # Whole-line form first so a stamp on its own line takes its newline with
    # it; then the unanchored form for one sitting mid-line, where only the
    # stamp goes and the prose around it stays.
    stripped = STAMP.sub("", STAMP_LINE.sub("", text))
    if stripped != text:
        with open(review, "w", encoding="utf-8") as fh:
            fh.write(stripped)
        print("extract: removed the workflow-updates stamp from the review")

    if entries:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2)
        print("extract: %d reference correction(s) proposed" % len(entries))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:                          # noqa: BLE001
        print("extract: %s" % exc, file=sys.stderr)
    sys.exit(0)
