#!/usr/bin/env python3
"""Reachability from the call graph of upstream master (callgraph/, callgraph.json).

  reach.py pr <checkout> [base-ref]      PR_REACH.md on stdout: every function the
                                         pull request changes, the entrypoints that
                                         reach it and their shortest paths
  reach.py fn <checkout> <function> [path[:line]]   (line: as printed)
  reach.py path <checkout> <from> <to>
  reach.py head <checkout>               one line: the head graph's state

The graph is master's, built from GCC call-graph dumps and libclang and merged
into a trailmark snapshot. A path is a lead to confirm in the source; no path
proves nothing. Context only: any failure prints a note.

A graph of the pull request's head, built the same way from its code, may sit
beside master's. Its names and edges are the pull request's claims, so it only
adds leads: the calls the pull request adds, and entrypoints that reach a
function only at the head. Trust comes from master wherever a node is in both.
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
HEAD_GRAPH = "monero-review-callgraph-head.json"
HEAD_MAX = 30 << 20
LABEL = re.compile(r"[ -_a-~]{1,400}")    # printable ASCII, no backtick
QUALIFIER = re.compile(r"\b(?:namespace|class|struct|union|enum)\s+([A-Za-z_]\w*)|\b([A-Za-z_]\w*)\s*(?:<[^;{}]*?>)?\s*(?:::|\()")
HEAD_PART = re.compile(r"~?[A-Za-z_]\w*|\{lambda(#\d+)?\}|\(anonymous\)|"
                       r"operator(\(\)|\[\]|->\*?|<=>|<<=?|>>=?|&&|\|\||\+\+|--|[-+*/%^&|~!=<>,]=?)")
NODE_PATH = re.compile(r"(src|contrib)/[A-Za-z0-9_./+-]{1,300}")
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
  is of master, so calls this pull request adds are absent from it. The head
  graph, when there is one, is built from the pull request's own code: what
  it adds is a lead to confirm, what it lacks proves nothing. Both cover one
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
- A label shared by several functions (overloads) carries its `path:line`
  (master's; the head's in a section from the head graph); pass that to
  `rtool reach <fn> <path>:<line>`."""


class Graph:
    def __init__(self, path, side="master"):
        if side == "head" and os.path.getsize(path) > HEAD_MAX:
            raise Bad("too large")
        g = json.load(open(path))
        if g.get("format") != "monero-review-callgraph/1":
            raise ValueError("unknown call graph format")
        if side == "head":
            validate(g)
        self.side = side
        self.commit, self.built, self.rules = g["commit"], g["built"], g.get("rules")
        self.nodes = g["nodes"]                  # [id, label, path, start, end]
        for n in self.nodes:
            n[1] = n[1].replace("::::", "::(anonymous)::")
        self.origins = g["origins"]
        self.pred = collections.defaultdict(dict)
        self.succ = collections.defaultdict(dict)
        for a, b, o in g["edges"]:
            self.pred[b][a] = self.origins[o]
            self.succ[a][b] = self.origins[o]
        self.gate = {i for i, n in enumerate(self.nodes) if WALLET_GATE.search(strip_targs(n[1]))}
        self.rpc_map = {i for i, n in enumerate(self.nodes) if RPC_MAP.search(strip_targs(n[1]))}
        self.untrusted_cut = {tuple(x) for x in g.get("untrusted_cut", [])}   # their request parsers too
        self.set_entry({e: (t, d) for e, t, d in g["entrypoints"]}, self.untrusted_cut)
        self.shared = collections.Counter(n[1] for n in self.nodes)

    def set_entry(self, entry, cut):
        self.entry = entry
        self.cut = {(m, e) for e, (t, d) in entry.items() if d == UNRESTRICTED
                    for m in self.rpc_map if e in self.succ[m]} | cut

    def label(self, i):
        return self.nodes[i][1]

    def name(self, i):
        """The label, with path:line when other functions share it."""
        n = self.nodes[i]
        return f"{n[1]} ({n[2]}:{n[3]})" if self.shared[n[1]] > 1 else n[1]

    def ref(self, i):
        return f"`{self.name(i)}`"

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
        parts = [self.ref(path[0])]
        for a, b in zip(path, path[1:]):
            parts.append(f"-({self.succ[a][b]})-> {self.ref(b)}")
        flags = []
        hops = [self.succ[a][b] for a, b in zip(path, path[1:])]
        if any(h in INFERRED for h in hops):
            flags.append("inferred hops")
        if any(CONDITIONAL.search(strip_targs(self.label(x))) for x in path[1:]):
            flags.append("conditional")
        return " ".join(parts) + (f"  *[{', '.join(flags)}]*" if flags else "")

    def reached(self, i):
        """[(hops, label, entrypoint)] for the entrypoints that reach `i`, and the
        BFS each was found by."""
        full, untrusted = self.back(i), self.back(i, self.gate, self.cut)
        via = {e: untrusted if self.entry[e][0] == "untrusted_external" else full for e in self.entry}
        return sorted((via[e][0][e], self.label(e), e) for e in self.entry if e in via[e][0] and e != i), via

    def paths(self, eps, via):
        out = []
        for trust, cap in PATHS.items():
            shown, labels = [], set()
            for x in eps:
                if self.entry[x[2]][0] == trust and x[1] not in labels and len(shown) < cap:
                    shown.append(x); labels.add(x[1])
            if shown:
                out.append(f"Shortest from {TRUST[trust]} entrypoints:")
                for d, _, e in shown:
                    out.append(f"- {self.entry[e][1]}, {d} hop(s): {self.fmt(self.walk(e, via[e][1]))}")
        return out

    def section(self, i):
        """Markdown lines for one node: entrypoint counts, shortest paths, direct callers."""
        out = [f"Graph node: `{self.label(i)}` ({self.side} {self.nodes[i][2]}:{self.nodes[i][3]})"]
        eps, via = self.reached(i)
        count = collections.Counter(self.entry[e][0] for _, _, e in eps)
        if i in self.entry:
            out.append(f"It is itself an entrypoint ({TRUST.get(self.entry[i][0], self.entry[i][0])}: {self.entry[i][1]}).")
        out.append("Reached from " + ", ".join(f"{count[t]} {TRUST[t]}" for t in TRUST)
                   + " entrypoint(s).")
        out += self.paths(eps, via)
        callers = sorted(self.pred[i].items(), key=lambda kv: self.label(kv[0]))
        if callers:
            more = f" ({len(callers) - MAX_CALLERS} more)" if len(callers) > MAX_CALLERS else ""
            out.append("Direct callers: " + ", ".join(
                f"{self.ref(c)} ({o})" for c, o in callers[:MAX_CALLERS]) + more)
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


