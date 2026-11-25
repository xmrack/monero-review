#!/usr/bin/env python3
"""Reachability from the call graph of upstream master (callgraph/, callgraph.json).

  reach.py pr <checkout> [base-ref]      PR_REACH.md on stdout: every function the
                                         pull request changes, the entrypoints that
                                         reach it and their shortest paths
  reach.py fn <checkout> <function> [path]
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
import sys

MAX_FUNCS = 60
PATHS = {"untrusted_external": 4, "semi_trusted_external": 3}
MAX_CALLERS = 15
INFERRED = {"virtual", "template_virtual", "template_argument", "template_enclosing_class",
            "reference", "reference_instantiation", "lambda", "function_table"}
CONDITIONAL = re.compile(r"(release_protocol|anvoke_handler::cancel|miner::start|miner::worker_thread)$")
TRUST = {"untrusted_external": "untrusted", "semi_trusted_external": "semi-trusted",
         "trusted_internal": "trusted-internal"}

HOW = """How to read this:
- A path is a lead, to confirm in the source at this pull request's head.
  `gcc` hops are calls the compiler made; `gcc_instantiation` is a call made
  by a template instantiated from that caller; `gcc_bridged` passes through
  std or boost; `trailmark` is trailmark's own parse. `virtual`, `reference`, `lambda`, `template_*` and
  `function_table` hops are inferred from the class hierarchy or from where a
  callback is registered.
- No path, or a function missing from the graph, proves nothing. The graph
  is of master, so calls this pull request adds are absent, and it covers one
  Linux build. asio handlers hang off the code that registers them, not off
  `io_context::run()`.
- Paths marked *conditional* pass through connection teardown
  (`release_protocol`, `anvoke_handler::cancel`) or the miner thread. They
  are real, but a finding that rests on one must say so.
- Dispatch is not tracked per object: the daemon and wallet RPC servers share
  one HTTP handler, so either can appear to reach the other's handlers."""


class Graph:
    def __init__(self, path):
        g = json.load(open(path))
        if g.get("format") != "monero-review-callgraph/1":
            raise ValueError("unknown call graph format")
        self.commit, self.built = g["commit"], g["built"]
        self.nodes = g["nodes"]                  # [id, label, path, start, end]
        self.origins = g["origins"]
        self.pred = collections.defaultdict(dict)
        self.succ = collections.defaultdict(dict)
        for a, b, o in g["edges"]:
            self.pred[b][a] = self.origins[o]
            self.succ[a][b] = self.origins[o]
        self.entry = {e: (t, d) for e, t, d in g["entrypoints"]}

    def label(self, i):
        return self.nodes[i][1]

    def short(self, i):
        return short(self.nodes[i][1])

    def find(self, name, path=None):
        """Nodes whose qualified name ends with `name`, optionally in `path`."""
        want = strip_targs(name)
        out = []
        for i, (_, lab, p, _, _) in enumerate(self.nodes):
            if path and p != path:
                continue
            q = strip_targs(lab)
            if q == want or q.endswith("::" + want):
                out.append(i)
        return out

    def back(self, target):
        """Reverse BFS: hops to `target` and the next node towards it, for every ancestor."""
        dist, nxt, q = {target: 0}, {}, collections.deque([target])
        while q:
            x = q.popleft()
            for p in self.pred[x]:
                if p not in dist:
                    dist[p], nxt[p] = dist[x] + 1, x
                    q.append(p)
        return dist, nxt

    def walk(self, start, nxt):
        path = [start]
        while path[-1] in nxt:
            path.append(nxt[path[-1]])
        return path

    def fmt(self, path):
        parts = [f"`{self.label(path[0])}`"]
        for a, b in zip(path, path[1:]):
            parts.append(f"-({self.succ[a][b]})-> `{self.label(b)}`")
        flags = []
        hops = [self.succ[a][b] for a, b in zip(path, path[1:])]
        if any(h in INFERRED for h in hops):
            flags.append("inferred hops")
        if any(CONDITIONAL.search(self.label(x)) for x in path[1:-1]):
            flags.append("conditional")
        return " ".join(parts) + (f"  *[{', '.join(flags)}]*" if flags else "")

    def section(self, i):
        """Markdown lines for one node: entrypoint counts, shortest paths, direct callers."""
        out = [f"Graph node: `{self.label(i)}` (master {self.nodes[i][2]}:{self.nodes[i][3]})"]
        dist, nxt = self.back(i)
        eps = sorted((dist[e], self.label(e), e) for e in self.entry if e in dist)
        count = collections.Counter(self.entry[e][0] for _, _, e in eps)
        if i in self.entry:
            out.append(f"It is itself an entrypoint ({TRUST.get(self.entry[i][0], self.entry[i][0])}: {self.entry[i][1]}).")
        out.append("Reached from " + ", ".join(f"{count[t]} {TRUST[t]}" for t in TRUST)
                   + " entrypoint(s).")
        for trust, cap in PATHS.items():
            shown, labels = [], set()
            for x in eps:
                if self.entry[x[2]][0] == trust and x[2] != i and x[1] not in labels and len(shown) < cap:
                    shown.append(x); labels.add(x[1])
            if shown:
                out.append(f"Shortest from {TRUST[trust]} entrypoints:")
                for d, _, e in shown:
                    out.append(f"- {self.entry[e][1]}, {d} hop(s): {self.fmt(self.walk(e, nxt))}")
        callers = sorted(self.pred[i].items(), key=lambda kv: self.label(kv[0]))
        if callers:
            more = f" ({len(callers) - MAX_CALLERS} more)" if len(callers) > MAX_CALLERS else ""
            out.append("Direct callers: " + ", ".join(
                f"`{self.label(c)}` ({o})" for c, o in callers[:MAX_CALLERS]) + more)
        else:
            out.append("No callers in the graph.")
        return out

    def shortest(self, srcs, dsts):
        prev, q = {s: None for s in srcs}, collections.deque(srcs)
        while q:
            x = q.popleft()
            if x in dsts:
                path = [x]
                while prev[path[-1]] is not None:
                    path.append(prev[path[-1]])
                return path[::-1]
            for y in self.succ[x]:
                if y not in prev:
                    prev[y] = x
                    q.append(y)
        return None


