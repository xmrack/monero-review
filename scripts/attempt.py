#!/usr/bin/env python3
"""Decide whether a failed run was THIS PR's fault, from the execution log.

    EXEC_FILE=<path[,path]> python3 scripts/attempt.py

Prints `verdict=pr|infra|unknown` on stdout for $GITHUB_OUTPUT, and a reason on
stderr. Never fails: an unreadable or unrecognised log prints `unknown` and the
caller falls back to its elapsed-time heuristic.

Why this exists
---------------
`Record failed attempt` has to answer one question: does this failure count
against the PR's MAX_ATTEMPTS budget? Getting it wrong is expensive in both
directions -- charge the PR for an account-level blip and two of them retire it
from the queue for good; refuse to charge a PR that genuinely cannot be
reviewed and it is the newest unreviewed item on every tick forever, blocking
the queue and re-burning the budget each time.

That question was answered purely by elapsed time: under MIN_REAL_ATTEMPT_
SECONDS meant "usage limit or auth, not the PR's fault". That proxy worked
while reviews took 4-13 minutes on Sonnet. It degrades on Opus, where runs are
long enough that a transient API error twenty minutes in looks exactly like a
PR that is genuinely too hard.

The execution log answers it directly, so use it where it is decisive and leave
the clock as the fallback where it is not.

Deliberately conservative: only three situations are treated as decisive, and
everything else defers.
"""
import json
import os
import sys

# A run that consumed at least this many turns engaged with the diff; below it,
# the model may have died before doing any work worth charging for.
MIN_REAL_TURNS = 3

# Subtypes that mean the model spent its whole budget on this diff. That is the
# PR being too large or too hard, and a retry produces the same outcome.
BUDGET_EXHAUSTED = {"error_max_turns"}

# An ACCOUNT-level limit is never the pull request's fault, and it is the one
# failure this file used to get backwards. A limit refused before any work
# leaves no execution log at all, which the `not paths` branch below has
# always read as infra. A limit landing MID-RUN is the opposite: the log is
# complete, with real turns and real tokens, so it fell through to "the model
# did real work and produced nothing" and charged the PR. Two of those retire
# it from the queue permanently, for something no diff could have caused.
#
# There is no usage-limit subtype to key off -- the set is success,
# error_during_execution, error_max_turns, error_max_budget_usd and
# error_max_structured_output_retries. A subscription usage limit surfaces as
# a 429 recorded in `api_error_status`, on a record that may still say
# `subtype: success` with `is_error` set. So match the status code, and match
# the message text too, because the field carrying it is not documented and
# has changed shape before.
API_LIMIT_STATUS = {429, 529}
LIMIT_PHRASES = (
    "usage limit",
    "session limit",
    "rate limit",
    "rate_limit",
    "overloaded",
    "too many requests",
    "quota",
)

METRIC_KEYS = ("total_cost_usd", "duration_ms", "usage", "num_turns", "subtype")


def load(path):
    """Parse a log that may be JSON or JSONL. Returns None on anything odd."""
    try:
        with open(path) as fh:
            text = fh.read().strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        events = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return events or None


def find_result(node, depth=0):
    """Deepest-first search for the record carrying run metrics.

    Same shape as telemetry.py's: the schema is not documented, so match on the
    presence of metric keys rather than on a path.
    """
    if depth > 6:
        return None
    if isinstance(node, dict):
        if any(k in node for k in METRIC_KEYS):
            return node
        for key in ("result", "data", "summary"):
            if key in node:
                hit = find_result(node[key], depth + 1)
                if hit:
                    return hit
        return None
    if isinstance(node, list):
        for item in reversed(node):
            hit = find_result(item, depth + 1)
            if hit:
                return hit
    return None


def hit_account_limit(result):
    """True when this record shows an account-level API limit, not a PR problem.

    Deliberately generous: a false positive costs one un-recorded attempt on a
    PR that will be retried anyway, while a false negative charges a PR for an
    outage. Those are not symmetric.
    """
    status = result.get("api_error_status")
    try:
        if status is not None and int(status) in API_LIMIT_STATUS:
            return True
    except (TypeError, ValueError):
        pass

    # Machine fields only. `result` is the model's own closing prose and is
    # deliberately NOT searched: this repository reviews networking code, so a
    # perfectly good review can end with "the PR adds rate limiting to the P2P
    # layer" and would otherwise spare a PR that genuinely cannot be reviewed,
    # leaving it at the head of the queue forever.
    blob = " ".join(
        str(result.get(key, "")) for key in ("errors", "error", "stop_reason")
    ).lower()
    return any(phrase in blob for phrase in LIMIT_PHRASES)


def tokens(result):
    usage = result.get("usage")
    if not isinstance(usage, dict):
        return 0
    return sum(v for v in usage.values() if isinstance(v, (int, float)))


def verdict():
    raw = os.environ.get("EXEC_FILE", "")
    paths, seen = [], set()
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        # Both passes can name the same file; realpath so one is not counted
        # as two, the same defect telemetry.py had.
        real = os.path.realpath(piece)
        if real not in seen and os.path.exists(real):
            seen.add(real)
            paths.append(real)

    if not paths:
        # No execution log anywhere. The model never got far enough to write
        # one: a workflow-validation skip, an auth failure, or a usage limit
        # refused before any call. None of those are the PR's fault, and this
        # is more reliable than the clock -- a validation skip exits 0 in
        # seconds but an auth failure can hang first.
        return "infra", "no execution log was written, so the model never ran"

    results = []
    for path in paths:
        data = load(path)
        if data is None:
            continue
        found = find_result(data)
        if found:
            results.append(found)

    if not results:
        return "unknown", "execution log present but no metrics record found"

    # Before anything else: an account-level limit is not this PR's fault at
    # any turn count. Checked ahead of BUDGET_EXHAUSTED so a run that was rate
    # limited on its way to the turn cap is still spared.
    for r in results:
        if hit_account_limit(r):
            return "infra", ("the run hit an account-level API limit "
                             "(rate/usage limit or an overloaded API), which no "
                             "change to this PR would avoid")

    for r in results:
        subtype = r.get("subtype")
        if subtype in BUDGET_EXHAUSTED:
            return "pr", f"the model exhausted its turn budget on this diff ({subtype})"

    total_turns = sum(r.get("num_turns", 0) for r in results
                      if isinstance(r.get("num_turns"), (int, float)))
    total_tokens = sum(tokens(r) for r in results)

    if total_turns >= MIN_REAL_TURNS and total_tokens > 0:
        return "pr", (f"the model did real work on this diff "
                      f"({int(total_turns)} turns, {int(total_tokens)} tokens) "
                      f"and still produced no usable review")

    if total_turns == 0 and total_tokens == 0:
        return "infra", "the model was invoked but consumed nothing"

    # Some work, but not enough to be sure. Let the clock decide.
    return "unknown", (f"inconclusive: {int(total_turns)} turns, "
                       f"{int(total_tokens)} tokens")


def main():
    try:
        state, reason = verdict()
    except Exception as exc:  # never fail the job over a log-parsing bug
        state, reason = "unknown", f"could not classify the failure ({exc})"
    print(f"verdict={state}")
    print(f"attempt: {state} -- {reason}", file=sys.stderr)


if __name__ == "__main__":
    main()
