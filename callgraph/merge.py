# Inject compiler-derived call edges into a trailmark snapshot.
#   GCC -fcallgraph-info (.ci): direct calls, incl. template instantiations and macro expansions.
#     Paths through functions with no trailmark node (std/boost/external/unextracted) are bridged.
#   libclang (cg/*.json): virtual calls -> declared method + all overriders,
#     address-taken functions (callbacks) and lambdas -> edge from the enclosing function.
# usage: merge.py <monero root> <build dir> <tree> <clang dir> <snapshot in> <snapshot out> <report dir>
import bisect, collections, glob, json, os, re, sys
import rustworkx as rx

ROOT, BUILD, TREE, CG, SNAP_IN, SNAP_OUT, OUT = sys.argv[1:8]
ROOT, TREE = os.path.abspath(ROOT), os.path.abspath(TREE)
os.makedirs(OUT, exist_ok=True)
stats = collections.Counter()

def to_tree(path):
    if not path: return None
    p = os.path.normpath(path)
    for pre, dst in ((ROOT + "/src/", TREE + "/src/"), (ROOT + "/contrib/epee/", TREE + "/epee/")):
        if p.startswith(pre):
            t = dst + p[len(pre):]
            return t + ".hpp" if t.endswith(".inl") else t
    return None

snap = json.load(open(SNAP_IN))
G = snap["graph"]
funcs = {i: n for i, n in G["nodes"].items() if n["kind"] in ("function", "method")}
byfile = collections.defaultdict(list)
for i, n in funcs.items():
    l = n["location"]; byfile[l["file_path"]].append((l["start_line"], l["end_line"], i))

def locate(path, line):
    """Smallest trailmark function whose span contains line."""
    t = to_tree(path)
    if t is None: return None
    best = None
    for s, e, i in byfile.get(t, ()):
        if s <= line <= e and (best is None or e - s < best[0]):
            best = (e - s, i)
    return best[1] if best else None

def locate_extent(path, start, end):
    """Largest trailmark function lying inside [start, end]; else containment of start."""
    t = to_tree(path)
    if t is None: return None
    best = None
    for s, e, i in byfile.get(t, ()):
        if start - 1 <= s and e <= end + 1:
            d = abs(s - start) + abs(e - end)
            if best is None or d < best[0]: best = (d, i)
    return best[1] if best else locate(path, start)

def locate_named(path, lo, hi, name):
    """Trailmark function in [lo, hi] (or containing lo) whose base name matches; smallest span."""
    t = to_tree(path)
    if t is None or not name: return None
    best = None
    for s_, e_, i in byfile.get(t, ()):
        if (lo <= s_ <= hi or s_ <= lo <= e_):
            nm = re.split(r"::|\.", re.sub(r"@\d+_\d+$", "", funcs[i]["name"]))[-1]
            if nm == name or (name.startswith("~") and name[1:] == nm):
                if best is None or e_ - s_ < best[0]: best = (e_ - s_, i)
    return best[1] if best else None

# ---------- GCC call graph ----------
NODE = re.compile(r'^node: \{ title: "([^"]*)" label: "([^"]*)"( shape : ellipse)?')
EDGE = re.compile(r'^edge: \{ sourcename: "([^"]*)" targetname: "([^"]*)" label: "([^"]*)"')
LOC = re.compile(r'^(.*):(\d+):(\d+)$')

collided = set()
bare_defs = collections.defaultdict(set)
def gkey(title, tu):
    # defined nodes are "<tu>:<asm name>"; externals are "<asm name>".
    # A name defined at several distinct locations is internal linkage (C static, _ZL, anonymous
    # namespace) in several TUs: qualify it by TU so different functions are not merged.
    local = title.startswith(tu + ":")
    name = title[len(tu) + 1:] if local else title
    if "_GLOBAL__N" in name or (name in collided and (local or tu in bare_defs.get(name, ()))): return tu + ":" + name
    return name

def _prepass(files):
    locs = collections.defaultdict(set)
    for ci in files:
        tu = None
        with open(ci, errors="replace") as fh:
            for line in fh:
                if line.startswith("graph: { title:"): tu = line.split('"')[1]; continue
                m = NODE.match(line)
                if m and not m.group(3):
                    # external-linkage definitions are titled by bare name (e.g. one `main` per program)
                    local = m.group(1).startswith(tu + ":")
                    name = m.group(1)[len(tu) + 1:] if local else m.group(1)
                    if not local: bare_defs[name].add(tu)
                    lm = LOC.match(m.group(2).split("\\n")[-1])
                    if lm: locs[name].add((os.path.normpath(lm.group(1)), lm.group(2)))
    return {k for k, v in locs.items() if len(v) > 1}

