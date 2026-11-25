# Compact call graph from the merged trailmark snapshot, readable with the standard library.
# usage: export.py <merged snapshot> <monero commit> > callgraph.json
import json, os, re, sys, time

ORDER = ["gcc", "gcc_instantiation", "gcc_instantiation_kept", "gcc_bridged", "trailmark", "virtual",
         "template_virtual", "template_argument", "template_enclosing_class", "reference",
         "reference_instantiation", "lambda", "function_table"]
snap, commit = sys.argv[1:3]
s = json.load(open(snap)); G = s["graph"]; root = G["root_path"].rstrip("/")

def path(p):
    r = os.path.relpath(p, root)
    if r.startswith("epee/"): r = "contrib/" + r
    return r[:-4] if r.endswith(".inl.hpp") else r

def label(i, n):
    if i.startswith("compiler:"): return n["name"]
    q = re.sub(r"@\d+_\d+", "", i.split(":", 1)[1] if ":" in i else i)
    return q.replace("$anonymous", "(anonymous)").replace("$lambda", "{lambda}").replace(".", "::")

F = sorted(i for i, n in G["nodes"].items() if n["kind"] in ("function", "method"))
idx = {i: k for k, i in enumerate(F)}
nodes = []
for i in F:
    n = G["nodes"][i]; l = n["location"]
    nodes.append([i, label(i, n), path(l["file_path"]), l["start_line"], l["end_line"]])
best = {}
for e in G["edges"]:
    if e["kind"] != "calls" or e["source_id"] not in idx or e["target_id"] not in idx: continue
    o = dict(map(tuple, e.get("attributes") or [])).get("configured_by", "trailmark").replace("compiler:", "")
    if o not in ORDER: ORDER.append(o)
    k = (idx[e["source_id"]], idx[e["target_id"]])
    if k not in best or ORDER.index(o) < ORDER.index(best[k]): best[k] = o
eps = sorted([idx[i], v.get("trust_level", ""), v.get("description", "")]
             for i, v in G["entrypoints"].items() if i in idx)
json.dump({"format": "monero-review-callgraph/1", "commit": commit,
           "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "origins": ORDER, "nodes": nodes,
           "edges": sorted([a, b, ORDER.index(o)] for (a, b), o in best.items()),
           "entrypoints": eps}, sys.stdout, separators=(",", ":"))