CERTAIN = {"gcc", "gcc_instantiation"}
ORIGINS = CERTAIN | INFERRED


class Bad(Exception):
    pass


def validate(g):
    """A head graph comes out of a build of the pull request's code, which can
    write anything there: check every field that is printed or indexed by."""
    def need(ok):
        if not ok:
            raise Bad("malformed")
    need(isinstance(g.get("commit"), str) and re.fullmatch(r"[0-9a-f]{40}", g["commit"]))
    need(isinstance(g.get("built"), str) and LABEL.fullmatch(g["built"]))
    need(isinstance(g.get("rules"), str) and re.fullmatch(r"[0-9a-f]{16}", g["rules"]))
    o = g.get("origins")
    need(isinstance(o, list) and o and all(isinstance(x, str) and x in ORIGINS for x in o))
    nodes = g.get("nodes")
    need(isinstance(nodes, list) and 0 < len(nodes) <= 200000)
    for n in nodes:
        need(isinstance(n, list) and len(n) == 5 and isinstance(n[0], str)
             and isinstance(n[1], str) and LABEL.fullmatch(n[1])
             and isinstance(n[2], str) and NODE_PATH.fullmatch(n[2]) and ".." not in n[2]
             and type(n[3]) is int and type(n[4]) is int and 0 < n[3] <= n[4] < 10**7)
    idx = lambda x: type(x) is int and 0 <= x < len(nodes)
    for key, size in (("edges", 3), ("entrypoints", 3), ("untrusted_cut", 2)):
        need(isinstance(g.get(key, []), list) and len(g.get(key, [])) <= 10**6)
        for e in g.get(key, []):
            need(isinstance(e, list) and len(e) == size and idx(e[0]))
            if key == "edges":
                need(idx(e[1]) and type(e[2]) is int and 0 <= e[2] < len(o))
            elif key == "entrypoints":
                need(e[1] in TRUST and isinstance(e[2], str) and LABEL.fullmatch(e[2]))
            else:
                need(idx(e[1]))


