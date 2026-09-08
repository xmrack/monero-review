#!/usr/bin/env python3
"""Append a one-line run footer to review.md.

The claude-code-action `execution_file` schema is not documented, so this
parses defensively: it walks whatever JSON it is given looking for a record
carrying cost/usage fields, and degrades to wall-clock only if it finds
nothing. It must never fail the job -- any error just means a shorter footer.

TWO SCOPES LIVE IN THAT FILE AND ONLY ONE OF THEM IS THE RUN.

The result record carries `usage`, which is the Lead's own conversation, and
`modelUsage`, whose `costUSD` equals `total_cost_usd` -- so that one is the
whole run, subagents included. This footer used to print `usage` beside the
whole-run cost, and under the agent fleet the two are nowhere near each other.
Measured on run 487: `usage` said 1.10M in / 10.0k out while `modelUsage` said
7.22M in / 150.6k out for the same $10.74. A reader comparing two issues by
those columns was comparing orchestrators, not reviews, and would have
concluded the pipeline got lazier at the point it got more thorough -- turns
fell from 50-88 to 25-38 across the cutover while cost and wall clock roughly
doubled on diffs several times larger.

So `modelUsage` is what prints, `num_turns` is labelled as the Lead's and
nothing else, and the agent count comes from the workflow journal, which
records one `started` entry per dispatch -- measured rather than asserted.

Env:
  EXEC_FILE   path to the execution log (action output, or `claude
              --output-format json` stdout). Optional. Accepts a
              comma-separated list -- the review and refutation passes are
              separate invocations and their metrics are summed.
  REVIEW_MD   review file to append to. Default: review.md
  T0          unix timestamp taken before the review started. Optional.
  MODEL       model name to display. Optional.
  TIER        which review shape ran (`standard`/`deep`). Optional.
  JOURNAL     glob for the agent-fleet journal(s). Optional; defaults to the
              path the CLI writes under $HOME.
  RUN_URL     link to the CI run. Optional.
"""
import glob
import json
import os
import sys
import time

USAGE_KEYS = ("input_tokens", "output_tokens",
              "cache_read_input_tokens", "cache_creation_input_tokens")


def find_result(node, depth=0):
    """Deepest-first search for a dict carrying run metrics."""
    if depth > 6:
        return None
    if isinstance(node, dict):
        if any(k in node for k in ("total_cost_usd", "duration_ms", "usage")):
            return node
        for key in ("result", "data", "summary"):
            if key in node:
                hit = find_result(node[key], depth + 1)
                if hit:
                    return hit
        return None
    if isinstance(node, list):
        # stream-json: the terminal `result` event is last
        for item in reversed(node):
            hit = find_result(item, depth + 1)
            if hit:
                return hit
    return None


def load(path):
    with open(path) as fh:
        text = fh.read().strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # JSONL fallback
        events = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return events or None


def merge(results):
    """Sum metrics across passes (review, then refutation)."""
    if len(results) == 1:
        return results[0]
    total = {"usage": {}, "passes": len(results)}
    for key in ("duration_ms", "num_turns", "total_cost_usd"):
        vals = [r.get(key) for r in results if isinstance(r.get(key), (int, float))]
        if vals:
            total[key] = sum(vals)
    for key in USAGE_KEYS:
        vals = [(r.get("usage") or {}).get(key) for r in results]
        vals = [v for v in vals if isinstance(v, (int, float))]
        if vals:
            total["usage"][key] = sum(vals)
    # And the whole-run block, per model, or a two-pass footer would report
    # only whichever pass happened to be read first.
    merged_mu = {}
    for r in results:
        mu = r.get("modelUsage")
        if not isinstance(mu, dict):
            continue
        for name, rec in mu.items():
            if not isinstance(rec, dict):
                continue
            into = merged_mu.setdefault(name, {})
            for k, v in rec.items():
                if isinstance(v, (int, float)):
                    into[k] = into.get(k, 0) + v
    if merged_mu:
        total["modelUsage"] = merged_mu
    return total


# The CLI writes one journal per dispatched workflow. Overridable so
# review-local.sh and a test can point somewhere else.
DEFAULT_JOURNAL = os.path.expanduser(
    "~/.claude/projects/*/*/subagents/workflows/*/journal.jsonl")


def whole_run_usage(result):
    """Totals for the WHOLE run from `modelUsage`, or None if it is absent.

    `modelUsage` is keyed by model and its `costUSD` sums to `total_cost_usd`,
    which is what identifies it as the run-wide block rather than the Lead's.
    Summed across keys rather than reading one: a turn served by a fallback
    model adds a second key, and reporting only the first would quietly drop
    whatever that model did.
    """
    mu = result.get("modelUsage")
    if not isinstance(mu, dict) or not mu:
        return None
    out = {"input": 0, "cached": 0, "output": 0, "thinking": 0, "models": []}
    for name, rec in mu.items():
        if not isinstance(rec, dict):
            continue
        cached = rec.get("cacheReadInputTokens") or 0
        out["input"] += (rec.get("inputTokens") or 0) + cached \
            + (rec.get("cacheCreationInputTokens") or 0)
        out["cached"] += cached
        out["output"] += rec.get("outputTokens") or 0
        out["thinking"] += rec.get("thinkingTokens") or 0
        out["models"].append(str(name))
    if not out["models"]:
        return None
    out["models"].sort()
    return out


def lead_usage(result):
    """The Lead's own conversation, from `usage`. The fallback, and labelled."""
    usage = result.get("usage")
    if not isinstance(usage, dict) or not any(k in usage for k in USAGE_KEYS):
        return None
    got = {k: usage.get(k) or 0 for k in USAGE_KEYS}
    cached = got["cache_read_input_tokens"]
    return {"input": got["input_tokens"] + cached + got["cache_creation_input_tokens"],
            "cached": cached, "output": got["output_tokens"], "thinking": 0,
            "models": []}


