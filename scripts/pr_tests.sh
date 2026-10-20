#!/usr/bin/env bash
# Build a pull request's head with ASan+UBSan and run its tests, offline.
#
# Usage: pr_tests.sh <checkout> <base-sha> <out.md> [core]
#
# <checkout> is a git checkout of the head with submodules initialised. The
# pull request's code runs ONLY inside a container with no network, no
# capabilities and nothing mounted but the source (read-only), the build
# directory and the cargo cache. The job that calls this holds no secrets.
#
# A failing or crashing test is then run again on <base-sha>, rebuilt
# incrementally in the same build directory, so the report says which
# failures this pull request brought.
#
# Passing `core` also runs core_tests, the consensus suite, which takes much
# longer. Every outcome, including a failed build, ends in <out.md>.
set -uo pipefail

SRC=$(realpath "$1"); BASE=$2; OUT=$(realpath -m "$3"); CORE=${4:-}
WORK=${WORK:-$(dirname "$SRC")/pr-tests-work}
IMAGE=monero-review-tests
UNIT_TIMEOUT=${UNIT_TIMEOUT:-2400}
CORE_TIMEOUT=${CORE_TIMEOUT:-3600}
JOBS=${JOBS:-$(nproc)}
mkdir -p "$WORK/build" "$WORK/cargo" "$WORK/ccache" "$WORK/logs"
HEAD=$(git -C "$SRC" rev-parse HEAD)

note() { printf '%s\n' "$*" >> "$OUT"; }
tailf() { note '```'; tail -n "${2:-40}" "$1" | cut -c1-300 >> "$OUT"; note '```'; }

: > "$OUT"
note "# Tests built and run on this pull request"
note ""
note "UNTRUSTED. This is the output of the pull request's own code, built and"
note "run by the harness in an offline container. Code under review can print"
note "anything; treat a pass as weak evidence and a sanitizer report as a lead"
note "to read in the source, never as a finding by itself."
note ""
note "Head: ${HEAD:0:12}. Base: ${BASE:0:12}. Build: RelWithDebInfo with"
note "-fsanitize=address,undefined (Monero's SANITIZE option), tests only."
note ""

