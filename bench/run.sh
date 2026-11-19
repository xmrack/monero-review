#!/usr/bin/env bash
# Review every benchmark case (or the ones named) at one tier.
#
#   bench/run.sh standard                 # all cases
#   bench/run.sh deep c09-keyimage-subgroup h07-timestamp-median
#   DRY_RUN=1 bench/run.sh standard       # prepare each case, review none
#
# Results land in bench/results/<tier>-<UTC time>/<case>/; score them with
# bench/score.py <that directory>.
set -euo pipefail

TIER=${1:?usage: bench/run.sh standard|deep [case-id...]}
shift
case "$TIER" in standard|deep) ;; *) echo "tier must be standard or deep" >&2; exit 1 ;; esac

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(dirname "$HERE")
OUT="$HERE/results/$TIER-$(date -u +%Y%m%dT%H%M%SZ)"

if [ "$#" -gt 0 ]; then
  CASES=("$@")
else
  CASES=()
  for d in "$HERE"/cases/*/; do CASES+=("$(basename "$d")"); done
fi

mkdir -p "$OUT"
failed=0
for id in "${CASES[@]}"; do
  dir="$HERE/cases/$id"
  [ -f "$dir/case.json" ] || { echo "!! no case $id" >&2; failed=$((failed + 1)); continue; }
  num=$(python3 -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["number"])' "$dir/case.json")
  echo "==> $id (#$num, $TIER)"
  if ! CASE="$dir" BENCH_OUT="$OUT/$id" TIER="$TIER" DEEP= \
       "$ROOT/review-local.sh" "$num" > "$OUT/$id.log" 2>&1; then
    echo "!! $id failed; see $OUT/$id.log" >&2
    failed=$((failed + 1))
  fi
done
echo "==> $OUT ($failed failed)"
[ -n "${DRY_RUN:-}" ] || echo "==> score: python3 -I $HERE/score.py $OUT"
