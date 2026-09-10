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
STAMP = re.compile(r"^[ \t]*<!--[ \t]*workflow-updates\b(.*?)-->[ \t]*\r?\n?",
                   re.DOTALL | re.MULTILINE | re.IGNORECASE)

FIELDS = ("file", "says", "correction", "evidence")

# Where a correction is allowed to land. An entry naming anything else is
# dropped here rather than passed to a job that can write: the proposer is a
# model that has spent half an hour reading attacker-controlled text, and the
# one thing it must not be able to choose is which file gets rewritten.
ALLOWED_PREFIXES = (
    ".claude/references/monero/",
    ".claude/skills/monero-security-review/references/",
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
                entries.append(got)

    # Strip whether or not anything parsed. A stamp that failed to parse is
    # still not something to publish into a maintainer's issue.
    stripped = STAMP.sub("", text)
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
