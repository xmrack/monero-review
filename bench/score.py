"""Score a bench/run.sh results directory against the cases.

    python3 -I bench/score.py bench/results/<tier>-<time> [--json]

A case is found when a published finding (not refuted) cites a file the patch
changed, within SLACK lines of a changed hunk. Its severity is compared with
the case's, and the categories researchers proposed at that spot with the
case's. On a control, every finding the report does not mark pre-existing is
a false positive.
"""
import glob
import json
import os
import re
import sys

SLACK = 25
SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
HERE = os.path.dirname(os.path.abspath(__file__))

FINDING = re.compile(r"^###\s*\[(CRITICAL|HIGH|MEDIUM|LOW)\]\s*(.*)$", re.M)
LOCATOR = re.compile(r"^`([^`:\n]+):(\d+)`(?:\s*·\s*`([^`\n]+)`)?([^\n]*)$", re.M)
SECTION = re.compile(r"^##(?!#)\s*(.*)$", re.M)
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)


def hunks(patch):
    """{file: [(start, end)]} in the head's line numbers."""
    out, current = {}, None
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            out.setdefault(current, [])
        m = HUNK.match(line)
        if m and current:
            start, count = int(m.group(3)), int(m.group(4) or 1)
            out[current].append((start, start + max(count, 1) - 1))
    return out


def findings(report):
    """Published findings: under `## Findings`, outside `## Refuted`."""
    out = []
    sections = [(m.start(), m.group(1).strip().lower()) for m in SECTION.finditer(report)]
    for m in FINDING.finditer(report):
        name = ""
        for pos, title in sections:
            if pos < m.start():
                name = title
        if not name.startswith("findings"):
            continue
        rest = report[m.end():]
        loc = LOCATOR.search(rest.split("\n### ", 1)[0])
        out.append({
            "severity": m.group(1),
            "title": m.group(2).strip(),
            "file": loc.group(1) if loc else None,
            "line": int(loc.group(2)) if loc else None,
            "symbol": loc.group(3) if loc else None,
            "preExisting": bool(loc and "not introduced by this pull request" in loc.group(4)),
        })
    return out


def near(finding, spans):
    ranges = spans.get(finding["file"] or "")
    if not ranges or finding["line"] is None:
        return False
    return any(a - SLACK <= finding["line"] <= b + SLACK for a, b in ranges)


def proposed_categories(result_dir, spans):
    """Categories researchers gave candidates near the changed hunks."""
    cats = set()
    for path in glob.glob(os.path.join(result_dir, "journal-*.jsonl")):
        for line in open(path, errors="replace"):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            r = e.get("result") if isinstance(e, dict) else None
            if not isinstance(r, dict):
                continue
            for c in r.get("candidates") or []:
                if not isinstance(c, dict):
                    continue
                f = {"file": c.get("file"), "line": c.get("line")}
                if isinstance(f["line"], int) and near(f, spans) and c.get("category"):
                    cats.add(c["category"])
    return sorted(cats)


def score_case(case, result_dir):
    patch = open(os.path.join(HERE, "cases", case["id"], "patch.diff")).read()
    spans = hunks(patch)
    review = os.path.join(result_dir, "review.md")
    if not os.path.exists(review):
        return {"id": case["id"], "split": case["split"], "status": "no-report"}
    found = findings(open(review, errors="replace").read())
    row = {"id": case["id"], "split": case["split"], "status": "ok",
           "findings": len(found)}
    if case["split"] == "control":
        fps = [f for f in found if not f["preExisting"]]
        row.update(falsePositives=len(fps),
                   falsePositiveTitles=[f"[{f['severity']}] {f['title']}" for f in fps])
        return row
    hits = [f for f in found if near(f, spans)]
    best = min(hits, key=lambda f: SEVERITIES.index(f["severity"])) if hits else None
    cats = proposed_categories(result_dir, spans)
    row.update(
        found=bool(best),
        severity=best["severity"] if best else None,
        expectedSeverity=case["severity"],
        severityOk=bool(best) and SEVERITIES.index(best["severity"]) <= SEVERITIES.index(case["severity"]),
        markedPreExisting=bool(best and best["preExisting"]),
        expectedCategory=case["category"],
        proposedCategories=cats,
        categoryOk=bool(set(cats) & set(case["category"])),
        unrelated=len(found) - len(hits),
    )
    return row


def pct(n, d):
    return f"{n}/{d} ({100 * n // d}%)" if d else "0/0"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    results = args[0]
    cases = [json.load(open(p)) for p in sorted(glob.glob(os.path.join(HERE, "cases", "*", "case.json")))]
    rows = [score_case(c, os.path.join(results, c["id"])) for c in cases
            if os.path.isdir(os.path.join(results, c["id"])) or os.path.exists(os.path.join(results, c["id"] + ".log"))]
    if "--json" in sys.argv:
        print(json.dumps(rows, indent=2))
        return

    print(f"# Benchmark: {os.path.basename(os.path.normpath(results))}\n")
    for split in ("catalogued", "held-out"):
        rs = [r for r in rows if r["split"] == split and r["status"] == "ok"]
        if not rs:
            continue
        found = [r for r in rs if r["found"]]
        print(f"**{split}:** found {pct(len(found), len(rs))}; "
              f"severity at or above expected {pct(sum(r['severityOk'] for r in found), len(found))}; "
              f"expected category proposed {pct(sum(r['categoryOk'] for r in rs), len(rs))}")
    ctl = [r for r in rows if r["split"] == "control" and r["status"] == "ok"]
    if ctl:
        print(f"**controls:** {sum(r['falsePositives'] for r in ctl)} false positive(s) "
              f"across {len(ctl)} clean change(s)")
    missing = [r["id"] for r in rows if r["status"] != "ok"]
    if missing:
        print(f"**no report:** {', '.join(missing)}")
    print("\n| case | found | severity (expected) | categories proposed (expected) | other findings |")
    print("| --- | --- | --- | --- | --- |")
    for r in rows:
        if r["status"] != "ok":
            print(f"| {r['id']} | no report | | | |")
        elif r["split"] == "control":
            print(f"| {r['id']} | control | | | {r['falsePositives']} false positive(s) |")
        else:
            sev = f"{r['severity'] or '-'} ({r['expectedSeverity']})"
            if r["markedPreExisting"]:
                sev += ", marked pre-existing"
            cats = f"{', '.join(r['proposedCategories']) or '-'} ({', '.join(r['expectedCategory'])})"
            print(f"| {r['id']} | {'yes' if r['found'] else 'NO'} | {sev} | {cats} | {r['unrelated']} |")

    by_cat = {}
    for r in rows:
        if r["status"] == "ok" and r["split"] != "control":
            by_cat.setdefault(r["expectedCategory"][0], []).append(r["found"])
    print("\n| category | found |\n| --- | --- |")
    for cat in sorted(by_cat):
        print(f"| {cat} | {pct(sum(by_cat[cat]), len(by_cat[cat]))} |")


if __name__ == "__main__":
    main()
