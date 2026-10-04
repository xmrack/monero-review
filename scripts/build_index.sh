#!/usr/bin/env bash
# Build a symbol index so the review can answer "who calls this" precisely
# instead of guessing from grep. ctags and cscope PARSE source text; they do
# not configure, compile, or execute anything from the PR.
#
# Degrades silently: if the tools are absent the review falls back to grep.
set -euo pipefail

cd "${1:-.}"

have() { command -v "$1" >/dev/null 2>&1; }

if ! have ctags && ! have cscope; then
  echo "index: ctags/cscope not installed -- skipping, review falls back to grep" >&2
  exit 0
fi

# Security surface only. tests/ and utils/ are excluded to keep the index
# small and the caller lists free of harness noise.
#
# Collect the directories that exist first: `find a b` where b is missing exits
# non-zero *after* writing a's results, and a `|| :` fallback would then discard
# them. UPSTREAM is configurable, so don't assume Monero's layout.
dirs=""
for d in src contrib; do
  [ -d "$d" ] && dirs="$dirs $d"
done
if [ -z "$dirs" ]; then
  echo "index: no src/ or contrib/ here, skipping" >&2
  exit 0
fi

# shellcheck disable=SC2086  # word splitting on $dirs is intended
find $dirs -type f \
  \( -name '*.c'  -o -name '*.cc'  -o -name '*.cpp' \
  -o -name '*.h'  -o -name '*.hpp' -o -name '*.inl' \) \
  > cscope.files 2>/dev/null || true

count=$(wc -l < cscope.files | tr -d ' ')
if [ "$count" = "0" ]; then
  echo "index: no source files found, skipping" >&2
  exit 0
fi
echo "index: ${count} source files" >&2

if have ctags; then
  # Default options only, so every run indexes the same way.
  if ctags --options=NONE --languages=C,C++ --fields=+ne --extras=+q \
       -L cscope.files -f tags 2>/dev/null; then
    echo "index: tags built ($(wc -l < tags | tr -d ' ') entries)" >&2
  else
    echo "index: ctags failed, continuing without it" >&2
  fi
fi

if have cscope; then
  if cscope -b -q -k -i cscope.files 2>/dev/null; then
    echo "index: cscope database built" >&2
  else
    echo "index: cscope failed, continuing without it" >&2
  fi
fi

# A SEPARATE index for tests/, deliberately not merged into the one above.
#
# Tests are the best available evidence of what a change is *supposed* to do,
# which is exactly the question a review asks of a diff -- and PRs frequently
# change them alongside the code (10819's own diff touches
# tests/libwallet_api_tests/main.cpp). But folding 211 test files into the main
# caller index would bury the reachability answers the review depends on under
# harness noise, which is why they were excluded in the first place. Two
# indexes gets both: clean caller lists by default, test usage on request.
if [ -d tests ] && have cscope; then
  find tests -type f \
    \( -name '*.c'  -o -name '*.cc'  -o -name '*.cpp' \
    -o -name '*.h'  -o -name '*.hpp' -o -name '*.inl' \) \
    > cscope.tests.files 2>/dev/null || true
  tcount=$(wc -l < cscope.tests.files | tr -d ' ')
  if [ "$tcount" != "0" ] && cscope -b -q -k -i cscope.tests.files -f tests.out 2>/dev/null; then
    echo "index: tests database built (${tcount} files)" >&2
  else
    echo "index: tests database skipped" >&2
  fi
fi