gdef = {}                       # key -> (file, line)  definition location
gedges = collections.defaultdict(set)   # key -> {(key, site_file, site_line)}
indirect_sites = []             # (caller key, file, line)
c_static = collections.defaultdict(set)
cifiles = glob.glob(os.path.join(BUILD, "**", "*.ci"), recursive=True)
collided |= _prepass(cifiles)
stats["internal_linkage_names_tu_qualified"] = len(collided)
for ci in cifiles:
    tu = None
    with open(ci, errors="replace") as fh:
        for line in fh:
            if line.startswith("graph: { title:"):
                tu = line.split('"')[1]; continue
            m = NODE.match(line)
            if m:
                title, label, ext = m.groups()
                if ext: continue
                k = gkey(title, tu)
                lm = LOC.match(label.split("\\n")[-1])
                if lm and k not in gdef:
                    gdef[k] = (os.path.normpath(lm.group(1)), int(lm.group(2)))
                continue
            m = EDGE.match(line)
            if m:
                s, t, site = m.groups()
                sk = gkey(s, tu)
                lm = LOC.match(site)
                sf, sl = (os.path.normpath(lm.group(1)), int(lm.group(2))) if lm else (None, 0)
                if t == "__indirect_call":
                    indirect_sites.append((sk, sf, sl)); continue
                tk = gkey(t, tu)
                if tk in collided: stats["ambiguous_external_targets_dropped"] += 1; continue
                gedges[sk].add((tk, sf, sl))
# GCC defines only the base-object ctor/dtor (C2/D2) when the complete-object one (C1/D1) is an
# alias of it, but call sites name C1/D1: retarget to whichever variant is defined.
CTOR = re.compile(r"(?<=[0-9A-Za-z_])([CD])([0-2])(?=[EIB])")
def ctor_alias(k):
    for m in CTOR.finditer(k):
        for v in ("2", "1", "0") if m.group(1) == "D" else ("2", "1"):
            if v == m.group(2): continue
            a = k[:m.start(2)] + v + k[m.end(2):]
            if a in gdef: return a
    return None
for sk in list(gedges):
    fixed = set()
    for tk, sf, sl in gedges[sk]:
        if tk not in gdef:
            a = ctor_alias(tk)
            if a: tk = a; stats["ctor_dtor_alias_retargeted"] += 1
        fixed.add((tk, sf, sl))
    gedges[sk] = fixed
stats["ci_files"] = len(cifiles); stats["gcc_defined_functions"] = len(gdef)
stats["gcc_call_edges"] = sum(len(v) for v in gedges.values())
stats["gcc_indirect_sites"] = len(indirect_sites)

import subprocess
OPS = [("operator<<=", "OPshlassign"), ("operator>>=", "OPshrassign"), ("operator<=>", "OPspaceship"),
       ("operator<<", "OPshl"), ("operator>>", "OPshr"), ("operator<=", "OPle"), ("operator>=", "OPge"),
       ("operator<", "OPlt"), ("operator>", "OPgt"), ("operator->", "OParrow"), ("operator()", "OPcall")]
def short_name(d):
    """Qualified name without return type, template arguments or parameters ('$lambda' for lambdas)."""
    d = re.sub(r"\[abi:[^\]]*\]", "", d)
    for a, b in OPS: d = d.replace(a, b)
    out, depth = "", 0
    for ch in d:                           # drop template arguments and parenthesised groups
        if ch in "<(": depth += 1
        elif ch in ">)": depth = max(0, depth - 1)
        elif depth == 0: out += ch
    out = re.sub(r"\s+(const|volatile|&|&&|noexcept)\s*$", "", out.strip())
    tok = out.split(" ")[-1] if out else d
    parts = tok.split("::")
    if "{lambda" in parts[-1] or (len(parts) > 1 and "{lambda" in parts[-2] and parts[-1].startswith(("operator", "OP"))):
        return "$lambda"
    for a, b in OPS: tok = tok.replace(b, a)
    return tok
def base(n):
    n = re.sub(r"@\d+_\d+$", "", n)
    return re.split(r"::|\.", n)[-1]
in_tree = [k for k, (f, l) in gdef.items() if to_tree(f)]
dem = dict(zip(in_tree, subprocess.run(["c++filt", "-p"], input="\n".join(k.split(":")[-1] for k in in_tree),
                                       capture_output=True, text=True).stdout.split("\n")))
def names_match(a, b):
    if a == b: return True
    if a.startswith("~") and a[1:] == b: return True          # trailmark names destructors by class
    if a.endswith("_" + b) or b.endswith("_" + a): return True  # C macro renames (blake2b_init)
    return False
def agrees(k, node_id):
    """Demangled GCC name vs the trailmark node it landed on."""
    sn = short_name(dem.get(k, k)); nn = funcs[node_id]["name"]
    if sn == "$lambda" or "$lambda" in nn: return sn == "$lambda" and "$lambda" in nn
    return names_match(base(sn), base(nn))
gmap = {}
agree = collections.Counter(); disagree_samples = []
for k, (f, l) in gdef.items():
    n = locate(f, l)
    if not n: continue
    if agrees(k, n): gmap[k] = n; agree["agree"] += 1
    else:
        alt = locate_named(f, l, l, base(short_name(dem.get(k, k))))
        if alt: gmap[k] = alt; agree["agree_after_name_lookup"] += 1; continue
        agree["disagree"] += 1
        if len(disagree_samples) < 4000: disagree_samples.append((dem.get(k, k)[:120], funcs[n]["name"][:80], os.path.relpath(to_tree(f), TREE), l))