class Head:
    """The head graph `h` beside master's `m`. A head node is master's when both
    have its label in its file (overloads paired by nearest mapped line); trust
    is master's for those and the head graph's only for the others. Removed
    calls and lower counts are never reported as such."""
    def __init__(self, root, m, path, mapped, moved):
        h = self.h = Graph(path, "head")
        if len(h.nodes) > 2 * len(m.nodes) or sum(map(len, h.succ.values())) > 3 * sum(map(len, m.succ.values())):
            raise Bad("too large")
        self.m, self.root, self.moved, self.files = m, root, moved, {}
        group = collections.defaultdict(lambda: ([], []))
        for i, n in enumerate(m.nodes):
            group[(n[1], n[2])][1].append(i)
        for i, n in enumerate(h.nodes):
            if (n[1], n[2]) in group:
                group[(n[1], n[2])][0].append(i)
        self.to_m = {}
        for hs, ms in group.values():
            used = set()
            for _, a, b in sorted((abs(mapped(h.nodes[a][2], h.nodes[a][3]) - m.nodes[b][3]), a, b)
                                  for a in hs for b in ms):
                if a not in self.to_m and b not in used:
                    self.to_m[a] = b
                    used.add(b)
        self.from_m = {b: a for a, b in self.to_m.items()}
        # A name only the head graph has is printed only as printable() allows,
        # and an entrypoint's description only if master uses it.
        self.vocab = {c for n in m.nodes for c in scope(n[1])}
        for i, n in enumerate(h.nodes):
            if i not in self.to_m:
                name = self.printable(n)
                n[1] = name or (f"(a name not in the head source, {n[2]}:{n[3]})" if self.source(n[2])
                                else "(a name the head graph puts in no file of the checkout)")
        h.shared = collections.Counter(n[1] for n in h.nodes)
        descs = {d for t, d in m.entry.values()}
        entry = {}
        for i in range(len(h.nodes)):
            j = self.to_m.get(i)
            if j is None and i in h.entry:
                t, d = h.entry[i]
                entry[i] = (t, d if d in descs else "an entrypoint only the head graph has")
            elif j is not None and j in m.entry:
                entry[i] = m.entry[j]
        h.set_entry(entry, {(a, b) for a, b in h.untrusted_cut
                            if b not in self.to_m or (self.to_m.get(a), self.to_m[b]) in m.cut})
        self.partial = len(h.nodes) < 0.9 * len(m.nodes)

    def source(self, path):
        """(lines, the names it uses as a scope) of a file in the head checkout, or None."""
        if path not in self.files:
            f = os.path.realpath(os.path.join(self.root, path))
            try:
                ok = f.startswith(os.path.realpath(self.root) + os.sep)
                text = open(f, errors="replace").read() if ok else None
            except OSError:
                text = None
            self.files[path] = text and (text.split("\n"), {a or b for a, b in QUALIFIER.findall(text)})
        return self.files[path]

    def printable(self, n):
        """The name to print for a node only the head graph has, else None: no
        template arguments; every component an identifier, destructor, operator,
        lambda or anonymous namespace; the last a word within 3 lines of where
        the node starts in the head source; the rest scopes master's graph has,
        or names that file declares, qualifies with or calls."""
        src = self.source(n[2])
        if not src:
            return None
        lines, idents = src
        name = strip_targs(n[1])
        parts = name.split("::")
        if not all(HEAD_PART.fullmatch(p) for p in parts) or not all(
                p in self.vocab or p in idents or p[0] in "({" for p in parts[:-1]):
            return None
        last, near = parts[-1], "\n".join(lines[max(0, n[3] - 3):n[3] + 3])
        if last.startswith("{"):
            return name if "[" in near else None
        word = "operator" if last.startswith("operator") else last.lstrip("~")
        return name if re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", near) else None

    def intro(self):
        out = [f"Head graph: built the same way from this pull request's head {self.h.commit[:12]}, "
               "so its names and edges are the pull request's own code compiled and analysed: "
               "leads, never evidence. A name only the head graph has is shown without template "
               "arguments, and only if it is a plain C++ name found where the graph says it is "
               "defined; else its path:line. Trust is master's for every function in both graphs."]
        if self.moved:
            out.append(f"Master changed {len(self.moved)} file(s) under src and contrib since this "
                       "branch's merge-base, so a difference between the graphs can be master's; "
                       "the calls of a function master changed are not compared.")
        if self.partial:
            out.append(f"The head graph has {len(self.h.nodes)} functions to master's "
                       f"{len(self.m.nodes)} (part of the build failed?): calls it lacks are not listed.")
        return out

    def delta(self, hi, mi, path):
        """The calls of head node `hi` that master node `mi` lacks, and the reverse."""
        h, m = self.h, self.m
        n = m.nodes[mi]
        if any(a <= n[4] and n[3] < a + max(b, 1) for c, d, a, b in self.moved.get(path, [])):
            return ["Master changed this function since the branch point: calls not compared."]
        # Callees by node, so a call to a new overload counts.
        mine = {self.to_m.get(j) for j in h.succ[hi]}
        out = []
        add = sorted((o not in CERTAIN, h.label(j), j, o) for j, o in h.succ[hi].items()
                     if self.to_m.get(j) not in m.succ[mi])
        if add:
            more = f" ({len(add) - MAX_CALLERS} more)" if len(add) > MAX_CALLERS else ""
            out.append("Calls this pull request adds (head graph): " + ", ".join(
                f"{h.ref(j)} ({o})" for _, _, j, o in add[:MAX_CALLERS]) + more)
        gone = sorted((m.label(j), j) for j, o in m.succ[mi].items() if o in CERTAIN and j not in mine)
        if gone and not self.partial:
            more = f" ({len(gone) - MAX_CALLERS} more)" if len(gone) > MAX_CALLERS else ""
            out.append("Compiler calls in master the head graph lacks (removed, or missed by the "
                       "head build: the weakest lead): " + ", ".join(
                           m.ref(j) for _, j in gone[:MAX_CALLERS]) + more)
        return out

    def new_reach(self, hi, mi):
        """Entrypoints that reach head node `hi` but, at that trust, not master node `mi`."""
        h, m = self.h, self.m
        old = {(e, m.entry[e][0]) for _, _, e in m.reached(mi)[0]}
        eps, via = h.reached(hi)
        new = [x for x in eps if h.entry[x[2]][0] in PATHS
               and (self.to_m.get(x[2]), h.entry[x[2]][0]) not in old]
        if not new:
            return []
        count = collections.Counter(h.entry[e][0] for _, _, e in new)
        return ["Reached in the head graph only from " + ", ".join(
            f"{count[t]} {TRUST[t]}" for t in PATHS) + " entrypoint(s):"] + h.paths(new, via)


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
    commit is not in this clone: the graph is at most a day older), and the
    hunks between those two, {path: [(merge-base start, count, graph start, count)]}."""
    git = lambda *a: subprocess.run(["git", *a], cwd=root, capture_output=True, text=True)
    mb = git("merge-base", base, "HEAD").stdout.strip()
    tip = commit if git("cat-file", "-e", commit + "^{commit}").returncode == 0 else base
    head = base_lines(root, [f"{base}...HEAD"])
    ahead = {p: [(a, b, c, d) for c, d, a, b in h] for p, h in base_lines(root, [mb, tip]).items()} if mb else {}
    return head, lambda path, line: to_base(ahead.get(path, []), to_base(head.get(path, []), line)), ahead


def head_of(root, m, mapped, moved):
    """(Head or None, a sentence on the head graph)."""
    p = graph_path(root)
    p = p and os.path.join(os.path.dirname(p), HEAD_GRAPH)
    if not p or not os.path.isfile(p):
        return None, "No graph of this pull request's head in this run: none is built without C or C++ changes, or its build failed."
    try:
        head = Head(root, m, p, mapped, moved)
    except Bad as exc:
        return None, f"The graph of this pull request's head was not used: {exc}."
    except Exception:  # noqa: BLE001
        return None, "The graph of this pull request's head was not used: malformed."
    sha = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if head.h.commit != sha:
        return None, "The graph of this pull request's head was built for another commit, so it was not used."
    if head.h.rules != m.rules:
        return None, "The graph of this pull request's head was built by other rules than master's, so it was not used."
    return head, None


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
    hunks, mapped, moved = to_graph(root, base, g.commit)
    head, why = head_of(root, g, mapped, moved)
    print("\n".join(head.intro()) + "\n" if head else why + "\n")
    done = set()
    for name, qual, path, start, end in fns[:MAX_FUNCS]:
        print(f"## `{qual}` -- {path}:{start}-{end}\n")
        hi, hcaveat = match(head.h, name, qual, path, start) if head else (None, None)
        new = added(hunks.get(path, []), start, end)
        i, caveat = (None, None) if new else match(g, name, qual, path, mapped(path, start))
        if i is None:
            if new:
                print("Added by this pull request, so not in the master graph.", end=" ")
            else:
                print("Not in the master graph under this name and scope: added or renamed by")
                print("this pull request, or not built on Linux.", end=" ")
            if hi is None:
                print("Inconclusive;\nread its callers in the source.\n")
            else:
                print("From the head graph (leads only):\n")
                if hcaveat:
                    print(hcaveat.replace("master line", "head line"))
                print("\n".join(head.h.section(hi)) + "\n")
            continue
        if caveat:
            print(caveat)
        if i in done:
            print(f"Same graph node as above (`{g.name(i)}`).\n")
            continue
        done.add(i)
        print("\n".join(g.section(i)))
        if head and hi is None:
            print("Not found in the head graph.")
        elif head and head.to_m.get(hi) != i:
            print("The head graph's node for it is not this master node, so the two are not compared.")
        elif head:
            print("\n".join(head.delta(hi, i, path) + head.new_reach(hi, i)))
        print()


def head_for(root, g):
    hunks, mapped, moved = to_graph(root, os.environ.get("REACH_BASE", "origin/base"), g.commit)
    return head_of(root, g, mapped, moved)


def pick(g, name, path, line):
    """Nodes named `name` (in `path`, nearest `line`), and a caveat."""
    found = g.find(name, path)
    if not found or line is None:
        return found, None
    i = min(found, key=lambda i: abs(g.nodes[i][3] - line))
    return [i], nearness(g, found, i, line)


def cmd_fn(root, name, path=None):
    g = graph_of(root)
    if g is None:
        print("no call graph in this run; use rtool callers")
        return 0
    print(f"# {header(g)} A path is a lead; no path proves nothing.")
    line = None
    if path and re.fullmatch(r".+:\d+", path):
        path, line = path.rsplit(":", 1)
        line = int(line)
    path = path and os.path.normpath(path)
    found, caveat = pick(g, name, path, line)
    side, head = g, None
    if not found:
        head = head_for(root, g)[0]
        if head:
            # Only in the head graph: the line, if any, is the head's, as printed.
            found, caveat = pick(head.h, name, path, line)
            side = head.h
            caveat = caveat and caveat.replace("master line", "head line")
            if found:
                print("# not in the master graph; from the graph of this pull request's head, "
                      "built from its own code: leads only")
    if not found:
        print(f"# no function named {name} in the {'master or head graph' if head else 'master graph'}; "
              "a miss is inconclusive")
        return 0
    if caveat:
        print("# " + caveat)
    if len(found) > 5:
        print(f"# {len(found)} matches; qualify the name, or give path:line to pick one:")
        for i in found[:40]:
            print(f"  {side.label(i)}  {side.nodes[i][2]}:{side.nodes[i][3]}")
        return 0
    for i in found:
        print(f"\n## {side.label(i)}  {side.side} {side.nodes[i][2]}:{side.nodes[i][3]}")
        print("\n".join(side.section(i)))
    if side is g:
        # Master's answer first: the head graph can be slow to load.
        sys.stdout.flush()
        head = head_for(root, g)[0]
        for i in found:
            lines = head.new_reach(head.from_m[i], i) if head and i in head.from_m else []
            if lines:
                print(f"\n## {g.label(i)}: in the graph of this pull request's head (leads only)")
                print("\n".join(lines))
    return 0


def route(g, A, B):
    """The shortest path an untrusted client could take, else any, with a note."""
    p = g.shortest(A, B, g.gate, g.cut)
    if p:
        return p, []
    p = g.shortest(A, B)
    return p, ["# only through the wallet RPC or a daemon RPC method restricted mode refuses,",
               "# both semi-trusted: not a path for an untrusted client"]


def cmd_path(root, a, b):
    g = graph_of(root)
    if g is None:
        print("no call graph in this run")
        return 0
    print(f"# {header(g)}")
    A, B = g.find(a), set(g.find(b))
    p, note = route(g, A, B) if A and B else (None, [])
    if p:
        print("\n".join(note + [g.fmt(p)]))
        return 0
    head = head_for(root, g)[0]
    if head:
        HA, HB = head.h.find(a), set(head.h.find(b))
        q, note = route(head.h, HA, HB) if HA and HB else (None, [])
        if q:
            print("# none in the master graph; in the graph of this pull request's head, "
                  "built from its own code: a lead to confirm")
            print("\n".join(note + [head.h.fmt(q)]))
            return 0
    if not A or not B:
        print(f"# not in the master graph: {a if not A else b}; inconclusive")
    else:
        print(f"# no path from {a} to {b} in the graph; inconclusive (see PR_REACH.md)")
    return 0


def cmd_head(root):
    g = graph_of(root)
    if g is None:
        print("no master call graph, so the head graph is not used")
        return 0
    head, why = head_for(root, g)
    if head:
        print(f"head {head.h.commit[:12]}, {len(head.h.nodes)} functions, compared with master's in "
              "PR_REACH.md and by rtool reach and rtool path; built from the pull request's code, so leads only")
    else:
        print(why.rstrip("."))
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
    if cmd == "head" and len(sys.argv) == 3:
        return cmd_head(root)
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 -- context only, never fatal
        print(f"\nReachability incomplete: {exc}")
