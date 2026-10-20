#!/usr/bin/env python3
"""Callers of every function the pull request changes, as markdown on stdout.

Usage: callers.py <checkout> [base-ref]     (base-ref defaults to origin/base)

Reads the head side of `git diff -U0 <base>...HEAD`, finds each function
definition in `tags` whose body overlaps a changed line, and lists its
callers from cscope (src and contrib, then tests) plus every `git grep -w`
match, because cscope misses a call written inside a macro argument.

Name-based, like the index it reads: overloads share a name and virtual or
function-pointer calls have none. Context only; any failure prints a note.
"""
import os
import re
import subprocess
import sys

MAX_FUNCS = 60
MAX_LINES = 25
SRC = re.compile(r"\.(c|cc|cpp|h|hpp|inl)$")


def sh(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True).stdout


def changed_lines(root, base):
    """{path: set(head line numbers)} for added or modified lines."""
    out, path = {}, None
    diff = sh(["git", "--no-pager", "diff", "-U0", "--no-ext-diff", "--no-textconv",
               f"{base}...HEAD", "--", "src", "contrib"], root)
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@") and path and SRC.search(path):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            if m:
                start, n = int(m.group(1)), int(m.group(2) or 1)
                # A pure deletion still touches the function it sat in.
                out.setdefault(path, set()).update(range(start, start + max(n, 1)))
    return out


def functions(root, changed):
    """[(name, qualified, path, start, end)] for definitions overlapping changes."""
    found = []
    with open(os.path.join(root, "tags"), errors="replace") as f:
        for line in f:
            if line.startswith("!"):
                continue
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 4 or cols[1] not in changed:
                continue
            fields = dict(c.split(":", 1) for c in cols[3:] if ":" in c)
            kind = fields.get("kind") or (cols[3] if ":" not in cols[3] else "")
            if kind not in ("f", "function") or cols[0].startswith("__anon"):
                continue
            try:
                start, end = int(fields["line"]), int(fields.get("end", fields["line"]))
            except (KeyError, ValueError):
                continue
            if any(start <= n <= end for n in changed[cols[1]]):
                scope = next((v for k, v in fields.items()
                              if k in ("class", "struct", "namespace")), "")
                qual = f"{scope}::{cols[0]}" if scope else cols[0]
                found.append((cols[0], qual, cols[1], start, end))
    seen, uniq = set(), []
    for fn in sorted(found, key=lambda t: (t[2], t[3])):
        if (fn[1], fn[2], fn[3]) not in seen:
            seen.add((fn[1], fn[2], fn[3]))
            uniq.append(fn)
    return uniq


def cap(lines):
    lines = [x for x in lines if x.strip()]
    if len(lines) > MAX_LINES:
        return lines[:MAX_LINES] + [f"... {len(lines) - MAX_LINES} more"]
    return lines or ["(none)"]


def main():
    root = sys.argv[1]
    base = sys.argv[2] if len(sys.argv) > 2 else "origin/base"
    print("# Callers of the functions this pull request changes\n")
    print("Written by the harness before the review. Name-based: overloads share a")
    print("name, and virtual, function-pointer and macro-generated calls may be")
    print("missing. cscope misses calls inside macro arguments, so the git grep list")
    print("follows it. Covers src and contrib definitions only.\n")
    if not os.path.isfile(os.path.join(root, "tags")):
        print("No symbol index in this run, so nothing was computed. Use git grep.")
        return
    changed = changed_lines(root, base)
    fns = functions(root, changed)
    if not fns:
        print("No changed function definitions in src or contrib.")
        return
    if len(fns) > MAX_FUNCS:
        print(f"{len(fns)} changed functions; the first {MAX_FUNCS} by path are listed.\n")
    names_done = {}
    for name, qual, path, start, end in fns[:MAX_FUNCS]:
        print(f"## `{qual}` -- {path}:{start}-{end}\n")
        if name in names_done:
            print(f"Same name as `{names_done[name]}` above; see its callers.\n")
            continue
        names_done[name] = qual
        for db, label in (("cscope.out", "cscope, production"), ("tests.out", "cscope, tests")):
            if os.path.isfile(os.path.join(root, db)):
                print(f"{label}:\n```")
                print("\n".join(cap(sh(["cscope", "-d", "-f", db, "-L3", name], root).splitlines())))
                print("```")
        grep = sh(["git", "--no-pager", "grep", "-n", "-w", "-e", name, "--",
                   "src", "contrib", "tests"], root).splitlines()
        grep = [g for g in grep if not g.startswith(f"{path}:{start}:")]
        print("git grep -w:\n```")
        print("\n".join(cap(grep)))
        print("```\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 -- context only, never fatal
        print(f"\nCaller list incomplete: {exc}")
