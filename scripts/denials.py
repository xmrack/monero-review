#!/usr/bin/env python3
"""Print the tool calls a run had refused, from an execution log.

    EXEC_FILE=<path[,path]> python3 scripts/denials.py

The job log reports only `permission_denials_count`. That number is not
actionable: two runs of the same PR with the same allowlist showed 0 denials
outside Actions and 24 inside it, and without the list there is no way to tell
which calls differ. The array lives in the execution file, so surface it where
a reader of the log can see it.

Parses defensively and never fails the job -- the schema is not documented, and
a missing list is worth a note, not a red run.
"""
import json
import os
import re
import sys
import collections

KEYS = ("permission_denials", "permissionDenials")

# Why a call was refused, so denial review is something the harness does on
# every run rather than something a human does by pasting lists into a chat.
#
# Every shape below was observed in a real run and each has a documented
# alternative in the skills. An UNCLASSIFIED denial is therefore the
# interesting one: it means a NEW cause has appeared and the skills do not yet
# answer it. That is the line worth reading.
#
# Ordered most-specific first, and `chain` is last on purpose: a day of runs
# (38 refusals over 48 reviews) had 15 calls labelled `chain` whose real gate
# was a `cd`, a shell block, or a binary that is simply not allowlisted. The
# chaining was never the problem, and "split the chain" was the wrong advice
# every time. Anything more specific therefore suppresses it.
CAUSES = (
    # (label, pattern, the answer the skills already give)
    ("rc-echo",      r'echo\s+"?rc\d*=\$\?',
     "the tool result already reports success/failure"),
    ("loop",         r'\b(for|while|until)\b[^\n]*\bdo\b|\bif\b[^\n]*\bthen\b',
     "a shell block is refused whole, however allowlisted its parts: pass a "
     "glob to a tool that takes many paths -- grep -n pat dir/*.c, "
     "stat -c '%n %s' dir/*, wc -c dir/*"),
    ("compile",      r'\bg\+\+(?!\s+-E\b)',
     "g++ -E is the only compiler form here; nothing is built or run"),
    ("not-allowlisted",
     r'(?:^|[|;&]\s*)(gpg|tar|env|man|col|rm|mkdir|rmdir|getent|hash|xargs|'
     r'make|cmake|curl|wget|python3?|perl|bash|sh|zsh)\b',
     "the binary is not on the allowlist -- read the source instead of "
     "running the tool"),
    ("var-prefix",   r'(?:^|[|;&]\s*)[A-Z_][A-Z0-9_]*=',
     "a VAR=val prefix runs a command the allowlist has not seen, like env; "
     "drop it, or set the variable's effect with the tool's own flag"),
    ("git form",     r'\bgit\s+(?:-C\b|--git-dir|--work-tree|branch\b)',
     "not an allowlisted git form: for a submodule read PR_SUBMODULES.md, "
     "which already holds the bump range, or `cd <dir> && git log` -- cd is "
     "allowlisted, git -C is not"),
    ("git blame",    r'\bgit\s+blame\b',
     "deliberately not allowlisted: git log -S <string> and git log -L find "
     "the commit that introduced a line, and take a path directly"),
    ("redirect",     r'(?<!2)>\s*[^&\s]',
     "use the Write tool"),
    ("substitution", r'\$\(|\$\{|\$\'',
     "resolve it in a separate call"),
    ("dollar-arg",   r'\$\d',
     "an unresolved-looking expansion is refused whatever the quoting: "
     "sed -E 's/.../\\1/' instead of rg -r '$1'"),
    ("outside-tree", r'(^|\s)(/usr/|/etc/|/opt/)|find\s+/\s',
     "/usr/include/boost/X -> deps-include/boost/X"),
    ("cd",           r'(?:^|[|;&]\s*)cd\s',
     "cd is allowlisted now, and you start at the repo root anyway"),
    ("chain",        r';|&&|\|\|',
     "one command takes several args: git log --no-walk <sha> <sha>"),
)

