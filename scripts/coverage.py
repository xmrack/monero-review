#!/usr/bin/env python3
"""Check that a single-pass review accounted for every file the PR changed.

The multi-agent pipeline settles this in JavaScript: the mapper's placement of
files is compared against the real changed-file list and whatever it left out
is published as unaccounted. The single-reviewer path had no equivalent, and
the gap is not cosmetic. A review that read 5 of 40 files and wrote
"No findings." publishes exactly like a thorough one, and the issue it files
IS the dedup record -- so that pull request is never looked at again. A
coverage hole there is permanent.

So the reviewer now ends its report with

    <!-- scan files=<n> reviewed=<n> excluded=<n> -->

and this compares those numbers against PR_FILES.md, which the harness wrote
from `git diff --name-only origin/base...HEAD` before the review started. The
reviewer does not derive the total -- it copies it from a file the harness
put on disk -- so this gate is about whether every path was accounted for,
not about whether a model can add up.

Exit status is always 0. The verdict goes to stdout as `state=` and `note=`
for $GITHUB_OUTPUT; a caller that wants to fail does so on the state.

Usage: coverage.py <review.md> <PR_FILES.md>
"""
import re
import sys

STAMP = re.compile(r"<!--\s*scan\s+([^>]*?)-->")
FIELD = re.compile(r"\b(\w+)\s*=\s*(\d+)\b")


def parse_stamp(text):
    """The LAST stamp in the file wins.

    Same rule as the deep gate, and for the same reason: a re-run appends, and
    a report must not be judged on an earlier pass's numbers.
    """
    found = STAMP.findall(text)
    if not found:
        return None
    return {k: int(v) for k, v in FIELD.findall(found[-1])}


def real_total(text):
    """How many paths PR_FILES.md lists.

    Written by the harness, one path per line, with `#` comment lines. An
    absent or empty file means the harness did not run this step, which is not
    the review's fault -- the caller reads a None as "cannot check".
    """
    paths = [ln.strip() for ln in text.splitlines()]
    paths = [p for p in paths if p and not p.startswith("#")]
    return len(paths)


def judge(review, files_md):
    stamp = parse_stamp(review)
    if stamp is None:
        return ("missing",
                "the report carries no coverage stamp, so nothing says which "
                "of the changed files were actually read. A quiet report "
                "here is indistinguishable from a review that never opened "
                "most of the diff.")

    have = {k: stamp.get(k) for k in ("files", "reviewed", "excluded")}
    if any(v is None for v in have.values()):
        absent = ", ".join(k for k, v in have.items() if v is None)
        return ("missing",
                f"the coverage stamp is incomplete (no {absent}), so it was "
                "not copied from a real count.")

    claimed, reviewed, excluded = have["files"], have["reviewed"], have["excluded"]

    if reviewed + excluded != claimed:
        return ("mismatch",
                f"the coverage stamp does not add up ({reviewed} reviewed + "
                f"{excluded} excluded is not {claimed} files), so it was not "
                "taken from a real account of the diff.")

    total = real_total(files_md)
    if total == 0:
        # No list to check against. Report it rather than passing silently:
        # an unchecked stamp is a claim, and this file exists because a claim
        # is what it was replacing.
        return ("unchecked",
                f"the report accounts for {claimed} file(s), but the harness "
                "wrote no changed-file list, so the total was not checked "
                "against the real diff.")

    if claimed != total:
        return ("mismatch",
                f"the report accounts for {claimed} file(s) but this pull "
                f"request changes {total}. The review was working from a "
                "different set of files than the one under review.")

    if reviewed == 0:
        return ("mismatch",
                f"the report excludes all {total} changed file(s) and reviews "
                "none. That is not a review of this pull request.")

    note = f"every one of the {total} changed file(s) is accounted for"
    if excluded:
        # Excluding files is legitimate and common -- a CMakeLists.txt with a
        # renamed target does not need a memory-safety read. It is only
        # legitimate WITH a reason, which is prose this cannot check, so say
        # the number out loud and let the reader hold the report to it.
        note += (f" ({reviewed} reviewed, {excluded} excluded with a reason "
                 "stated in the report)")
    return ("ok", note + ".")


def main():
    if len(sys.argv) != 3:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        print("state=missing")
        print("note=coverage.py was called wrongly, so coverage was not checked.")
        return
    try:
        with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
            review = fh.read()
    except OSError as exc:
        print(f"cannot read {sys.argv[1]}: {exc}", file=sys.stderr)
        print("state=missing")
        print("note=the report could not be read, so coverage was not checked.")
        return
    try:
        with open(sys.argv[2], encoding="utf-8", errors="replace") as fh:
            files_md = fh.read()
    except OSError:
        files_md = ""

    state, note = judge(review, files_md)
    print(f"coverage: {state} -- {note}", file=sys.stderr)
    print(f"state={state}")
    print(f"note={note}")


if __name__ == "__main__":
    main()
