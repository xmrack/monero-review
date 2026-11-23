#!/usr/bin/env bash
set -euo pipefail
CALLER_PATH=$PATH
PATH=/usr/bin:/bin

runner_root() {
  if [ -n "${FP_RUNNER_ROOT:-}" ]; then printf '%s\n' "$FP_RUNNER_ROOT"; return; fi
  local pid=$$ exe
  while [ "$pid" -gt 1 ]; do
    exe=$(readlink -f "/proc/$pid/exe" 2>/dev/null || true)
    if [ "${exe##*/}" = Runner.Worker ]; then dirname "$(dirname "$exe")"; return; fi
    pid=$(awk '/^PPid:/{print $2}' "/proc/$pid/status" 2>/dev/null || echo 1)
  done
  echo "fingerprint: cannot find the runner's install directory" >&2
  return 1
}

runner_trees() {
  local root e
  root=$(runner_root)
  [ -d "$root" ] || { echo "fingerprint: $root is not a directory" >&2; return 1; }
  printf '%s\n' "$root"
  for e in "$root"/*; do
    if [ -L "$e" ] && [ -d "$e" ]; then readlink -f "$e"; fi
  done
}

path_dirs() {
  local d
  printf '%s\n' "$SAVED_PATH" | tr ':' '\n' | while IFS= read -r d; do
    if [ -n "$d" ] && [ -d "$d" ]; then readlink -f "$d"; fi
  done | sort -u
}

print() {
  local trees t
  trees=$(runner_trees)
  while IFS= read -r t; do
    find "$t" -xdev -path "$t/_diag" -prune -o -type f \
      \( -perm /111 -o -name '*.so' -o -name '*.so.*' -o -name '*.dll' -o -name '*.js' -o -name '*.cjs' -o -name '*.mjs' \) \
      -printf '%p\t%i\t%s\t%C@\n' 2>/dev/null || true
  done <<< "$trees"
  path_dirs | while IFS= read -r d; do
    if [ -w "$d" ]; then
      find -L "$d" -maxdepth 1 -mindepth 1 -printf '%p\t%i\t%s\t%C@\n' 2>/dev/null || true
    else
      find -L "$d" -maxdepth 1 -mindepth 1 -writable -printf '%p\t%i\t%s\t%C@\n' 2>/dev/null || true
    fi
  done
}

SAVED_PATH=$CALLER_PATH
case "${1:-}" in
  snap)
    { printf 'PATH\t%s\n' "$SAVED_PATH"; print | LC_ALL=C sort; } > "$2"
    grep -qE '/externals/[^/]+/bin/node	' "$2" || { echo "fingerprint: the runner's node is not in the record" >&2; exit 1; }
    ;;
  check)
    SAVED_PATH=$(sed -n '1s/^PATH\t//p' "$2")
    if ! print | LC_ALL=C sort | cmp -s - <(tail -n +2 "$2"); then
      echo "fingerprint: a file outside the workspace changed" >&2
      exit 1
    fi
    ;;
  dirs)
    runner_trees
    path_dirs
    ;;
  *)
    echo "usage: fingerprint.sh snap|check <file> | dirs" >&2
    exit 2
    ;;
esac