stats["gcc_map_name_agree"] = agree["agree"]; stats["gcc_map_name_agree_after_lookup"] = agree["agree_after_name_lookup"]; stats["gcc_map_name_disagree_rerouted"] = agree["disagree"]
# external C-linkage symbols defined outside GCC's view (Rust FFI): map by unique exact name
byname = collections.defaultdict(list)
for i, n in funcs.items():
    if n["location"]["file_path"].endswith(".rs"): byname[n["name"]].append(i)
targets = {t for ts in gedges.values() for t, _, _ in ts}
for t in targets:
    if t not in gdef and not t.startswith("_Z") and len(byname.get(t, ())) == 1:
        gmap[t] = byname[t][0]; stats["ffi_mapped_by_name"] += 1
ours_unmapped = [k for k in in_tree if k not in gmap]
# functions in monero files with no matching trailmark node (macro-generated, implicit, generated
# protobuf, or trailmark node of another name at that line): one synthetic node per (file, line, name)
synth = {}
synth_by_file = collections.defaultdict(list)
for k in ours_unmapped:
    d = dem.get(k, k); f, l = gdef[k]; t = to_tree(f); nm = short_name(d)
    if (t, l, nm) not in synth:
        rel = os.path.relpath(t, TREE)
        nid = f"compiler:{rel}:{l}:{nm}"
        synth[(t, l, nm)] = nid; synth_by_file[t].append((l, nid))
        G["nodes"][nid] = {"id": nid, "name": nm, "kind": "function",
            "location": {"file_path": t, "start_line": l, "end_line": l, "start_col": 0, "end_col": 0},
            "parameters": [], "return_type": None, "exception_types": [], "type_parameters": [],
            "cyclomatic_complexity": None, "branches": [], "docstring": d, "origin": "source",
            "attributes": [["synthesized_by", "compiler:gcc"]], "exception_events": []}
    gmap[k] = synth[(t, l, nm)]
stats["synthetic_nodes_added"] = len(synth)
stats["gcc_functions_mapped"] = len(gmap)
stats["gcc_functions_in_tree_unmapped"] = len(ours_unmapped)

new_edges = {}   # (src, dst) -> (confidence, origin, site_file, site_line)
def add(src, dst, conf, origin, sf=None, sl=None, via=None):
    if not src or not dst: return
    key = (src, dst)
    if key not in new_edges or (new_edges[key][0] != "certain" and conf == "certain"):
        new_edges[key] = (conf, origin, to_tree(sf) if sf else None, sl, via)

site_lines = collections.defaultdict(set)  # trailmark caller -> call-site lines seen by the compiler (any target)
site_targets = collections.defaultdict(set)  # (trailmark caller, file, line) -> everything GCC calls there
indirect_at = set()
# ---------- libclang ----------
# Callers are resolved against the defining TU first: external-linkage names such as main()
# share one USR across executables.
cdefs, overrides, virt = {}, collections.defaultdict(set), {}
cls_bases, meth = collections.defaultdict(set), collections.defaultdict(set)
tus = []
for f in glob.glob(os.path.join(CG, "*.json")):
    d = json.load(open(f)); tus.append(d)
    for usr, v in d["all_defs"].items():
        if v[0] and usr not in cdefs: cdefs[usr] = v
    for m, parents in d["overrides"].items(): overrides[m].update(parents)
    for u, v in d.get("virtual", {}).items():
        virt[u] = v if isinstance(v, list) else [v, None]
    for c_, bs in d.get("bases", {}).items(): cls_bases[c_].update(bs)
    for owner, name, mu in d.get("methods", []): meth[(owner, name)].add(mu)
_mapcache = {}
def map_def(usr, v):
    if v is None: return None
    key = (usr, v[0], v[1])
    if key not in _mapcache:
        f, s_, e_ = v
        n = locate(f, s_) if usr.startswith("lambda:") else locate_extent(f, s_, e_)
        if usr.startswith("lambda:") and n and "$lambda" not in n and to_tree(f):
            # trailmark has no node for this lambda: use GCC's synthetic one, not the enclosing function
            c = sorted((l_, x) for l_, x in synth_by_file.get(to_tree(f), ()) if s_ <= l_ <= e_ and x.endswith(":$lambda"))
            n = c[0][1] if c else None
            stats["lambda_mapped_to_synthetic" if n else "lambda_without_node"] += 1
        if not n and to_tree(f):
            c = sorted(x for x in synth_by_file.get(to_tree(f), ()) if s_ <= x[0] <= e_)
            if c: n = c[0][1]
        _mapcache[key] = n
    return _mapcache[key]
def usr_name(usr):
    m = re.findall(r"@F@([^#@]+)#|@FT@>\d+(?:#[^#]*)*?#T([^#@]+)#|@FI@([^#@]+)", usr)
    if not m: return None
    return next(x for x in m[-1] if x)