def strip_targs(n):
    out, depth = "", 0
    for ch in n:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif depth == 0:
            out += ch
    return out


def short(n):
    return strip_targs(n).split("::")[-1]


def graph_of(root):
    p = os.path.join(root, "callgraph.json")
    return Graph(p) if os.path.isfile(p) else None


def header(g):
    return f"Call graph of upstream master {g.commit[:12]}, built {g.built}."


def match(g, name, qual, path, start):
    """The master node for a function changed at path:start (head line numbers)."""
    cands = [i for i, n in enumerate(g.nodes) if n[2] == path and g.short(i) == name]
    if not cands:
        return None
    scoped = [i for i in cands if strip_targs(g.label(i)).endswith(strip_targs(qual))]
    cands = scoped or cands
    return min(cands, key=lambda i: abs(g.nodes[i][3] - start))


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
    if len(fns) > MAX_FUNCS:
        print(f"{len(fns)} changed functions; the first {MAX_FUNCS} by path are listed.\n")
    done, seen = set(), set()
    for name, qual, path, start, end in fns[:MAX_FUNCS]:
        name = short(name)                  # ctags also lists a definition by its qualified name
        if (name, path, start) in seen:
            continue
        seen.add((name, path, start))
        print(f"## `{qual}` -- {path}:{start}-{end}\n")
        i = match(g, name, qual, path, start)
        if i is None:
            print("Not in the master graph: added or renamed by this pull request, or not")
            print("built on Linux. Inconclusive; read its callers in the source.\n")
            continue
        if i in done:
            print(f"Same graph node as above (`{g.label(i)}`).\n")
            continue
        done.add(i)
        print("\n".join(g.section(i)) + "\n")


def cmd_fn(root, name, path=None):
    g = graph_of(root)
    if g is None:
        print("no call graph in this run (callgraph.json); use rtool callers")
        return 0
    print(f"# {header(g)} A path is a lead; no path proves nothing.")
    found = g.find(name, path)
    if not found:
        print(f"# no function named {name} in the master graph; a miss is inconclusive")
        return 0
    if len(found) > 5:
        print(f"# {len(found)} matches; qualify the name or add a path:")
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
        print("no call graph in this run (callgraph.json)")
        return 0
    A, B = g.find(a), set(g.find(b))
    if not A or not B:
        print(f"# not in the master graph: {a if not A else b}; inconclusive")
        return 0
    p = g.shortest(A, B)
    print(f"# {header(g)}")
    print(g.fmt(p) if p else f"# no path from {a} to {b} in the graph; inconclusive (see PR_REACH.md)")
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
