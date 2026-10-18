#!/usr/bin/env python3
"""Findings earlier reviews of a pull request published, as JSON on stdout.

Reads this repository's open review issues for the pull request -- only the
workflow's own or the repository owner's, titled `Review: <upstream>#<n> @
<sha>` -- at any head but the one under review, and returns one entry per `### [SEVERITY]` heading under
`## Findings`. Issues are never closed automatically, so the same finding
can appear in several; it is taken once, from the newest.

Usage: prior_findings.py <review-repo> <pr-number> <head-sha12>
Env:   GH_TOKEN (optional), API (optional base URL, for testing),
       REVIEW_BOT (issue author to trust, default github-actions[bot]; the
       repository owner is trusted too, for reviews run locally and filed by
       hand).

Prints `[]` on any failure: this is context, never a reason to lose a review.
"""
import json
import os
import re
import sys
import urllib.request

API = os.environ.get("API", "https://api.github.com")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
REVIEW_BOT = os.environ.get("REVIEW_BOT", "github-actions[bot]")
# A finding body is cut here; the reader re-reads the code anyway.
MAX_BODY = 2500
MAX_FINDINGS = 18


def get(path, params):
    url = f"{API}{path}?" + "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "monero-review",
        **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}),
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def findings_of(body):
    """(severity, title, text) for each finding under `## Findings`."""
    m = re.search(r"^## Findings[ \t]*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    if not m:
        return []
    out = []
    for part in re.split(r"^(?=### \[)", m.group(1), flags=re.M):
        h = re.match(r"### \[([A-Z]+)\][ \t]*(.*)\n", part)
        if not h:
            continue
        out.append((h.group(1), h.group(2).strip(), part[h.end():].strip()[:MAX_BODY]))
    return out


def main():
    repo, pr, head = sys.argv[1], sys.argv[2], sys.argv[3][:12]
    title_re = re.compile(rf"^Review: \S+#{re.escape(pr)} @ ([0-9a-f]{{12}})\b")
    issues = []
    for page in range(1, 11):
        rows = get(f"/repos/{repo}/issues", {
            "state": "open", "labels": f"pr-{pr}", "per_page": 100, "page": page})
        issues.extend(rows)
        if len(rows) < 100:
            break
    trusted = {REVIEW_BOT, repo.split("/")[0]}
    out, seen = [], set()
    # Newest first, so a finding repeated across reviews is taken once, from
    # the latest review that published it.
    for issue in sorted(issues, key=lambda i: i["number"], reverse=True):
        if "pull_request" in issue:
            continue
        if (issue.get("user") or {}).get("login") not in trusted:
            continue
        t = title_re.match(issue.get("title", ""))
        if not t or t.group(1) == head:
            continue
        for sev, title, text in findings_of(issue.get("body") or ""):
            key = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
            if key in seen:
                continue
            seen.add(key)
            out.append({"issue": issue["number"], "sha": t.group(1),
                        "severity": sev, "title": title, "body": text})
    print(json.dumps(out[:MAX_FINDINGS], indent=1))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 -- context only, never fatal
        print(f"warn: earlier findings could not be read ({exc})", file=sys.stderr)
        print("[]")