clang_dis = []
_rescache = {}
def resolve(usr, v, count=False):
    """map_def, then the name check: a trailmark node whose span swallows a
    differently named function is not that function."""
    key = (usr, v[0], v[1], v[2]) if v else None
    if key in _rescache and not count: return _rescache[key]
    n = map_def(usr, v)
    if n and not usr.startswith("lambda:"):
        un = usr_name(usr)
        if un and un != base(funcs[n]["name"] if n in funcs else G["nodes"][n]["name"]):
            if count:
                stats["clang_map_name_disagree"] += 1
                clang_dis.append((un, funcs[n]["name"] if n in funcs else G["nodes"][n]["name"], usr[:100]))
            n = locate_named(v[0], v[1], v[2], un)
            if n:
                if count: stats["clang_map_agree_after_lookup"] += 1
            else:
                c = [x for x in synth_by_file.get(to_tree(v[0]), ()) if v[1] <= x[0] <= v[2] and x[1].endswith(":" + un)]
                n = c[0][1] if c else None
        elif un and count: stats["clang_map_name_agree"] += 1
    _rescache[key] = n
    return n
cmap = {}
for usr, v in cdefs.items():
    n = resolve(usr, v, count=True)
    if n: cmap[usr] = n
    elif to_tree(v[0]): stats["clang_defs_in_tree_unmapped"] += 1
children = collections.defaultdict(set)
for m, parents in overrides.items():
    for p in parents: children[p].add(m)
derived_of = collections.defaultdict(set)
for c_, bs in cls_bases.items():
    for b in bs: derived_of[b].add(c_)
_desc = {}
def descendants(c_):
    if c_ not in _desc:
        out, stack = {c_}, [c_]
        while stack:
            for d_ in derived_of.get(stack.pop(), ()):
                if d_ not in out: out.add(d_); stack.append(d_)
        _desc[c_] = out
    return _desc[c_]
def hierarchy_methods(owner, name):
    return {m for c_ in descendants(owner) for m in meth.get((c_, name), ())}
def overriders(m):
    """clang override relation plus same-named methods in derived classes (covers dependent bases)."""
    out, stack = {m}, [m]
    while stack:
        for c in children.get(stack.pop(), ()):
            if c not in out: out.add(c); stack.append(c)
    if m in virt and virt[m][1]:
        out |= hierarchy_methods(virt[m][1], virt[m][0])
    return out
_src = {}
def is_call_at(f, line, name):
    if f not in _src:
        try: _src[f] = open(f, errors="replace").read().splitlines()
        except OSError: _src[f] = []
    t = _src[f][line - 1] if 0 < line <= len(_src[f]) else ""
    n = re.escape(name.split("::")[-1])
    return bool(re.search(r"\b" + n + r"\s*\(", t)) and not re.search(r"&\s*(?:\w+::)*" + n + r"\b", t)
# class USR <-> qualified name, for reading template arguments out of demangled instantiations
def usr_qual(u):
    segs = re.findall(r"@(?:N|S|C|U|ST>[^@]*)@([A-Za-z_]\w*)", u)
    return "::".join(segs) if segs else None
cls_by_qual = collections.defaultdict(set)
for (owner, _n) in meth: 
    q = usr_qual(owner)
    if q: cls_by_qual[q].add(owner)
for c_ in set(cls_bases) | {b for bs in cls_bases.values() for b in bs} | {v[1] for v in virt.values() if v[1]}:
    q = usr_qual(c_)
    if q: cls_by_qual[q].add(c_)
def spec_overriders(m):
    """A virtual call through a class-template specialization names the specialization's method
    (`@S@i_p2p_endpoint>#...@F@send_txs`); overrides are recorded on the primary template."""
    if m in virt or ">#" not in m: return set()
    i = max(m.rfind("@F@"), m.rfind("@FT@"))
    if i < 0: return set()
    owner, name = m[:i], usr_name(m)
    q = usr_qual(owner.split(">#")[0])
    out = set()
    for prim in cls_by_qual.get(q, ()):
        out |= hierarchy_methods(prim, name)
    return out
dep_at = collections.defaultdict(set)      # (tree file, line) -> dependent callee names
table_refs = collections.defaultdict(set)  # tree file -> functions referenced at file scope
for d in tus:
    local = d["all_defs"]
    def caller(usr):
        v = local.get(usr) or cdefs.get(usr)
        return (resolve(usr, v) if v else None, v[0] if v else None)
    for c, m, name, line in d["vcalls"]:
        src, cf = caller(c)
        if src and to_tree(cf): site_lines[src].add((to_tree(cf), line))
        for o in overriders(m) | spec_overriders(m):
            if o in cmap: add(src, cmap[o], "inferred", "virtual", cf, line); stats["edge_virtual"] += 1
    for c, target, name, line, col in d["addr"]:
        src, cf = caller(c)
        for o in overriders(target):
            if o in cmap and cmap[o] != src: add(src, cmap[o], "inferred", "reference", cf, line); stats["edge_reference"] += 1
    for enc, lam, f, line in d["lambdas"]:
        src, _ = caller(enc)
        add(src, map_def(lam, local.get(lam) or cdefs.get(lam)), "inferred", "lambda", f, line); stats["edge_lambda"] += 1
    for dc in d.get("depcalls", []):
        c, name, line = dc[:3]; recv = dc[3] if len(dc) > 3 else None
        v = local.get(c) or cdefs.get(c)
        if v and to_tree(v[0]): dep_at[(to_tree(v[0]), line)].add((name, recv))
    for usr, name, f, line in d.get("global_addr", []):
        # file-scope references include static-initializer calls (`x = make_arg();`): not table entries
        if to_tree(f) and usr in cmap and not is_call_at(f, line, name): table_refs[to_tree(f)].add(cmap[usr])
