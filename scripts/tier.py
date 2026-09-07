#!/usr/bin/env python3
"""Choose which review a pull request gets.

The queue used to run one shape on everything: a single Opus reviewer at 200
turns, whatever arrived. That is flat in the size of the change while coverage
is not -- a two-file typo fix and a twenty-file wire-format rewrite cost the
same and are served very differently. This routes instead:

  light     a small change nowhere near a trust boundary. Same model, lower
            effort, fewer turns.
  standard  the single-reviewer + adversary shape this repo was built around.
  medium    the bounded agent fan-out: mapped into units, a researcher per
            unit, two verifier angles per candidate, counted in code.
  deep      never chosen here. It is a human escalation, hours and ~7x the
            cost of a standard review, and `mode=deep` names one PR by number.

EVERY TIER READS WITH THE SAME MODEL. The tiers differ by `--effort` and by
turn budget, never by who is doing the reading -- this is consensus-critical
financial software, a missed bug costs more than any review, and a smaller
model reads the same diff with less of everything. Thinking tokens were 80% of
the deep run's output bill, so effort is where the money actually is.

Two callers, one policy:

  - scripts/select_prs.py imports `classify` and feeds it the file list it
    already fetched for the doc-only probe, so routing costs no extra API
    call.
  - `tier.py --pr <n>` probes one PR directly, for the by-number dispatch
    path, which returns before the selector runs.
  - `tier.py --diff` classifies the checkout it is run in, for
    review-local.sh.

THE THRESHOLDS BELOW ARE A FIRST CUT AND ARE NOT MEASURED. They are picked to
fail upward: every rule that fires moves a PR to a *heavier* review, and the
only rule that can make one cheaper requires all three of small, short and
nowhere sensitive. If they are wrong the cost shows up in the telemetry footer
of every published issue, which is the place to re-derive them from.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

API = os.environ.get("API", "https://api.github.com")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

# Ordered cheapest first. `deep` is deliberately absent: nothing auto-selects
# it, and a router that could would be able to spend $100 and three hours of
# runner on whatever the queue happened to surface.
TIERS = ("light", "standard", "medium")

# Paths where this codebase handles input it did not produce, or decides
# consensus. A change touching one of these NEVER routes to `light`, however
# small it looks -- a one-line change to a bounds check in the deserialiser is
# exactly the diff this whole pipeline exists for, and it is also exactly the
# diff a size heuristic would wave through.
#
# Drawn from the trust-boundary table in
# .claude/skills/monero-security-review/references/trust-boundaries.md; keep
# the two in step. `external/` is here because a submodule bump is a
# supply-chain change whose size in the diff (one gitlink hash) says nothing
# about the size of the change.
SENSITIVE = re.compile(
    r"^(?:"
    r"src/(?:cryptonote_core|cryptonote_basic|cryptonote_protocol|ringct"
    r"|crypto|serialization|rpc|p2p|wallet|blockchain_db|hardforks"
    r"|multisig|checkpoints|net|device|device_trezor)/"
    r"|contrib/epee/"
    r"|external/"
    r")"
)

# A change at or above any of these is `medium`.
WIDE_FILES = 10          # files touched
WIDE_LINES = 800         # additions + deletions
# Lower bars, but only when the change reaches a trust boundary.
SENSITIVE_FILES = 4
SENSITIVE_LINES = 300
# A change below ALL of these, touching nothing sensitive, is `light`.
LIGHT_FILES = 2
LIGHT_LINES = 100


def classify(paths, lines, truncated=False):
    """Return (tier, reason).

    `paths` are repository-relative names, `lines` is additions + deletions,
    and `truncated` says the file list was capped and there are more files
    than we can see. Truncation routes to `medium`: an unknown number of
    unseen files is the case a size heuristic must not guess cheaply on.
    """
    paths = [p for p in paths if p]
    sensitive = sorted({p for p in paths if SENSITIVE.search(p)})
    n = len(paths)

    if truncated:
        return "medium", f"file list truncated at {n}; true width unknown"
    if n >= WIDE_FILES:
        return "medium", f"{n} files"
    if lines >= WIDE_LINES:
        return "medium", f"{lines} changed lines"
    if sensitive and n >= SENSITIVE_FILES:
        return "medium", (f"{n} files including {len(sensitive)} at a trust "
                          f"boundary ({sensitive[0]})")
    if sensitive and lines >= SENSITIVE_LINES:
        return "medium", (f"{lines} changed lines at a trust boundary "
                          f"({sensitive[0]})")
    if sensitive:
        return "standard", f"reaches a trust boundary ({sensitive[0]})"
    if n <= LIGHT_FILES and lines < LIGHT_LINES:
        return "light", f"{n} file(s), {lines} changed lines, nothing sensitive"
    return "standard", f"{n} file(s), {lines} changed lines"


def heaviest(tiers):
    """The heaviest tier in a selection.

    BATCH is 1 and documented as staying 1, so in practice this is the only
    PR's own tier. At BATCH>1 the matrix legs share one job-level
    `timeout-minutes`, so the whole batch runs at the heaviest tier in it:
    that overpays for the light ones and never under-reviews any of them,
    which is the direction to be wrong in.
    """
    ranked = [t for t in TIERS if t in set(tiers)]
    return ranked[-1] if ranked else "standard"


def get(path, params=None):
    url = f"{API}{path}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "monero-review",
        **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}),
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def from_api(upstream, number):
    """Classify one PR from its file listing. One API call."""
    try:
        files = get(f"/repos/{upstream}/pulls/{number}/files", {"per_page": 100})
    except urllib.error.HTTPError as exc:
        # Fail toward the shape the queue has always used rather than toward
        # the cheap one: an API hiccup must not silently downgrade a review.
        print(f"warn: file listing for #{number} failed ({exc.code}); "
              "routing to standard", file=sys.stderr)
        return "standard", f"file listing unavailable ({exc.code})"
    names = [f["filename"] for f in files]
    lines = sum(f.get("additions", 0) + f.get("deletions", 0) for f in files)
    return classify(names, lines, truncated=len(names) >= 100)


def from_checkout():
    """Classify the checkout this is run in, against origin/base.

    review-local.sh has the diff and no API budget, so it asks git. Same
    three-dot range every skill uses: origin/base...HEAD is the change, where
    origin/base..HEAD would be the whole branch divergence on a backport.
    """
    def git(*args):
        return subprocess.run(("git",) + args, check=True, text=True,
                              capture_output=True).stdout
    rng = "origin/base...HEAD"
    names = [n for n in git("diff", "--name-only", rng).splitlines() if n]
    lines = 0
    for row in git("diff", "--numstat", rng).splitlines():
        cols = row.split("\t")
        if len(cols) >= 2:
            # A binary file's counts are "-", which is not a width we can add.
            lines += sum(int(c) for c in cols[:2] if c.isdigit())
    return classify(names, lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pr", type=int, help="classify this upstream PR number")
    ap.add_argument("--diff", action="store_true",
                    help="classify the checkout against origin/base")
    args = ap.parse_args()

    if args.diff:
        tier, why = from_checkout()
    elif args.pr:
        tier, why = from_api(os.environ.get("UPSTREAM", "monero-project/monero"),
                             args.pr)
    else:
        ap.error("pass --pr <n> or --diff")

    # Flatten before printing. This goes to $GITHUB_OUTPUT, where a newline
    # in a value starts a new key -- and `why` can quote a path, which git
    # permits to contain almost anything.
    why = " ".join(str(why).split())
    print(f"tier chosen: {tier} -- {why}", file=sys.stderr)
    print(f"tier={tier}")
    print(f"tier_reason={why}")


if __name__ == "__main__":
    main()
