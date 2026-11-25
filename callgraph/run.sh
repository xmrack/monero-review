#!/usr/bin/env bash
# Build the call graph of a monero checkout in a container.
# usage: callgraph/run.sh <monero checkout> <out dir>
# The checkout needs its submodules. Only `docker build` and `cargo fetch` use
# the network; the build, the analysis and the gate run with none. Exit status
# is the gate's: <out dir>/callgraph.json is publishable only on 0.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(realpath "$1"); OUT=$(realpath -m "$2")
WORK=${WORK:-$(mktemp -d)}
IMAGE=monero-review-callgraph
mkdir -p "$OUT" "$WORK/cargo"
docker build -q -t "$IMAGE" "$HERE" > "$OUT/image.log"
box() {
  docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -e JOBS="${JOBS:-}" ${CPUS:+--cpus "$CPUS"} \
    --cap-drop ALL --security-opt no-new-privileges \
    -e CARGO_HOME=/cargo -v "$SRC:/src" -v "$WORK:/work" -v "$WORK/cargo:/cargo" -v "$OUT:/out" \
    -v "$HERE:/cg:ro" "$@"
}
if [ -f "$SRC/src/fcmp_pp/fcmp_pp_rust/Cargo.lock" ]; then
  box "$IMAGE" cargo fetch -q --locked --manifest-path /src/src/fcmp_pp/fcmp_pp_rust/Cargo.toml
fi
box --network none -e CARGO_NET_OFFLINE=true "$IMAGE" bash /cg/pipeline.sh
