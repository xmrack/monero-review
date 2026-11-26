# Compact call graph from the merged trailmark snapshot, readable with the standard library.
# usage: export.py <merged snapshot> <monero commit> [compiler_pairs.json [refused.json]] > callgraph.json
import collections, hashlib, json, os, re, sys, time

ORDER = ["gcc", "gcc_instantiation", "gcc_instantiation_kept", "gcc_bridged", "trailmark", "virtual",
         "template_virtual", "template_argument", "template_enclosing_class", "reference",
         "reference_instantiation", "lambda", "function_table"]
snap, commit = sys.argv[1:3]
# merge.py does not add a compiler edge trailmark already has; its origin still wins here.
pairs = json.load(open(sys.argv[3])) if len(sys.argv) > 3 else []
refused = json.load(open(sys.argv[4])) if len(sys.argv) > 4 else {"handlers": [], "commands": []}
s = json.load(open(snap)); G = s["graph"]; root = G["root_path"].rstrip("/")

def path(p):
    r = os.path.relpath(p, root)
    if r.startswith("epee/"): r = "contrib/" + r
    return r[:-4] if r.endswith(".inl.hpp") else r

def label(i, n):
    if i.startswith("compiler:"): q = n["name"]
    else:
        q = re.sub(r"@\d+_\d+", "", i.split(":", 1)[1] if ":" in i else i)
        q = q.replace("$anonymous", "(anonymous)").replace("$lambda", "{lambda}").replace(".", "::")
    return q.replace("::::", "::(anonymous)::")

F = sorted(i for i, n in G["nodes"].items() if n["kind"] in ("function", "method"))
idx = {i: k for k, i in enumerate(F)}
nodes = []
for i in F:
    n = G["nodes"][i]; l = n["location"]
    nodes.append([i, label(i, n), path(l["file_path"]), l["start_line"], l["end_line"]])
# GCC's lambdas that trailmark has no node for: name them after the function they sit in.
spans = collections.defaultdict(list)
for k, n in enumerate(nodes):
    if "$lambda" not in n[1]: spans[n[2]].append((n[4] - n[3], n[3], n[4], n[1]))
for n in nodes:
    if n[1] == "$lambda":
        inner = min(((w, l) for w, a, b_, l in spans[n[2]] if a <= n[3] <= b_), default=None)
        n[1] = (inner[1] + "::{lambda}") if inner else "{lambda}"
best = {}
def edge(s, t, o):
    if s not in idx or t not in idx: return
    if o not in ORDER: ORDER.append(o)
    k = (idx[s], idx[t])
    if k not in best or ORDER.index(o) < ORDER.index(best[k]): best[k] = o
for e in G["edges"]:
    if e["kind"] == "calls":
        edge(e["source_id"], e["target_id"],
             dict(map(tuple, e.get("attributes") or [])).get("configured_by", "trailmark").replace("compiler:", ""))
calls = set(best)
for s_, t, o in pairs:
    if s_ in idx and t in idx and (idx[s_], idx[t]) in calls: edge(s_, t, o)
# Only the entrypoints entrypoints.toml configures (and main): trailmark's own guesses
# (exported C symbols, Rust FFI) are internal boundaries, not attacker input.
HEURISTIC = ("C/C++ exported symbol", "Rust FFI export")
eps = {idx[i]: [idx[i], v.get("trust_level", ""), v.get("description", "")]
       for i, v in G["entrypoints"].items() if i in idx and not v.get("description", "").startswith(HEURISTIC)}
# The daemon is not trusted by the wallet: a wallet function that asks it for data, and
# refresh, which feeds what it pulled to the block and transaction parsers, take its reply.
REQUEST = re.compile(r"^(epee::net_utils|tools::wallet2)::invoke_http_(json|bin|json_rpc)$")
req = {k for i, k in idx.items() if REQUEST.match(label(i, G["nodes"][i]))}
callers = {a for (a, b) in best if b in req and a not in req
           and nodes[a][2].startswith(("src/wallet/", "src/simplewallet/"))}
callers |= {k for i, k in idx.items() if label(i, G["nodes"][i]) == "tools::wallet2::refresh"}
for k in callers:
    eps.setdefault(k, [k, "untrusted_external", "daemon reply to the wallet (remote node)"])
# The RPC dispatchers parse every request before its handler runs: the code they run
# for the wallet, or for a method restricted mode refuses, is semi-trusted.
lab = {k: label(i, G["nodes"][i]) for i, k in idx.items()}
for k, l in lab.items():
    if l == "tools::wallet_rpc_server::handle_http_request":
        eps.setdefault(k, [k, "semi_trusted_external", "wallet RPC"])
    if l == "cryptonote::core_rpc_server::handle_http_request":
        eps.setdefault(k, [k, "semi_trusted_external", "daemon RPC dispatcher, unrestricted mode"])
# Untrusted paths do not take these: restricted mode refuses the method before it parses
# the request.
refuse = re.compile(r"(^|::)(" + "|".join(map(re.escape, refused["commands"] or ["$^"])) + r")::"
                    r"|::core_rpc_server::(" + "|".join(map(re.escape, refused["handlers"] or ["$^"])) + r")$")
rpc_map = {k for k, l in lab.items() if l == "cryptonote::core_rpc_server::handle_http_request_map"}
cut = sorted([a, b] for (a, b) in best if a in rpc_map and refuse.search(lab[b]))
eps = sorted(eps.values())
# Which version of these scripts built it: a head graph is compared with master's only
# when both were built by the same rules.
here = os.path.dirname(os.path.realpath(__file__))
rules = hashlib.sha256()
for f in sorted(os.listdir(here)):
    if os.path.isfile(os.path.join(here, f)):
        rules.update(f.encode() + b"\0" + open(os.path.join(here, f), "rb").read())
json.dump({"format": "monero-review-callgraph/1", "commit": commit, "rules": rules.hexdigest()[:16],
           "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "origins": ORDER, "nodes": nodes,
           "edges": sorted([a, b, ORDER.index(o)] for (a, b), o in best.items()),
           "entrypoints": eps, "untrusted_cut": cut}, sys.stdout, separators=(",", ":"))
