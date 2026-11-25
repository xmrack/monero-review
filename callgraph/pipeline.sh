#!/usr/bin/env bash
# Runs inside the callgraph container, offline. /src is a monero checkout with
# submodules, /work is scratch, /out receives callgraph.json and the logs.
set -euo pipefail
SRC=/src WORK=/work OUT=/out HERE=$(cd "$(dirname "$0")" && pwd)
PY=/opt/venv/bin/python JOBS=${JOBS:-$(nproc)}
log() { echo "[$(date -u +%H:%M:%S)] $*"; }
mkdir -p "$WORK/build" "$WORK/clang" "$OUT"

log "build with -fcallgraph-info"
cmake -S "$SRC" -B "$WORK/build" -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTS=OFF -DMANUAL_SUBMODULES=ON \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DCMAKE_C_FLAGS=-fcallgraph-info -DCMAKE_CXX_FLAGS=-fcallgraph-info \
  > "$OUT/cmake.log" 2>&1
cmake --build "$WORK/build" -j"$JOBS" > "$OUT/build.log" 2>&1
cmake --build "$WORK/build" -j"$JOBS" --target wallet_api >> "$OUT/build.log" 2>&1

log "libclang pass"
$PY -I "$HERE/make_tus.py" "$SRC" "$WORK/build" > "$WORK/tus.jsonl"
tr '\n' '\0' < "$WORK/tus.jsonl" |
  xargs -0 -P "$JOBS" -I{} $PY -I "$HERE/clang_extract.py" "$SRC" "$WORK/clang" {} > "$OUT/clang.log" 2>&1 || true
log "libclang: $(ls "$WORK/clang" | wc -l) of $(wc -l < "$WORK/tus.jsonl") translation units"

# After the build, so generated sources (trezor protobuf) are included. Trailmark
# skips .inl, so those are renamed in the copy.
log "trailmark"
rm -rf "$WORK/tree" && mkdir -p "$WORK/tree/.trailmark"
cp -a "$SRC/src" "$WORK/tree/src" && cp -a "$SRC/contrib/epee" "$WORK/tree/epee"
find "$WORK/tree" -name '*.inl' -exec sh -c 'mv "$1" "$1.hpp"' _ {} \;
$PY -I "$HERE/gen_entrypoints.py" "$SRC" "$WORK/refused.json" > "$WORK/tree/.trailmark/entrypoints.toml"
$PY -I "$HERE/snapshot.py" "$WORK/tree" "$WORK/trailmark.json" 2> "$OUT/trailmark.log"

log "merge"
$PY -I "$HERE/merge.py" "$SRC" "$WORK/build" "$WORK/tree" "$WORK/clang" "$WORK/trailmark.json" \
  "$WORK/merged.json" "$WORK/report" > "$OUT/merge.log"
$PY -I "$HERE/export.py" "$WORK/merged.json" "$(git -C "$SRC" rev-parse HEAD)" \
  "$WORK/report/compiler_pairs.json" "$WORK/refused.json" > "$OUT/callgraph.json"

log "gate"
$PY -I "$HERE/gate.py" "$OUT/callgraph.json" | tee "$OUT/gate.log"
