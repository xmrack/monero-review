#!/usr/bin/env bash
# Review the next unreviewed Monero PR on this machine. One PR per run.
#
# No GitHub credential: the claude CLI is already authenticated, and picking
# which PR to review only reads public data. Results land in reviews/.
#
# One of two ways to drive the drip; GitHub's own scheduler is not a third --
# see "the schedule" in the README for why it has never fired here. This one
# needs no credential but leaves results in reviews/ locally. The alternative,
# `gh workflow run review.yml -f pr=sweep` from cron, files them as issues.
#
# Run ONE of them, not both: this script skips PRs by looking at reviews/
# filenames and CI skips them by looking at issue markers, and neither sees the
# other's record, so both together will double-review and double-spend.
#
# Setup:
#   crontab -e   # add, with absolute paths:
#     23,53 * * * * /home/jack/Desktop/monero-review/scripts/drip.sh >> /tmp/monero-review.log 2>&1
#
# Check it is working:
#   tail /tmp/monero-review.log
#   ls ~/Desktop/monero-review/reviews/
set -euo pipefail

# cron gives you a near-empty PATH.
export PATH="/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin:${PATH:-}"

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

log() { echo "$(date -Is) $*"; }

if ! command -v claude >/dev/null 2>&1; then
  log "ERROR: claude not on PATH ($PATH)"
  exit 1
fi

# Ask the queue for one PR. Dedup counts both this repo's issues (public read,
# no token) and reviews/ filenames from previous local runs.
picked=$(
  UPSTREAM=${UPSTREAM:-monero-project/monero} \
  REVIEW_REPO=${REVIEW_REPO:-xmrack/monero-review} \
  REVIEWS_DIR="$HERE/reviews" \
  MAX_AGE_DAYS=${MAX_AGE_DAYS:-1} \
  BATCH=1 \
  python3 "$HERE/scripts/select_prs.py" | sed -n 's/^prs=//p'
)

pr=$(printf '%s' "$picked" | tr -cd '0-9')
if [ -z "$pr" ]; then
  log "nothing to review"
  exit 0
fi

log "reviewing PR $pr"
# `auto` lets review-local.sh route the tier and pick the model with it --
# Sonnet on a light diff, Opus otherwise. Set MODEL to pin one for every PR
# the drip picks.
if "$HERE/review-local.sh" "$pr" "${MODEL:-auto}"; then
  log "done: PR $pr"
else
  log "ERROR: review of PR $pr failed"
  exit 1
fi
