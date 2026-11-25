#!/usr/bin/env python3
"""Reachability from the call graph of upstream master (callgraph/, callgraph.json).

  reach.py pr <checkout> [base-ref]      PR_REACH.md on stdout: every function the
                                         pull request changes, the entrypoints that
                                         reach it and their shortest paths
  reach.py fn <checkout> <function> [path[:line]]   (line: master's, as printed)
  reach.py path <checkout> <from> <to>

The graph is master's, built from GCC call-graph dumps and libclang and merged
into a trailmark snapshot. A path is a lead to confirm in the source; no path
proves nothing. Context only: any failure prints a note.
"""
import collections
import importlib.util
import json
import os
import re
import subprocess
import sys

MAX_FUNCS = 60
PATHS = {"untrusted_external": 4, "semi_trusted_external": 3}
MAX_CALLERS = 15
GRAPH = "monero-review-callgraph.json"   # in the checkout's git directory, out of rg's way
INFERRED = {"trailmark", "gcc_instantiation_kept", "gcc_bridged", "virtual", "template_virtual", "template_argument", "template_enclosing_class",
            "reference", "reference_instantiation", "lambda", "function_table"}
# The daemon and wallet RPC servers share one HTTP parser, an untrusted
# entrypoint; untrusted paths stop at the wallet's handler, and do not enter
# a daemon RPC method that restricted mode refuses.
WALLET_GATE = re.compile(r"wallet_rpc_server::handle_http_request$")
RPC_MAP = re.compile(r"core_rpc_server::handle_http_request_map$")
UNRESTRICTED = "daemon RPC, unrestricted only"
CONDITIONAL = re.compile(r"(release_protocol|anvoke_handler::cancel|miner::start|miner::worker_thread)$")
TRUST = {"untrusted_external": "untrusted", "semi_trusted_external": "semi-trusted",
         "trusted_internal": "trusted-internal"}

HOW = """How to read this:
- A path is a lead, to confirm in the source at this pull request's head.
  `gcc` hops are calls the compiler made; `gcc_instantiation` is a call made
  by a template instantiated from that caller. `trailmark` is trailmark's
  name-based parse, where the compiler saw no call. `gcc_instantiation_kept` is a call made by some instantiation
  of a template, credited to every caller of it; `gcc_bridged` hops pass
  through std or boost; `virtual`, `reference`, `lambda`, `template_*` and
  `function_table` hops are inferred from the class hierarchy or from where
  a callback is registered. All of these are flagged *inferred hops*.
- No path, or a function missing from the graph, proves nothing. The graph
  is of master, so calls this pull request adds are absent, and it covers one
  Linux build. asio handlers hang off the code that registers them, not off
  `io_context::run()`.
- Paths marked *conditional* pass through connection teardown
  (`release_protocol`, `anvoke_handler::cancel`) or the miner thread. They
  are real, but a finding that rests on one must say so.
- The daemon and wallet RPC servers share one HTTP parser. Untrusted paths
  are not followed into `wallet_rpc_server::handle_http_request` (the wallet
  RPC is semi-trusted) or into daemon RPC methods restricted mode refuses,
  nor into those methods' request parsers; `rtool path` says when its only
  path goes that way.
- The daemon is untrusted by the wallet: wallet functions that ask it for
  data, and `wallet2::refresh`, are untrusted entrypoints ("daemon reply to
  the wallet"), since a remote node chooses the reply.
- A label shared by several functions (overloads) carries its master
  `path:line`; pass that to `rtool reach <fn> <path>:<line>`."""


