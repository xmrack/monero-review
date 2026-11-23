#!/usr/bin/env python3
"""Findings the private disclosure repository holds, as JSON on stdout.

    private_findings.py <disclosure-repo> > private.json

Reads every OPEN issue in the disclosure repository: an open issue is still
under embargo, and a closed one has been released or dismissed. For each it
returns the pull request number from its title, whether it is an unverified
report, and every finding heading outside `## Refuted`, with severity and
locator.

disclosure.py reads this to keep a review public only when none of its
findings was reported privately first. A later run can rate the same defect
lower, or word it differently, and the severity rules alone would then
publish it.

NEVER print what this returns, its size or its count: the log is public.

Exits 1 on any failure. The workflow then writes `{"ok": false}`, and
disclosure.py routes private: an unchecked review may repeat an embargoed
finding.

Env: GH_TOKEN (the disclosure token), API (optional base URL, for testing).
"""
import json
import os
import re
import sys
import time
import urllib.request

API = os.environ.get("API", "https://api.github.com")
TOKEN = os.environ.get("GH_TOKEN", "")
TITLE = re.compile(r"^(Unverified review|Review): \S+?(?:#| PR )(\d+) @ ")
HEADING = re.compile(r"^#{2,6}[^\n]*?\b(CRITICAL|HIGH|MEDIUM|LOW)\b(?!-level)[^\n]*",
                     re.MULTILINE | re.IGNORECASE)
REFUTED = re.compile(r"^##\s+Refuted\b[^\n]*$(.*?)(?=^##(?!#)|\Z)",
                     re.MULTILINE | re.IGNORECASE | re.DOTALL)
LOCATOR = re.compile(r"^\s*(`[^`\n]+`(?:\s*·\s*`[^`\n]+`)?)", re.MULTILINE)


def get(path, params):
    url = f"{API}{path}?" + "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "monero-review",
        "Authorization": f"Bearer {TOKEN}",
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except Exception:  # noqa: BLE001 -- retried, then fatal
            if attempt == 2:
                raise
            time.sleep(10 * (attempt + 1))


def findings_of(body):
    body = REFUTED.sub("", body)
    out = []
    for match in HEADING.finditer(body):
        rest = body[match.end():]
        end = re.search(r"^#", rest, re.MULTILINE)
        where = LOCATOR.search(rest[:end.start() if end else len(rest)])
        out.append({"severity": match.group(1).upper(),
                    "title": match.group(0).strip().lstrip("#").strip(),
                    "where": where.group(1) if where else ""})
    return out


def main():
    if not TOKEN:
        sys.exit(1)
    repo = sys.argv[1]
    issues = []
    for page in range(1, 51):
        rows = get(f"/repos/{repo}/issues", {"state": "open", "per_page": 100, "page": page})
        if not isinstance(rows, list):
            sys.exit(1)
        issues.extend(rows)
        if len(rows) < 100:
            break
    else:
        sys.exit(1)
    out = []
    for issue in issues:
        if "pull_request" in issue:
            continue
        title = TITLE.match(issue.get("title") or "")
        out.append({"issue": issue["number"],
                    "pr": title.group(2) if title else "",
                    "unverified": bool(title) and title.group(1) != "Review",
                    "findings": findings_of(issue.get("body") or "")})
    json.dump({"ok": True, "issues": out}, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 -- any failure routes private
        sys.exit(1)
