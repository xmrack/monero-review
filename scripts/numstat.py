#!/usr/bin/env python3
"""Changed lines per path, from `git diff -z --numstat` on stdin.

Prints `<added+deleted>\t<path>` per file. A rename is counted under its new
path, which is the name `git diff --name-only` gives. Binary files count 0.
"""
import sys

fields = sys.stdin.buffer.read().decode("utf-8", "replace").split("\0")
i = 0
while i < len(fields) - 1:
    added, deleted, path = fields[i].split("\t", 2)
    i += 1
    if not path:  # a rename: the old and new paths follow
        path = fields[i + 1]
        i += 2
    lines = (0 if added == "-" else int(added)) + (0 if deleted == "-" else int(deleted))
    print(f"{lines}\t{path}")