def agent_count(pattern):
    """How many fleet agents were dispatched, counted from the journal(s).

    One `started` entry per dispatch, each with its own `agentId`. Keyed on
    (file, agentId) because ids are only unique within a workflow run, and a
    review that dispatched two workflows would otherwise merge them.

    Returns None when there is no journal at all -- which is the honest answer
    for the single-reviewer fallback, and is NOT the same as zero agents.
    """
    seen = set()
    found = False
    for path in sorted(glob.glob(pattern)):
        found = True
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(rec, dict) and rec.get("type") == "started" \
                            and rec.get("agentId"):
                        seen.add((path, rec["agentId"]))
        except OSError:
            continue
    return len(seen) if found else None


def human(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def dur(seconds):
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"
    if seconds >= 60:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds}s"


def main():
    review = os.environ.get("REVIEW_MD", "review.md")
    if not os.path.exists(review) or os.path.getsize(review) == 0:
        return

    bits = []
    model = os.environ.get("MODEL")
    if model:
        bits.append(f"`{model}`")

    tier = os.environ.get("TIER")
    if tier:
        bits.append(tier)

    # THE FIELD THIS FOOTER WAS MISSING. Under the fleet the Lead reads almost
    # nothing, so every number that describes the Lead understates the review;
    # this is the one that describes the machinery. Counted from the journal,
    # so it is a measurement rather than the model's account of itself.
    agents = agent_count(os.environ.get("JOURNAL") or DEFAULT_JOURNAL)
    if agents:
        bits.append(f"{agents} agents + lead")

    t0 = os.environ.get("T0")
    wall = None
    if t0:
        try:
            wall = time.time() - float(t0)
        except ValueError:
            wall = None
    if wall is not None:
        bits.append(f"{dur(wall)} wall")

    # De-duplicate: claude-code-action wrote both passes to one path, so an
    # unguarded list could contain the same file twice and merge() would sum a
    # pass with itself -- inflating turns, duration and cost on every two-pass
    # footer. The workflow now snapshots pass 1, but a footer that silently
    # doubles its numbers is bad enough to guard in both places.
    seen = set()
    paths = []
    for raw in os.environ.get("EXEC_FILE", "").split(","):
        path = raw.strip()
        if not path:
            continue
        key = os.path.realpath(path)
        if key in seen:
            print(f"telemetry: ignoring duplicate execution log {path}",
                  file=sys.stderr)
            continue
        seen.add(key)
        paths.append(path)
    results = []
    for path in paths:
        if not os.path.exists(path):
            continue
        try:
            found = find_result(load(path))
        except Exception as exc:                      # noqa: BLE001
            print(f"telemetry: could not parse {path}: {exc}", file=sys.stderr)
            continue
        if found:
            results.append(found)

    result = merge(results) if results else None

    if result:
        # Only when there is no wall clock to fall back on. It duplicates
        # `wall` to within a few seconds otherwise, and two near-identical
        # durations in one line is a field that costs a reader attention and
        # returns nothing.
        ms = result.get("duration_ms")
        if wall is None and isinstance(ms, (int, float)):
            bits.append(f"{dur(ms / 1000)} model")

        whole = whole_run_usage(result)
        scope = "run"
        if whole is None:
            # No `modelUsage`: an older CLI, or a shape this has not seen. Fall
            # back to the Lead's own numbers and SAY SO. Printing them unlabelled
            # beside a whole-run cost is the bug this rewrite exists to fix, and
            # a silent fallback would reintroduce it on the day the schema moves.
            whole = lead_usage(result)
            scope = "lead only"
        if whole:
            piece = f"{human(whole['input'])} in"
            if whole["cached"]:
                piece += f" ({human(whole['cached'])} cached)"
            piece += f" / {human(whole['output'])} out"
            if whole["thinking"] and whole["output"]:
                piece += f", {round(100 * whole['thinking'] / whole['output'])}% thinking"
            if scope != "run":
                piece += f" [{scope}]"
            bits.append(piece)
            # A run served by more than one model is worth seeing: it means a
            # fallback happened, and the tier's cost and depth are then not
            # what the tier table says they are.
            if len(whole["models"]) > 1:
                bits.append("served by " + ", ".join(f"`{m}`" for m in whole["models"]))

        cost = result.get("total_cost_usd")
        if isinstance(cost, (int, float)) and cost > 0:
            # Runs bill against a Claude subscription, not the API. This is the
            # API-rate equivalent -- useful for comparing PRs, not a charge.
            # Whole-run: it has always included the subagents, which is why it
            # was the only trustworthy number on the old footer.
            bits.append(f"~${cost:.2f} at API rates")

        # Last, and named for what it is. It measures the orchestrator, not the
        # review -- useful for spotting a Lead that thrashed, useless as a
        # proxy for effort, and unlabelled it was read as the latter.
        turns = result.get("num_turns")
        if isinstance(turns, int):
            passes = result.get("passes")
            bits.append(f"{turns} lead turns"
                        + (f" over {passes} passes" if passes else ""))
    elif paths:
        bits.append("token stats unavailable")

    run_url = os.environ.get("RUN_URL")
    if run_url:
        bits.append(f"[run]({run_url})")

    if not bits:
        return

    with open(review, "a") as fh:
        fh.write("\n\n---\n<sub>" + " · ".join(bits) + "</sub>\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:                          # noqa: BLE001
        print(f"telemetry: {exc}", file=sys.stderr)
    sys.exit(0)