class Graph:
    def __init__(self, path):
        g = json.load(open(path))
        if g.get("format") != "monero-review-callgraph/1":
            raise ValueError("unknown call graph format")
        self.commit, self.built = g["commit"], g["built"]
        self.nodes = g["nodes"]                  # [id, label, path, start, end]
        for n in self.nodes:
            n[1] = n[1].replace("::::", "::(anonymous)::")
        self.origins = g["origins"]
        self.pred = collections.defaultdict(dict)
        self.succ = collections.defaultdict(dict)
        for a, b, o in g["edges"]:
            self.pred[b][a] = self.origins[o]
            self.succ[a][b] = self.origins[o]
        self.entry = {e: (t, d) for e, t, d in g["entrypoints"]}
        self.gate = {i for i, n in enumerate(self.nodes) if WALLET_GATE.search(strip_targs(n[1]))}
        rpc_map = {i for i, n in enumerate(self.nodes) if RPC_MAP.search(strip_targs(n[1]))}
        self.cut = {(m, e) for e, (t, d) in self.entry.items() if d == UNRESTRICTED
                    for m in rpc_map if e in self.succ[m]}
        self.cut |= {tuple(x) for x in g.get("untrusted_cut", [])}   # their request parsers too
        self.shared = collections.Counter(n[1] for n in self.nodes)

    def label(self, i):
        return self.nodes[i][1]

    def name(self, i):
        """The label, with master path:line when other functions share it."""
        n = self.nodes[i]
        return f"{n[1]} ({n[2]}:{n[3]})" if self.shared[n[1]] > 1 else n[1]

    def short(self, i):
        return short(self.nodes[i][1])

    def find(self, name, path=None):
        """Nodes whose qualified name ends with `name`, optionally in `path`; else
        nodes whose label is the tail of `name` (labels of code under `using
        namespace` lack the namespace), class::name at least."""
        want = scope(name)
        nodes = [(i, scope(n[1])) for i, n in enumerate(self.nodes) if not path or n[2] == path]
        out = [i for i, h in nodes if h[-len(want):] == want]
        return out or [i for i, h in nodes if len(h) >= 2 and want[-len(h):] == h]

    def back(self, target, skip=(), cut=()):
        """Reverse BFS: hops to `target` and the next node towards it, for every
        ancestor, not passing through `skip` or along an edge in `cut`."""
        dist, nxt, q = {target: 0}, {}, collections.deque([target])
        while q:
            x = q.popleft()
            for p in self.pred[x]:
                if p not in dist and p not in skip and (p, x) not in cut:
                    dist[p], nxt[p] = dist[x] + 1, x
                    q.append(p)
        return dist, nxt

    def walk(self, start, nxt):
        path = [start]
        while path[-1] in nxt:
            path.append(nxt[path[-1]])
        return path

    def fmt(self, path):
        parts = [f"`{self.name(path[0])}`"]
        for a, b in zip(path, path[1:]):
            parts.append(f"-({self.succ[a][b]})-> `{self.name(b)}`")
        flags = []
        hops = [self.succ[a][b] for a, b in zip(path, path[1:])]
        if any(h in INFERRED for h in hops):
            flags.append("inferred hops")
        if any(CONDITIONAL.search(strip_targs(self.label(x))) for x in path[1:]):
            flags.append("conditional")
        return " ".join(parts) + (f"  *[{', '.join(flags)}]*" if flags else "")

    def section(self, i):
        """Markdown lines for one node: entrypoint counts, shortest paths, direct callers."""
        out = [f"Graph node: `{self.label(i)}` (master {self.nodes[i][2]}:{self.nodes[i][3]})"]
        full, untrusted = self.back(i), self.back(i, self.gate, self.cut)
        via = {e: untrusted if self.entry[e][0] == "untrusted_external" else full for e in self.entry}
        eps = sorted((via[e][0][e], self.label(e), e) for e in self.entry if e in via[e][0] and e != i)
        count = collections.Counter(self.entry[e][0] for _, _, e in eps)
        if i in self.entry:
            out.append(f"It is itself an entrypoint ({TRUST.get(self.entry[i][0], self.entry[i][0])}: {self.entry[i][1]}).")
        out.append("Reached from " + ", ".join(f"{count[t]} {TRUST[t]}" for t in TRUST)
                   + " entrypoint(s).")
        for trust, cap in PATHS.items():
            shown, labels = [], set()
            for x in eps:
                if self.entry[x[2]][0] == trust and x[1] not in labels and len(shown) < cap:
                    shown.append(x); labels.add(x[1])
            if shown:
                out.append(f"Shortest from {TRUST[trust]} entrypoints:")
                for d, _, e in shown:
                    out.append(f"- {self.entry[e][1]}, {d} hop(s): {self.fmt(self.walk(e, via[e][1]))}")
        callers = sorted(self.pred[i].items(), key=lambda kv: self.label(kv[0]))
        if callers:
            more = f" ({len(callers) - MAX_CALLERS} more)" if len(callers) > MAX_CALLERS else ""
            out.append("Direct callers: " + ", ".join(
                f"`{self.name(c)}` ({o})" for c, o in callers[:MAX_CALLERS]) + more)
        else:
            out.append("No callers in the graph.")
        return out

    def shortest(self, srcs, dsts, skip=(), cut=()):
        prev, q = {s: None for s in srcs}, collections.deque(srcs)
        while q:
            x = q.popleft()
            if x in dsts:
                path = [x]
                while prev[path[-1]] is not None:
                    path.append(prev[path[-1]])
                return path[::-1]
            for y in self.succ[x]:
                if y not in prev and (y not in skip or y in dsts) and (x, y) not in cut:
                    prev[y] = x
                    q.append(y)
        return None


OPERATOR = re.compile(r"\boperator\s*(\(\)|\[\]|->\*?|<=>|<<=?|>>=?|&&|\|\||\+\+|--|[-+*/%^&|~!=<>,]=?)")


def norm(n):
    """ctags writes `operator ()`, the graph `operator()`."""
    return OPERATOR.sub(lambda m: "operator" + m.group(1), n)


