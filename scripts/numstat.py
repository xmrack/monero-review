#!/usr/bin/env python3
"""Changed lines per path, from `git diff -z --numstat` on stdin.

Prints `<added+deleted>\t<path>` per file. A rename is counted under its new
path, which is the name `git diff --name-only` gives, quoted as it quotes it.
Binary files count 0.
"""
import sys

ESC = {7: "\\a", 8: "\\b", 9: "\\t", 10: "\\n", 11: "\\v", 12: "\\f", 13: "\\r",
       34: '\\"', 92: "\\\\"}


def quoted(path):
    """The path as git prints it with core.quotePath on."""
    if not any(b < 0x20 or b >= 0x7f or b in (34, 92) for b in path):
        return path.decode("ascii")
    return '"' + "".join(ESC.get(b) or (chr(b) if 0x20 <= b < 0x7f else f"\\{b:03o}")
                         for b in path) + '"'


fields = sys.stdin.buffer.read().split(b"\0")
i = 0
while i < len(fields) - 1:
    added, deleted, path = fields[i].split(b"\t", 2)
    i += 1
    if not path:  # a rename: the old and new paths follow
        path = fields[i + 1]
        i += 2
    lines = (0 if added == b"-" else int(added)) + (0 if deleted == b"-" else int(deleted))
    print(f"{lines}\t{quoted(path)}")
