#!/usr/bin/env python3
"""One screen of "is the review bot working, and what has it found".

Reads only public data, so it needs no token:
  ./scripts/status.py

Env: REVIEW_REPO, UPSTREAM, LOG (the cron log), API.
"""
import collections
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = os.environ.get("API", "https://api.github.com")
REPO = os.environ.get("REVIEW_REPO", "xmrack/monero-review")
UPSTREAM = os.environ.get("UPSTREAM", "monero-project/monero")
LOG = os.environ.get("LOG", "/tmp/monero-review.log")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

NOW = datetime.datetime.now(datetime.timezone.utc)


def get(path, params=None):
    url = f"{API}{path}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "monero-review-status",
        **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}),
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def ts(s):
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc)


def ago(when):
    secs = int((NOW - when).total_seconds())
    if secs < 90:
        return f"{secs}s ago"
    if secs < 5400:
        return f"{secs // 60}m ago"
    if secs < 172800:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def section(title):
    print(f"\n\033[1m{title}\033[0m")


def main():
    print(f"\033[1mmonero-review\033[0m  {NOW:%Y-%m-%d %H:%MZ}  "
          f"{REPO} <- {UPSTREAM}")

    # ---- what has been reviewed, and did anything turn up ----
    issues = []
    for page in range(1, 11):
        try:
            batch = get(f"/repos/{REPO}/issues",
                        {"state": "all", "per_page": 100, "page": page})
        except urllib.error.HTTPError as exc:
            print(f"  could not read issues: HTTP {exc.code}", file=sys.stderr)
            break
        if not batch:
            break
        issues.extend(batch)
        if len(batch) < 100:
            break

    reviews = [i for i in issues if i["title"].startswith("Review:")]
    failures = [i for i in issues if i["title"].startswith("Review FAILED")]
    # A severity-tagged heading, not the section header: pass 1 sometimes emits
    # "## Findings" followed by "None." even though it is told to omit it.
    FINDING = re.compile(r"^###\s*\[(CRITICAL|HIGH|MEDIUM|LOW)", re.M)
    with_findings = [i for i in reviews
                     if FINDING.search(i.get("body") or "")]

    section("REVIEWED")
    print(f"  {len(reviews)} review(s): "
          f"{len(with_findings)} with findings, "
          f"{len(reviews) - len(with_findings)} clean")
    if failures:
        # Per SHA, not per PR: select_prs.py gives up on a SHA after
        # MAX_ATTEMPTS, so a PR that failed once at each of two different head
        # SHAs is still in the queue. Counting per PR reported it as abandoned.
        by_sha = collections.Counter()
        sha_pr = {}
        for f in failures:
            pr = re.search(r"#(\d+)", f["title"])
            for sha in re.findall(r"\b[0-9a-f]{12}\b", f["title"]):
                by_sha[sha] += 1
                if pr:
                    sha_pr[sha] = pr.group(1)
        stuck = sorted({sha_pr.get(sha, sha) for sha, n in by_sha.items()
                        if n >= 2})
        print(f"  {len(failures)} failed attempt(s)"
              + (f", gave up on PR(s) {', '.join(stuck)}" if stuck else ""))

    for i in with_findings:
        print(f"  \033[33m!\033[0m {i['title'][8:]}  -> {i['html_url']}")

    # ---- how much is left ----
    section("QUEUE")
    try:
        open_prs = []
        for page in range(1, 6):
            batch = get(f"/repos/{UPSTREAM}/pulls",
                        {"state": "open", "per_page": 100, "page": page,
                         "sort": "updated", "direction": "desc"})
            if not batch:
                break
            open_prs.extend(batch)
            if len(batch) < 100:
                break
        done = set()
        for i in issues:
            if not i["title"].startswith("Review FAILED"):
                done.update(re.findall(r"\b[0-9a-f]{12}\b", i["title"]))
        left = [p for p in open_prs
                if not p["draft"] and p["head"]["sha"][:12] not in done]
        # Says "before the doc-only filter" because it is: this runs with no
        # token by default, and separating the two would cost one file listing
        # per PR against a 60/hour anonymous budget. The selector does make
        # that split -- `ready` vs `docs` in a run's select log, and in every
        # published review's footer -- and the difference is not cosmetic: a
        # count of 13 here has meant 1 PR actually in line and 12 permanent
        # README edits.
        print(f"  {len(left)} unreviewed of {len(open_prs)} open upstream "
              f"(before the doc-only filter)")
    except urllib.error.HTTPError as exc:
        left = None
        print(f"  could not read upstream PRs: HTTP {exc.code}")

    # ---- rate and ETA ----
    if reviews:
        recent = [i for i in reviews
                  if (NOW - ts(i["created_at"])).total_seconds() < 86400]
        section("RATE")
        print(f"  {len(recent)} review(s) in the last 24h")
        if left and recent:
            days = len(left) / len(recent)
            print(f"  at that rate, {len(left)} remaining is ~{days:.0f} "
                  f"day(s) -- an upper bound, since some of those {len(left)} "
                  f"are doc-only and will never be picked")
        elif left:
            print("  nothing in the last 24h -- is the cron firing? (see CRON)")
        newest = max(reviews, key=lambda i: i["created_at"])
        print(f"  newest review {ago(ts(newest['created_at']))}"
              f"  ({newest['title'][8:]})")

    # ---- recent workflow runs ----
    section("RUNS")
    try:
        runs = get(f"/repos/{REPO}/actions/runs", {"per_page": 8})
        for r in runs.get("workflow_runs", [])[:6]:
            mark = {"success": "\033[32m+\033[0m",
                    "failure": "\033[31mx\033[0m"}.get(r["conclusion"], "~")
            concl = r["conclusion"] or r["status"]
            print(f"  {mark} {ts(r['created_at']):%m-%d %H:%M}Z  "
                  f"{r['event']:<18} {concl:<12} {ago(ts(r['created_at']))}")
        sched = [r for r in runs.get("workflow_runs", [])
                 if r["event"] == "schedule"]
        if not sched:
            print("  (no schedule-triggered runs -- expected, GitHub's "
                  "scheduler does not fire here; cron drives it)")
    except urllib.error.HTTPError as exc:
        print(f"  could not read runs: HTTP {exc.code}")

    # ---- is the local cron actually firing ----
    section("CRON")
    if os.path.exists(LOG):
        lines = [l.rstrip() for l in open(LOG, errors="replace") if l.strip()]
        hits = [l for l in lines if "dispatched" in l or "reviewing PR" in l]
        errs = [l for l in lines if "ERROR" in l]
        if hits:
            print(f"  last dispatch: {hits[-1]}")
        else:
            print(f"  {LOG} has no dispatch lines yet")
        if errs:
            print(f"  {len(errs)} error line(s), most recent:")
            print(f"    {errs[-1]}")
    else:
        print(f"  {LOG} does not exist -- cron has not run, or logs elsewhere")
        print("  check: crontab -l | grep monero")
    print()


if __name__ == "__main__":
    main()