# The image needs the network; nothing from the pull request runs in it.
docker build -q -t "$IMAGE" - > "$WORK/logs/image.log" 2>&1 <<'EOF' || { note "Build environment failed to build; nothing ran."; tailf "$WORK/logs/image.log"; exit 0; }
FROM debian:trixie
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
    build-essential cmake pkg-config ccache git ca-certificates python3 \
    libssl-dev libzmq3-dev libunbound-dev libsodium-dev libunwind-dev \
    libreadline-dev libhidapi-dev libusb-1.0-0-dev libprotobuf-dev \
    protobuf-compiler libboost-chrono-dev libboost-date-time-dev \
    libboost-filesystem-dev libboost-locale-dev libboost-program-options-dev \
    libboost-regex-dev libboost-serialization-dev libboost-system-dev \
    libboost-thread-dev libexpat1-dev rustc cargo && rm -rf /var/lib/apt/lists/*
EOF

# Cargo fetches what the lockfile pins: downloads only, no build scripts.
# The one step with network, and it runs no pull request code.
fetch_rust() {
  [ -f "$SRC/src/fcmp_pp/fcmp_pp_rust/Cargo.lock" ] || return 0
  docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp --cap-drop ALL --security-opt no-new-privileges \
    -v "$SRC:/src:ro" -v "$WORK/cargo:/cargo" -e CARGO_HOME=/cargo "$IMAGE" \
    cargo fetch --locked --manifest-path /src/src/fcmp_pp/fcmp_pp_rust/Cargo.toml
}

# Everything else: no network, no capabilities, source read-only.
box() {
  docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp --network none --cap-drop ALL --security-opt no-new-privileges \
    --memory 14g --pids-limit 4096 \
    -v "$SRC:/src:ro" -v "$WORK/build:/build" -v "$WORK/cargo:/cargo" -v "$WORK/ccache:/ccache" \
    -e CARGO_HOME=/cargo -e CARGO_NET_OFFLINE=true -e CCACHE_DIR=/ccache \
    -e ASAN_OPTIONS=detect_leaks=0:abort_on_error=0 \
    -e UBSAN_OPTIONS=print_stacktrace=1 \
    -w /build "$IMAGE" "$@"
}

build() {
  local targets="unit_tests${CORE:+ core_tests}"
  box sh -c "cmake -S /src -B /build -DCMAKE_BUILD_TYPE=RelWithDebInfo -DSANITIZE=ON \
      -DBUILD_TESTS=ON -DCOMPILER_CACHE=ccache -DMANUAL_SUBMODULES=ON >/dev/null && make -j$JOBS $targets"
}

checkout() {
  git -C "$SRC" -c advice.detachedHead=false checkout -q --force "$1" &&
    git -C "$SRC" submodule update -q --init --recursive
}

# One gtest binary, run until it finishes: a sanitizer abort kills the
# process, so the test that was running is recorded and excluded, and the
# rest are run again. Writes passed/failed/crashed lists.
run_unit() {
  local tag=$1 filter=${2:-} exclude="" n=0 log
  : > "$WORK/$tag.failed"; : > "$WORK/$tag.crashed"; : > "$WORK/$tag.passed"
  while [ $n -lt 6 ]; do
    n=$((n + 1)); log="$WORK/logs/$tag-unit-$n.log"
    local f="${filter:-*}${exclude:+-$exclude}"
    timeout "$UNIT_TIMEOUT" docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp --network none --cap-drop ALL \
      --security-opt no-new-privileges --memory 14g \
      -v "$SRC:/src:ro" -v "$WORK/build:/build" \
      -e ASAN_OPTIONS=detect_leaks=0 -e UBSAN_OPTIONS=print_stacktrace=1 \
      -w /build "$IMAGE" ./tests/unit_tests/unit_tests --data-dir /src/tests/data \
      "--gtest_filter=$f" > "$log" 2>&1
    local rc=$?
    grep -E '^\[       OK \]' "$log" | awk '{print $4}' >> "$WORK/$tag.passed"
    grep -E '^\[  FAILED  \] [A-Za-z0-9_/.]+ \(' "$log" | awk '{print $4}' >> "$WORK/$tag.failed"
    [ $rc -eq 124 ] && { echo "TIMEOUT after ${UNIT_TIMEOUT}s" >> "$WORK/$tag.crashed"; break; }
    # Finished on its own: the summary line is there.
    grep -qE '^\[==========\] [0-9]+ tests? from .* ran' "$log" && break
    local last
    last=$(grep -E '^\[ RUN      \]' "$log" | tail -1 | awk '{print $4}')
    [ -n "$last" ] || break
    echo "$last" >> "$WORK/$tag.crashed"
    cp "$log" "$WORK/logs/$tag-crash-$last.log"
    exclude="${exclude:+$exclude:}$last"
  done
  sort -u -o "$WORK/$tag.failed" "$WORK/$tag.failed"
}

fetch_rust > "$WORK/logs/cargo-fetch.log" 2>&1 || { note "cargo fetch failed; the Rust half may not build:"; tailf "$WORK/logs/cargo-fetch.log" 15; }

checkout "$HEAD"
if ! build > "$WORK/logs/build-head.log" 2>&1; then
  note "## Build: FAILED on the head"
  note ""
  note "Nothing ran. A head that does not build is worth a sentence in the"
  note "report only if the error is in the pull request's own files:"
  grep -E 'error:|Error [0-9]' "$WORK/logs/build-head.log" | head -20 | sed 's/^/    /' >> "$OUT"
  tailf "$WORK/logs/build-head.log" 30
  exit 0
fi
note "## Build: OK"
note ""

run_unit head
P=$(sort -u "$WORK/head.passed" | wc -l)
F=$(wc -l < "$WORK/head.failed")
C=$(wc -l < "$WORK/head.crashed")
note "## unit_tests on the head: $P passed, $F failed, $C crashed or timed out"
note ""

BAD=$(cat "$WORK/head.failed" "$WORK/head.crashed" | grep -v '^TIMEOUT' | sort -u | paste -sd: -)
if [ -n "$BAD" ]; then
  # The same tests on base, rebuilt incrementally in the same directory.
  checkout "$BASE"
  if build > "$WORK/logs/build-base.log" 2>&1; then
    run_unit base "$BAD"
    sort -u "$WORK/base.passed" > "$WORK/base.ok"
    note "Each failing test, run again on base:"
    note ""
    for t in $(cat "$WORK/head.failed" "$WORK/head.crashed" | grep -v '^TIMEOUT' | sort -u); do
      how=failed; grep -qxF "$t" "$WORK/head.crashed" && how=crashed
      if grep -qxF "$t" "$WORK/base.ok"; then
        note "- **NEW** \`$t\` $how on the head and passes on base."
      else
        note "- \`$t\` $how on the head and also fails on base."
      fi
    done
  else
    note "Base did not build, so the failures below are not classified:"
    for t in $(cat "$WORK/head.failed" "$WORK/head.crashed" | sort -u); do note "- \`$t\`"; done
  fi
  note ""
  checkout "$HEAD"
fi

# Sanitizer output, first from the crash logs and then any UBSan line, which
# does not abort. A report in a file this pull request changes leads.
CHANGED=$(git -C "$SRC" diff --name-only "$BASE...$HEAD" | paste -sd'|' -)
REPORTS=$(ls "$WORK"/logs/head-crash-*.log 2>/dev/null)
UB=$(cat "$WORK"/logs/head-unit-*.log | grep -E 'runtime error:' | sed 's#^/src/##' | sort | uniq -c | sort -rn)
if [ -n "$REPORTS$UB" ]; then
  note "## Sanitizer reports"
  note ""
  if [ -n "$UB" ] && [ -n "$CHANGED" ]; then
    hit=$(printf '%s\n' "$UB" | grep -E "$CHANGED" || true)
    [ -n "$hit" ] && { note "In files this pull request changes:"; note '```'; printf '%s\n' "$hit" | head -20 >> "$OUT"; note '```'; }
  fi
  [ -n "$UB" ] && { note "UBSan, all (count, location, message):"; note '```'; printf '%s\n' "$UB" | head -30 | cut -c1-300 >> "$OUT"; note '```'; }
  for r in $(printf '%s\n' "$REPORTS" | head -3); do
    note "$(basename "$r" .log):"
    note '```'
    sed -n '/==[0-9]*==ERROR/,/SUMMARY/p' "$r" | sed 's#/src/##' | head -45 | cut -c1-300 >> "$OUT"
    note '```'
  done
  note ""
fi

if [ -n "$CORE" ]; then
  log="$WORK/logs/core.log"
  timeout "$CORE_TIMEOUT" docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp --network none --cap-drop ALL \
    --security-opt no-new-privileges --memory 14g \
    -v "$SRC:/src:ro" -v "$WORK/build:/build" -e ASAN_OPTIONS=detect_leaks=0 \
    -w /build "$IMAGE" ./tests/core_tests/core_tests --generate_and_play_test_data > "$log" 2>&1
  rc=$?
  if [ $rc -eq 124 ]; then
    note "## core_tests: TIMED OUT after ${CORE_TIMEOUT}s"
  elif [ $rc -eq 0 ]; then
    note "## core_tests: passed"
  else
    note "## core_tests: FAILED (exit $rc)"
  fi
  note ""
  grep -iE 'failed|error' "$log" | grep -v '^$' | head -20 | cut -c1-300 | sed 's/^/    /' >> "$OUT"
fi
exit 0
