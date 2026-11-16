#!/usr/bin/env bash
# Prints what origin/base changed, since the commit the references were
# checked at, in the parts of the tree where a stale reference misleads most.
# Paths only: commit messages are author text. Silent when nothing changed or
# the pin is not an ancestor of origin/base (a backport branch).
# Usage: ref_drift.sh <monero checkout with .claude/references>
set -u
cd "$1" || exit 0
pin=$(grep -m1 -oE '^Written against master `[0-9a-f]{7,40}`' .claude/references/monero/README.md 2>/dev/null \
  | grep -oE '[0-9a-f]{7,40}')
[ -n "$pin" ] || exit 0
git merge-base --is-ancestor "$pin" origin/base 2>/dev/null || exit 0
changed=$(git diff --name-only "$pin" origin/base -- \
  src/fcmp_pp src/carrot_core src/carrot_impl src/ringct src/crypto src/cryptonote_basic \
  src/cryptonote_core src/blockchain_db src/hardforks src/cryptonote_config.h \
  src/cryptonote_protocol src/p2p src/rpc src/wallet src/serialization contrib/epee 2>/dev/null)
[ -n "$changed" ] || exit 0
n=$(printf '%s\n' "$changed" | wc -l)
echo
echo "The files in .claude/references/monero/ were checked at master $pin."
echo "Since then origin/base changed $n file(s) they describe. Where a reference"
echo "and the code disagree, the code wins: cite the code, and send the"
echo "correction through referenceUpdates. Changed since $pin:"
printf '%s\n' "$changed" | head -60 | sed 's/^/  /'
[ "$n" -le 60 ] || echo "  ... and $((n - 60)) more"
exit 0