stats["clang_defs"] = len(cdefs); stats["clang_defs_mapped"] = len(cmap)

# GCC indirect sites not explained by a resolved virtual call: (a) dependent calls in templates
# -> virtual methods of that name; (b) function-pointer tables at file scope in the same file.
vline = set()
for d in tus:
    for c, m, name, line in d["vcalls"]:
        v = d["all_defs"].get(c) or cdefs.get(c)
        if v: vline.add((to_tree(v[0]), line))
def targ_classes(k):
    d = dem.get(k, k); depth = 0; args = []; cur = ""
    for ch in d:
        if ch == "(" and depth == 0: break
        if ch == "<": depth += 1; cur += " "; continue
        if ch == ">": depth -= 1; cur += " "; continue
        if depth > 0: cur += ch
    out = set()
    for q in re.findall(r"[A-Za-z_][\w]*(?:::[A-Za-z_]\w*)*", cur):
        out |= cls_by_qual.get(q, set())
    return out
all_classes = {c_ for cs in cls_by_qual.values() for c_ in cs}
def owner_classes(k):
    """The class a GCC instantiation is a member of, plus the classes nested in it."""
    d = dem.get(k, k); depth = 0; flat = ""
    for ch in d:
        if ch == "(" and depth == 0: break
        if ch == "<": depth += 1; continue
        if ch == ">": depth -= 1; continue
        if depth == 0: flat += ch
    q = flat.split(" ")[-1].rsplit("::", 1)[0] if "::" in flat else ""
    out = set()
    for o in cls_by_qual.get(q, ()):
        out |= {c_ for c_ in all_classes if c_ == o or c_.startswith(o + "@")}
    return out
def class_methods(c_, name):
    """`name` called on a receiver of class c_: the declaring class at or above c_, plus overrides below it."""
    found = set(hierarchy_methods(c_, name)); seen = {c_}; stack = [c_]
    while stack and not meth.get((stack[-1], name)):
        nxt = [b for b in cls_bases.get(stack.pop(), ()) if b not in seen]
        for b in nxt:
            seen.add(b); stack.append(b)
            if meth.get((b, name)): found |= meth[(b, name)]
    return found
ind = collections.Counter(); unc = []
for sk, sf, sl in indirect_sites:
    t = to_tree(sf); src = gmap.get(sk)
    if not t: ind["outside_tree"] += 1; continue
    if (t, sl) in vline: ind["resolved_virtual"] += 1; continue
    hit = False
    for name, recv in dep_at.get((t, sl), ()):
        cands = {cmap[m] for m in hierarchy_methods(recv, name) if m in cmap} if recv else set()
        origin = "template_virtual"
        if not cands:   # receiver unknown or a smart pointer: classes in the template arguments
            cands = {cmap[m] for c_ in targ_classes(sk) for m in class_methods(c_, name) if m in cmap}
            origin = "template_argument"
        if not cands:   # then the enclosing class and the classes nested in it
            cands = {cmap[m] for c_ in owner_classes(sk) for m in class_methods(c_, name) if m in cmap}
            origin = "template_enclosing_class"
        for d_ in cands:
            # a GCC edge from this instantiation, so the instantiation split attributes it correctly
            pk = "tmpl:" + origin + ":" + d_; gmap[pk] = d_
            gedges[sk].add((pk, sf, sl)); hit = True; stats["edge_" + origin] += 1
    if not hit and table_refs.get(t):
        for d_ in table_refs[t]:
            add(src, d_, "inferred", "function_table", sf, sl); stats["edge_function_table"] += 1
        hit = True
    if hit: ind["resolved_template_or_table"] += 1
    else: ind["unresolved"] += 1; unc.append((os.path.relpath(t, TREE), sl))
for k, v in ind.items(): stats["indirect_" + k] = v
json.dump(sorted(set(unc)), open(os.path.join(OUT, "indirect_uncovered.json"), "w"), indent=0)