def strip_targs(n):
    n, out, depth, i = norm(n), "", 0, 0
    while i < len(n):
        m = OPERATOR.match(n, i)
        if m and (i == 0 or not (n[i - 1].isalnum() or n[i - 1] == "_")):
            if depth == 0:
                out += m.group(0)
            i = m.end()
            continue
        ch = n[i]
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif depth == 0:
            out += ch
        i += 1
    return out


def scope(n):
    """Name components, without template arguments or anonymous namespaces."""
    return [c.strip() for c in strip_targs(n).split("::")
            if c.strip() and c != "(anonymous)" and not c.startswith("__anon")]


def short(n):
    return strip_targs(n).split("::")[-1].strip()


def graph_path(root):
    try:
        p = subprocess.run(["git", "-C", root, "rev-parse", "--git-path", GRAPH],
                           capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return os.path.join(root, p)


def graph_of(root):
    p = graph_path(root)
    return Graph(p) if p and os.path.isfile(p) else None


def header(g):
    return f"Call graph of upstream master {g.commit[:12]}, built {g.built}."


def base_lines(root, rng):
    """{path: [(new start, new count, old start, old count)]} hunks of `git diff rng`."""
    out, path = {}, None
    diff = subprocess.run(["git", "--no-pager", "diff", "-U0", "--no-ext-diff", "--no-textconv",
                           *rng, "--", "src", "contrib"],
                          cwd=root, capture_output=True, text=True).stdout
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@") and path:
            m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if m:
                a, b, c, d = (int(x) if x is not None else 1 for x in m.groups())
                out.setdefault(path, []).append((c, d, a, b))
    return out


def to_graph(root, base, commit):
    """Line maps head -> merge-base -> the graph's commit (or `base`, when the
    commit is not in this clone: the graph is at most a day older)."""
    git = lambda *a: subprocess.run(["git", *a], cwd=root, capture_output=True, text=True)
    mb = git("merge-base", base, "HEAD").stdout.strip()
    tip = commit if git("cat-file", "-e", commit + "^{commit}").returncode == 0 else base
    head = base_lines(root, [f"{base}...HEAD"])
    ahead = {p: [(a, b, c, d) for c, d, a, b in h] for p, h in base_lines(root, [mb, tip]).items()} if mb else {}
    return head, lambda path, line: to_base(ahead.get(path, []), to_base(head.get(path, []), line))


def to_base(hunks, line):
    """A head line number on the base side: shifted by every hunk before it,
    or the start of the hunk it is in."""
    shift = 0
    for c, d, a, b in hunks:
        if (c + d <= line) if d else (c < line):
            shift += b - d
        elif d and c <= line:
            return a
    return line + shift


def match(g, name, qual, path, line):
    """The master node for a function at master line `line` of `path`, and a
    caveat when the match is not certain. Same file and short name; then the
    same scope, else the same innermost scope, else a nearby node whose scope
    lacks components (trailmark drops some). Overloads by nearest line."""
    want = scope(qual)
    cands = [i for i, n in enumerate(g.nodes) if n[2] == path and g.short(i) == short(name)]
    for tier, ok in enumerate((
            lambda i, h: h[-len(want):] == want,
            lambda i, h: len(want) > 1 and len(h) > 1 and h[-2] == want[-2],
            lambda i, h: set(h[:-1]) <= set(want[:-1]) and abs(g.nodes[i][3] - line) <= 10)):
        hit = [i for i in cands if ok(i, scope(g.label(i)))]
        if not hit:
            continue
        i = min(hit, key=lambda i: abs(g.nodes[i][3] - line))
        if tier:
            return i, "Matched by file and name; the graph's scope differs, so confirm it is this function."
        return i, nearness(g, hit, i, line)
    return None, None


def nearness(g, hit, i, line):
    """A caveat unless `i` is the only candidate within 3 lines of `line` (a
    template header can put the name 1-3 lines down)."""
    near = [h for h in hit if abs(g.nodes[h][3] - line) <= 3]
    if i not in near:
        return (f"This function maps to master line {line}, but the nearest graph node with "
                f"this name is at line {g.nodes[i][3]}: this overload may be missing from the "
                "graph, so confirm it is this function.")
    if len(near) > 1:
        return (f"{len(near)} overloads sit within 3 lines of master line {line}, where this "
                f"function maps to ({', '.join(str(g.nodes[h][3]) for h in near)}); confirm it is this one.")
    return None


def added(hunks, start, end):
    """Every line of head start..end is in a hunk that replaced nothing."""
    return any(b == 0 and c <= start and end < c + d for c, d, a, b in hunks)


def cmd_pr(root, base):
    print("# Reachability of the functions this pull request changes\n")
    print("Written by the harness before the review.", end=" ")
    g = graph_of(root)
    if g is None:
        print("No call graph in this run, so nothing was computed.")
        print("Use PR_CALLERS.md and `rtool callers`.")
        return
    print(header(g))
    target = os.environ.get("PR_BASE_REF", "master")
    if target != "master":
        print(f"\nThis pull request targets `{target}`, not master: the graph may not match its code.")
    print("\n" + HOW + "\n")
    spec = importlib.util.spec_from_file_location(
        "callers", os.path.join(os.path.dirname(os.path.realpath(__file__)), "callers.py"))
    callers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(callers)
    if not os.path.isfile(os.path.join(root, "tags")):
        print("No symbol index in this run, so the changed functions are unknown.")
        return
    fns = callers.functions(root, callers.changed_lines(root, base))
    if not fns:
        print("No changed function definitions in src or contrib.")
        return
    # ctags also lists each definition by its qualified name, with no end line.
    best = {}
    for fn in fns:
        k = (short(fn[0]), fn[2], fn[3])
        if k not in best or "::" in best[k][0]:
            best[k] = fn
    fns = sorted(best.values(), key=lambda t: (t[2], t[3]))
    if len(fns) > MAX_FUNCS:
        print(f"{len(fns)} changed functions; the first {MAX_FUNCS} by path are listed.\n")
    hunks, mapped = to_graph(root, base, g.commit)
    done = set()
    for name, qual, path, start, end in fns[:MAX_FUNCS]:
        print(f"## `{qual}` -- {path}:{start}-{end}\n")
        if added(hunks.get(path, []), start, end):
            print("Added by this pull request, so not in the master graph. Inconclusive;")
            print("read its callers in the source.\n")
            continue
        i, caveat = match(g, name, qual, path, mapped(path, start))
        if i is None:
            print("Not in the master graph under this name and scope: added or renamed by")
            print("this pull request, or not built on Linux. Inconclusive; read its callers")
            print("in the source.\n")
            continue
        if caveat:
            print(caveat)
        if i in done:
            print(f"Same graph node as above (`{g.name(i)}`).\n")
            continue
        done.add(i)
        print("\n".join(g.section(i)) + "\n")


def cmd_fn(root, name, path=None):
    g = graph_of(root)
    if g is None:
        print("no call graph in this run; use rtool callers")
        return 0
    print(f"# {header(g)} A path is a lead; no path proves nothing.")
    line = None
    if path and re.fullmatch(r".+:\d+", path):
        path, line = path.rsplit(":", 1)
    found = g.find(name, path and os.path.normpath(path))
    if not found:
        print(f"# no function named {name} in the master graph; a miss is inconclusive")
        return 0
    if line:
        # A master line, as this tool and PR_REACH.md print them.
        line = int(line)
        pick = min(found, key=lambda i: abs(g.nodes[i][3] - line))
        caveat = nearness(g, found, pick, line)
        if caveat:
            print("# " + caveat)
        found = [pick]
    if len(found) > 5:
        print(f"# {len(found)} matches; qualify the name, or give path:line to pick one:")
        for i in found[:40]:
            print(f"  {g.label(i)}  {g.nodes[i][2]}:{g.nodes[i][3]}")
        return 0
    for i in found:
        print(f"\n## {g.label(i)}  {g.nodes[i][2]}:{g.nodes[i][3]}")
        print("\n".join(g.section(i)))
    return 0


def cmd_path(root, a, b):
    g = graph_of(root)
    if g is None:
        print("no call graph in this run")
        return 0
    A, B = g.find(a), set(g.find(b))
    if not A or not B:
        print(f"# not in the master graph: {a if not A else b}; inconclusive")
        return 0
    print(f"# {header(g)}")
    p = g.shortest(A, B, g.gate, g.cut)
    if p:
        print(g.fmt(p))
        return 0
    p = g.shortest(A, B)
    if p:
        print("# only through the wallet RPC or a daemon RPC method restricted mode refuses,")
        print("# both semi-trusted: not a path for an untrusted client")
        print(g.fmt(p))
        return 0
    print(f"# no path from {a} to {b} in the graph; inconclusive (see PR_REACH.md)")
    return 0


def main():
    if len(sys.argv) < 3:
        print(__doc__.strip())
        return 2
    cmd, root = sys.argv[1], sys.argv[2]
    if cmd == "pr":
        cmd_pr(root, sys.argv[3] if len(sys.argv) > 3 else "origin/base")
        return 0
    if cmd == "fn" and 4 <= len(sys.argv) <= 5:
        return cmd_fn(root, *sys.argv[3:])
    if cmd == "path" and len(sys.argv) == 5:
        return cmd_path(root, sys.argv[3], sys.argv[4])
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 -- context only, never fatal
        print(f"\nReachability incomplete: {exc}")