# Quoted text is data, not shell syntax. Matching the raw command reported a
# redirect for `printf '...sizeof(std::map<std::string,int>)==48...'` and for
# `rg -o 'https?://[^ >)\\]+'` -- neither of which redirects anything -- and
# told the model to "use the Write tool". These causes see the command with
# quoted spans blanked out; the rest see it whole.
ON_BARE = frozenset(("loop", "not-allowlisted", "redirect", "cd", "chain",
                     "var-prefix"))
QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")


def bare(cmd):
    """The command with quoted spans blanked, length preserved."""
    return QUOTED.sub(lambda m: " " * len(m.group(0)), cmd)


def classify(cmd):
    """All causes matching one refused command, most specific first."""
    stripped = bare(cmd)
    hits = [name for name, pat, _ in CAUSES
            if re.search(pat, stripped if name in ON_BARE else cmd)]
    # rc-echo and loop both read as chains; report the specific reason.
    if len(hits) > 1 and "chain" in hits:
        hits.remove("chain")
    # $( ) is already reported as a substitution.
    if "substitution" in hits and "dollar-arg" in hits:
        hits.remove("dollar-arg")
    # awk's $0/$1 are its own field syntax, and awk is allowlisted -- flagging
    # them as an unresolved expansion sends the reader after the wrong thing.
    if "dollar-arg" in hits and re.search(r'\bawk\b', cmd):
        hits.remove("dollar-arg")
    return hits or ["UNCLASSIFIED"]


def walk(node, depth=0):
    """Yield every permission-denial list found anywhere in the structure."""
    if depth > 8:
        return
    if isinstance(node, dict):
        for k in KEYS:
            if isinstance(node.get(k), list):
                yield node[k]
        for v in node.values():
            yield from walk(v, depth + 1)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v, depth + 1)


def load(path):
    with open(path) as fh:
        text = fh.read().strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        events = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return events or None


def describe(entry):
    """One line for a denied call: the command, or the path, or the raw input."""
    if not isinstance(entry, dict):
        return "Bash", str(entry)[:160]
    tool = entry.get("tool_name") or entry.get("toolName") or "?"
    ti = entry.get("tool_input") or entry.get("toolInput") or {}
    if isinstance(ti, dict):
        what = ti.get("command") or ti.get("file_path") or json.dumps(ti)
        if ti.get("dangerouslyDisableSandbox"):
            what = f"{what}   [sandbox-disabled retry]"
    else:
        what = str(ti)
    return tool, str(what)[:220]


def main():
    # De-duplicate by real path: both passes' logs were written to one path
    # for a while, and counting that file twice would report 24 refused calls
    # where there were 12. The genuine doubling -- a blocked command retried
    # with the sandbox disabled -- is kept, since that is real behaviour worth
    # seeing.
    seen = set()
    paths = []
    for raw in os.environ.get("EXEC_FILE", "").split(","):
        path = raw.strip()
        if not path or not os.path.exists(path):
            continue
        key = os.path.realpath(path)
        if key not in seen:
            seen.add(key)
            paths.append(path)
    if not paths:
        return
    seen = collections.Counter()
    total = 0
    for path in paths:
        try:
            data = load(path)
        except Exception as exc:                          # noqa: BLE001
            print(f"denials: could not read {path}: {exc}", file=sys.stderr)
            continue
        for lst in walk(data):
            for entry in lst:
                total += 1
                seen[describe(entry)] += 1
    if not total:
        print("denials: none recorded")
        return
    print(f"denials: {total} refused tool call(s), {len(seen)} distinct:")
    causes = collections.Counter()
    for (tool, what), n in seen.most_common():
        hits = classify(what)
        causes.update({h: n for h in hits})
        print(f"  x{n} [{tool}] {what}")
        print(f"      cause: {', '.join(hits)}")

    print("denial causes: "
          + ", ".join(f"{c}={n}" for c, n in causes.most_common()))
    answers = {name: fix for name, _, fix in CAUSES}
    for c, _ in causes.most_common():
        if c in answers:
            print(f"  {c}: {answers[c]}")
    if "UNCLASSIFIED" in causes:
        print("  UNCLASSIFIED: a refusal shape the skills do not yet answer -- "
              "worth reading the command above and adding guidance.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:                              # noqa: BLE001
        print(f"denials: {exc}", file=sys.stderr)
    sys.exit(0)