# A lambda is entered from wherever its closure ends up (asio, std::function, threads), which GCC
# shows as an indirect call. Model it as called by the instantiation of its enclosing function (the
# same registration-site model as the clang lambda/reference edges), so each instantiation keeps its
# own lambda body: connection<levin>::handle_read's lambda reaches the levin handler only.
def _noparams(n):
    """Drop parameter lists and a leading return type outside template arguments; keep template arguments."""
    ang = par = 0; out = ""
    for ch in n:
        if ch == "<": ang += 1
        elif ch == ">": ang -= 1
        elif ch == "(" and ang == 0: par += 1; continue
        elif ch == ")" and ang == 0: par -= 1; continue
        if par == 0: out += ch
    out = re.sub(r"(\s*(const|volatile|noexcept|&&|&))+\s*$", "", out)
    ang = 0; cut = 0
    for i, ch in enumerate(out):
        if ch == "<": ang += 1
        elif ch == ">": ang -= 1
        elif ch == " " and ang == 0: cut = i + 1
    return out[cut:]
by_dem = collections.defaultdict(list)
for k in gdef:
    if k in dem: by_dem[_noparams(dem[k])].append(k)
for k in gdef:
    d = dem.get(k, "")
    if "::{lambda(" not in d: continue
    encl = _noparams(d[:d.index("::{lambda(")])
    for e_ in by_dem.get(encl, ()):
        if e_ != k: gedges[e_].add((k, None, 0)); stats["lambda_enclosing_instantiation_edges"] += 1

# A member of a class template that takes the address of another member (`bind(&T::handle_accept,
# this)`) does so per instantiation, but libclang only sees the template. Pair the instantiations
# by owner class, so the split treats the reference like a call, instead of the target node
# counting as entered indirectly and keeping every instantiation's callees.
def _owner(k):
    n = _noparams(dem.get(k, "")); ang = 0; cut = -1
    for i in range(len(n) - 1):
        if n[i] == "<": ang += 1
        elif n[i] == ">": ang -= 1
        elif ang == 0 and n[i:i + 2] == "::": cut = i
    return n[:cut] if cut > 0 else None
_keys = collections.defaultdict(list)
for k in gdef:
    if k in gmap: _keys[gmap[k]].append(k)
pseudo_origin = {}
def _from_tree(t):
    if not t: return None
    for pre, dst in ((TREE + "/src/", ROOT + "/src/"), (TREE + "/epee/", ROOT + "/contrib/epee/")):
        if t.startswith(pre): t = dst + t[len(pre):]; return t[:-4] if t.endswith(".inl.hpp") else t
    return None
for (X, Y), v in list(new_edges.items()):
    if v[1] != "reference" or len(_keys.get(X, ())) < 2 or len(_keys.get(Y, ())) < 2: continue
    by_owner = collections.defaultdict(list)
    for kd in _keys[Y]: by_owner[_owner(kd)].append(kd)
    pairs = [(ks, kd) for ks in _keys[X] for kd in by_owner.get(_owner(ks), ()) if _owner(ks)]
    if not pairs: continue
    for ks, kd in pairs:
        gedges[ks].add((kd, _from_tree(v[2]), v[3] or 0)); pseudo_origin[(ks, kd)] = "reference_instantiation"
    unpaired = {ks for ks in _keys[X]} - {ks for ks, _ in pairs}
    stats["reference_instantiations_unpaired"] += len(unpaired)
    if unpaired: continue    # some instantiation takes the address without a partner: keep the plain reference
    del new_edges[(X, Y)]
    stats["reference_paired_by_instantiation"] += 1

# Trailmark has one node per template; GCC has one per instantiation. Callees every instantiation
# of a node shares stay on that node. Callees only some instantiations have (the lambda handed to a
# scope_guard, T::store in store_t_to_binary<T>) are moved up to the callers of that instantiation,
# transitively, so instantiations do not leak each other's callees.
keys_of = collections.defaultdict(list)
for k in gdef:
    if k in gmap: keys_of[gmap[k]].append(k)
shared = {k for ks in keys_of.values() if len(ks) > 1 for k in ks}
stats["template_nodes_with_several_instantiations"] = sum(1 for ks in keys_of.values() if len(ks) > 1)

# unmapped-only subgraph, condensed once
U = rx.PyDiGraph(); uidx = {}
def un(k):
    if k not in uidx: uidx[k] = U.add_node(k)
    return uidx[k]
for s, ts in gedges.items():
    if s in gmap: continue
    un(s)
    for t, _, _ in ts:
        if t not in gmap: U.add_edge(un(s), un(t), None)
C = rx.condensation(U)
corder = list(reversed(rx.topological_sort(C)))

def compute_reach(spec):
    rm = {}
    for ci_ in corder:
        acc = set()
        for k in C[ci_]:
            for t, _, _ in gedges.get(k, ()):
                if t in gmap: acc.add(gmap[t]); acc |= spec.get(t, set())
        for succ in C.successor_indices(ci_): acc |= rm[C[succ][0]]
        for k in C[ci_]: rm[k] = acc
    return rm

def out_of(k, rm, spec):
    o = set()
    for t, _, _ in gedges.get(k, ()):
        if t in gmap: o.add(gmap[t]); o |= spec.get(t, set())
        else: o |= rm.get(t, set())
    return o

