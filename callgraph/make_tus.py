# usage: make_tus.py <monero checkout> <build dir> > cg_tus.jsonl
# One compile_commands entry per source file under src/ or contrib/epee/ (excluding external/ and generated files).
import json, os, sys
root, build = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
seen = set()
for e in json.load(open(os.path.join(build, "compile_commands.json"))):
    f = os.path.normpath(e["file"])
    if f in seen or f.startswith(build + "/") or "/external/" in f: continue
    if f.startswith(root + "/src/") or f.startswith(root + "/contrib/epee/"):
        seen.add(f); print(json.dumps(e))