spec, common = {}, {}
for it in range(50):
    reach_mapped = compute_reach(spec)
    out = {k: out_of(k, reach_mapped, spec) for k in shared}
    nspec = {}
    for X, ks in keys_of.items():
        if len(ks) < 2: continue
        cm = set.intersection(*(out[k] for k in ks))
        common[X] = cm
        for k in ks:      # grow-only: recursive templates otherwise oscillate
            d = (out[k] - cm) | spec.get(k, set())
            if d: nspec[k] = d
    if nspec == spec: break
    spec = nspec
stats["instantiation_split_iterations"] = it + 1
stats["instantiation_specific_callee_sets"] = len(spec)

for s, ts in gedges.items():
    src = gmap.get(s)
    if not src: continue
    keep = common.get(src) if s in shared else None     # shared instantiation: only its common callees
    for t, sf, sl in ts:
        if to_tree(sf):
            site_lines[src].add((to_tree(sf), sl))
            st = site_targets[(src, to_tree(sf), sl)]
            st.add(gmap.get(t, t)); st |= spec.get(t, set()) | reach_mapped.get(t, set())
        if t in gmap:
            if keep is None or gmap[t] in keep:
                if t.startswith("tmpl:"): add(src, gmap[t], "inferred", t.split(":")[1], sf, sl)
                elif (s, t) in pseudo_origin: add(src, gmap[t], "inferred", pseudo_origin[(s, t)], sf, sl)
                else: add(src, gmap[t], "certain", "gcc", sf, sl); stats["edge_gcc_direct"] += 1
            for d in spec.get(t, ()):
                if keep is None or d in keep:
                    add(src, d, "certain", "gcc_instantiation", sf, sl, t); stats["edge_gcc_instantiation"] += 1
        else:
            for d in reach_mapped.get(t, ()):
                if keep is None or d in keep:
                    add(src, d, "inferred", "gcc_bridged", sf, sl, t); stats["edge_gcc_bridged"] += 1
for s, sf, sl in indirect_sites:
    src = gmap.get(s)
    if src and to_tree(sf): site_lines[src].add((to_tree(sf), sl)); indirect_at.add((src, to_tree(sf), sl))

# A template node that is also entered indirectly (vtable, function table, callback, lambda) has
# callers the split cannot see: keep its instantiation-specific callees on the node itself. Same for
# an instantiation with no direct caller.
# keys some mapped function reaches directly or through unmapped (std/boost) code
seen_u = set(); stack = [t for s_, ts in gedges.items() if s_ in gmap for t, _, _ in ts if t not in gmap]
while stack:
    u = stack.pop()
    if u in seen_u: continue
    seen_u.add(u); stack += [t for t, _, _ in gedges.get(u, ()) if t not in gmap]
visible = {t for s_, ts in gedges.items() if s_ in gmap or s_ in seen_u for t, _, _ in ts if t in gmap}
entered_indirectly = {d for (s_, d), v in new_edges.items()
                      if v[1] not in ("gcc", "gcc_bridged", "gcc_instantiation", "lambda", "reference_instantiation")}
for X, ks in keys_of.items():
    if len(ks) < 2: continue
    for k in ks:
        if k in spec and (X in entered_indirectly or k not in visible):
            for d in spec[k]:
                add(X, d, "certain", "gcc_instantiation_kept", None, None, k); stats["edge_gcc_instantiation_kept"] += 1

# Instantiation-specific callees that no caller received (neither emitted nor forwarded upward)
rcallers = collections.defaultdict(set)
for s_, ts in gedges.items():
    for t, _, _ in ts: rcallers[t].add(s_)
def mapped_callers(k):
    out_, seen_, st_ = set(), set(), [k]
    while st_:
        x = st_.pop()
        for s_ in rcallers.get(x, ()):
            if s_ in seen_: continue
            seen_.add(s_)
            if s_ in gmap: out_.add(s_)
            else: st_.append(s_)
    return out_
orphans = []
for k, ds in spec.items():
    cs = mapped_callers(k)
    for d in ds:
        if (gmap[k], d) in new_edges and new_edges[(gmap[k], d)][1] == "gcc_instantiation_kept": continue
        if not any((gmap[s_], d) in new_edges or d in spec.get(s_, ()) for s_ in cs):
            orphans.append((k, d))
stats["instantiation_specific_pairs"] = sum(map(len, spec.values()))
stats["instantiation_specific_pairs_undelivered_kept_on_node"] = len(orphans)
json.dump(sorted(orphans), open(os.path.join(OUT, "instantiation_undelivered.json"), "w"), indent=0)
for k, d in orphans:
    add(gmap[k], d, "certain", "gcc_instantiation_kept", None, None, k); stats["edge_gcc_instantiation_kept"] += 1

# ---------- inject (through trailmark's model so snapshot provenance is recomputed) ----------
from trailmark.models.graph import CodeGraph
from trailmark.models.nodes import CodeUnit
from trailmark.models.edges import CodeEdge
from trailmark.models.snapshot import _decode
from trailmark.query.api import QueryEngine
graph = CodeGraph.from_snapshot(json.load(open(SNAP_IN)), verify_sources=False)
for nid in synth.values():
    graph.nodes[nid] = _decode(G["nodes"][nid], CodeUnit, "node")
# Trailmark's own edges that the compiler contradicts: GCC compiled that call site, made no indirect
# call there, and called neither the trailmark target nor anything defined at the same place.
def same_place(a, b):
    na, nb = graph.nodes.get(a), graph.nodes.get(b)
    if not na or not nb or not getattr(nb, "location", None) or not getattr(na, "location", None): return False
    la, lb = na.location, nb.location
    return la.file_path == lb.file_path and la.start_line <= lb.end_line and lb.start_line <= la.end_line
contradicted, kept_edges = [], []
for e in graph.edges:
    if e.kind.value == "calls" and e.target_id in funcs and e.location is not None:
        k = (e.source_id, e.location.file_path, e.location.start_line)
        if k in site_targets and k not in indirect_at and e.target_id not in site_targets[k] \
                and not any(same_place(e.target_id, d) for d in site_targets[k]):
            contradicted.append([e.source_id, e.target_id, e.location.start_line, sorted(x for x in site_targets[k] if x in graph.nodes)[:5]]); continue
    kept_edges.append(e)
graph.edges[:] = kept_edges
stats["trailmark_edges_contradicted_by_compiler_removed"] = len(contradicted)
json.dump(contradicted, open(os.path.join(OUT, "trailmark_edges_contradicted.json"), "w"), indent=0)
existing = {(e.source_id, e.target_id) for e in graph.edges if e.kind.value == "calls"}
added = 0
vias = sorted({v[4] for v in new_edges.values() if v[4]})
vdem = dict(zip(vias, subprocess.run(["c++filt"], input="\n".join(v.split(":")[-1] for v in vias),
                                     capture_output=True, text=True).stdout.split("\n")))
for (s_, t), (conf, origin, sf, sl, via) in new_edges.items():
    if s_ == t and origin != "gcc": continue
    if (s_, t) in existing: stats["already_in_trailmark"] += 1; continue
    graph.edges.append(_decode({"source_id": s_, "target_id": t, "kind": "calls", "confidence": conf,
        "location": ({"file_path": sf, "start_line": sl, "end_line": sl, "start_col": 0, "end_col": 0} if sf and sl else None),
        "attributes": [["configured_by", "compiler:" + origin]] + ([["via", vdem.get(via, via)[:300]]] if via else [])}, CodeEdge, "edge"))
    added += 1
stats["edges_injected"] = added
json.dump([[a, b, v[1]] for (a, b), v in new_edges.items()], open(os.path.join(OUT, "compiler_pairs.json"), "w"))
engine = QueryEngine.from_graph(graph)
open(SNAP_OUT, "w").write(engine.to_snapshot(indent=None))

# ---------- coverage ----------
calls_by = collections.defaultdict(list)
proxies = {i for i, n in G["nodes"].items() if n["kind"] == "proxy"}
for e in json.load(open(SNAP_IN))["graph"]["edges"]:
    if e["kind"] == "calls" and e["source_id"] in funcs:
        calls_by[e["source_id"]].append(e)
tot = res_tm = res_cc = 0; uncovered = collections.Counter(); unseen_callee = collections.Counter(); nocompile = set()
for src, es in calls_by.items():
    for e in es:
        if e["target_id"] not in proxies:
            res_tm += 1; tot += 1; continue
        tot += 1
        loc = e.get("location") or {}
        if (loc.get("file_path"), loc.get("start_line")) in site_lines.get(src, ()):
            res_cc += 1
        else:
            uncovered[src] += 1
            unseen_callee[(e.get("attributes") and dict(map(tuple, e["attributes"])).get("bare_name")) or e["target_id"].split(":")[-1].split(".")[-1]] += 1
            if src not in site_lines: nocompile.add(src)
stats["trailmark_call_sites"] = tot
stats["sites_resolved_by_trailmark"] = res_tm
stats["unresolved_sites_seen_by_compiler"] = res_cc
stats["sites_still_unseen"] = tot - res_tm - res_cc
stats["functions_with_calls_never_compiled"] = len(nocompile)
fn_total = len(funcs); fn_mapped = len(set(gmap.values()) | set(cmap.values()))
stats["trailmark_functions"] = fn_total; stats["trailmark_functions_with_compiler_evidence"] = fn_mapped
json.dump({"stats": stats, "never_compiled": sorted(nocompile),
           "top_uncovered": uncovered.most_common(200), "gcc_name_disagreements": disagree_samples, "clang_name_disagreements": clang_dis, "unseen_by_callee": unseen_callee.most_common(300),
           "gcc_unmapped_in_tree": [[k, gdef[k][0], gdef[k][1]] for k in ours_unmapped]},
          open(os.path.join(OUT, "compiler_merge_report.json"), "w"), indent=1)
for k, v in stats.items(): print(f"{k:45} {v}")

