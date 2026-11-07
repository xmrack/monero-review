#!/usr/bin/env python3
"""Decide where a review is published: this public repository, or the private
disclosure repository.

    python3 scripts/disclosure.py [--verdict verdict.json] [review.md]   # decide
    python3 scripts/disclosure.py --severe review.md     # findings the gate must judge
    python3 scripts/disclosure.py --strip review.md      # body for the issue
    python3 scripts/disclosure.py --summary [--verdict verdict.json] review.md

Deciding prints two lines and nothing else:

    route=public|private
    reason=<why, or empty>

--severe prints the heading of every surviving CRITICAL or HIGH finding, one
per line, for the disclosure gate's prompt.

--strip prints the report with every disclosure marker removed, using the same
pattern that decided the route, so a marker that routed a review private can
never survive into the issue it files.

--summary prints a markdown list of every reason the review is private, each
naming the exact finding or change that met it, for the top of the private
issue.

NEVER echo the decision into the job log, and never hand it to a later step
through `env:` or a step output: GitHub prints a step's `env:` block in the
public log. This repository is public, and so are its run logs, step
summaries and artifacts. The workflow writes it to a file outside the
workspace, and each consumer reads that file inside its own `run:`.

A review goes private for one of two reasons, and nothing else:

  live-code     a CRITICAL or HIGH finding whose defect is in code that is
                already live: the base branch, a release, or a merged pull
                request. Publishing it is publishing a zero-day.
  critical-fix  the pull request patches a CRITICAL vulnerability in the
                code that is live now. A public review of the patch points at
                the hole before the release ships.

THE GATE DECIDES. scripts/disclosure_gate.md is a separate model pass that
runs after the review, reads the report, the diff and the base branch, and
writes a verdict (--verdict): each CRITICAL or HIGH finding placed in
`private` or `public` with one sentence why, and any critical fix. This
script checks the verdict against the report before using it. A verdict
that cites a finding the report does not have, leaves a CRITICAL or HIGH
finding out, or names a critical fix without saying what it patches, is
read as no verdict.

THE GATE CANNOT OVERRULE THE REPORT. These are private whatever it says:

  - a surviving CRITICAL or HIGH finding the report itself calls
    pre-existing (`not introduced by this pull request`, or `Where it came
    from.` opening on "Pre-existing");
  - a surviving CRITICAL or HIGH finding when `PR_STATE` in the environment
    is not `open` or `closed`: the pull request is merged, or its state is
    unknown;
  - a CRITICAL or HIGH entry under `## Fixed on master`, an entry there
    whose severity cannot be read, or a coverage stamp counting more fixed
    entries than the section holds. A fix on master is not a fix in a
    release.

WITH NO VERDICT, the review's own markers and provenance decide, and every
doubt is private: a `security-fix` or `live-code` marker, or a surviving
CRITICAL or HIGH finding that does not say it was introduced by this change
or is newly reachable through it.

Privacy, soundness and funds wording does not route a review on its own any
more. Those are severities: a privacy break or an inflation bug in live code
is rated HIGH or CRITICAL by the panel, and goes private as live-code.

FAILS CLOSED. A report that is missing, empty or unreadable, or a marker with
a reason this script does not know, routes private. Missing is the important
one: a run that died before writing its report still left a transcript full
of candidate findings, and "public" would let that reach a public artifact.
"""
import json
import os
import re
import sys

REFUTED_SECTION = re.compile(r"^##\s+Refuted\b", re.MULTILINE | re.IGNORECASE)

# The shapes labels.py reads, but looser on purpose: any heading whose first
# severity word is the finding's severity, wherever on the line it sits.
HEADING = re.compile(
    r"^#{2,6}[^\n]*?\b(CRITICAL|HIGH|MEDIUM|LOW)\b(?!-level)([^\n]*)",
    re.MULTILINE | re.IGNORECASE,
)
SECTION = re.compile(r"^##(?!#)[ \t]*(.*)", re.MULTILINE)
# Where a finding's block ends: the next finding, or the next section.
BLOCK_END = re.compile(r"^##", re.MULTILINE)
# Anywhere in the finding's block, not only on an exact locator line: a
# trailing full stop or a bolded path must not send a finding public. The
# `Where it came from.` block opening on "pre-existing" counts too.
PRE_EXISTING = re.compile(
    r"not\s+introduced\s+by\s+this\s+pull\s+request"
    r"|\*\*Where it came from\.?\*\*\s*\**\s*pre-?existing",
    re.IGNORECASE,
)
# The two provenances that make a finding this change's own. With no verdict,
# a surviving CRITICAL or HIGH that does not state one of them routes private.
INTRODUCED = re.compile(
    r"\*\*Where it came from\.?\*\*[\s*_]*"
    r"(introduced\s+by\s+this\s+(change|pull\s+request)|newly\s+reachable)",
    re.IGNORECASE,
)
# Searched over the WHOLE file: the marker sits at the foot, below
# `## Refuted`, beside the other stamps. Lazy and across lines, so neither a
# line break nor a `>` inside the comment hides it.
MARKER = re.compile(r"<!--\s*disclosure\b(.*?)-->", re.IGNORECASE | re.DOTALL)
# Any comment naming disclosure, so a misspelt marker is not read as none.
LOOSE_MARKER = re.compile(r"<!-(?:(?!-->).)*?\bdisclosure\b", re.IGNORECASE | re.DOTALL)
MARKER_REASON = re.compile(r"\breason\s*=\s*([a-z-]+)", re.IGNORECASE)
# privacy and funds are known so that a report written to the old spec is
# not read as carrying an unknown marker; they route nothing.
KNOWN_REASONS = ("security-fix", "live-code", "privacy", "funds")
# Entries a merged pull request's recheck found fixed on master. They sit below
# `## Refuted`, so the finding-heading rule above never sees them. The same
# three patterns are in labels.py; change them together.
FIXED_SECTION = re.compile(r"^##\s+Fixed on master\b[^\n]*$(.*?)(?=^##\s|\Z)",
                           re.MULTILINE | re.IGNORECASE | re.DOTALL)
FIXED_ENTRY = re.compile(r"^###\s+(.*)$", re.MULTILINE)
FIXED_WAS = re.compile(r"\(\s*was\s+(CRITICAL|HIGH|MEDIUM|LOW)\s*\)\s*$", re.IGNORECASE)
# Looser than FIXED_SECTION, the way HEADING is looser than labels.py: any
# heading level, bold or stray spacing. A section only this matches is one
# the strict parse cannot read, which routes private.
FIXED_SECTION_LOOSE = re.compile(r"^#{1,6}\s*[*_]*\s*Fixed\s+on\s+master", re.MULTILINE | re.IGNORECASE)
STAMP_FIXED = re.compile(r"<!--\s*deep-scan\b[^>]*?\sfixedOnMaster=(\d+)", re.IGNORECASE)
# The finding's locator, the line under its heading: `path:line` · `symbol`.
LOCATOR = re.compile(r"^\s*(`[^`\n]+`(?:\s*·\s*`[^`\n]+`)?)", re.MULTILINE)


def marked_refuted(match):
    """True when a heading's bracket, not its title, says refuted: a title
    like "bounds check refuted by the caller" is a finding like any other."""
    bracket = (match.group(2) or "").split("]", 1)
    return len(bracket) == 2 and bool(re.search(r"refuted", bracket[0], re.IGNORECASE))


def heading_title(line):
    return line.strip().lstrip("#").strip()


def severe_findings(text):
    """(heading, block) for every surviving CRITICAL or HIGH finding."""
    found = []
    for match in HEADING.finditer(text):
        if match.group(1).upper() not in ("CRITICAL", "HIGH"):
            continue
        if marked_refuted(match):
            continue
        section = None
        for section in SECTION.finditer(text, 0, match.start()):
            pass
        if section and REFUTED_SECTION.match(section.group(0)):
            continue
        end = BLOCK_END.search(text, match.end())
        found.append((heading_title(match.group(0)),
                      text[match.end():end.start() if end else len(text)]))
    return found


def locator(block):
    where = LOCATOR.search(block)
    return where.group(1) if where else ""


def reason(rule, finding, where, why):
    return {"rule": rule, "finding": finding, "where": where, "why": why}


def floor_reasons(text):
    """What routes private whatever the gate says."""
    found = []
    merged = os.environ.get("PR_STATE") not in ("open", "closed")
    for head, block in severe_findings(text):
        if PRE_EXISTING.search(block):
            found.append(reason("live-code", head, locator(block),
                                "The report says this finding predates the pull request, "
                                "so it is in live code."))
        elif merged:
            found.append(reason("live-code", head, locator(block),
                                "The pull request is merged, or its state could not be read, "
                                "so this finding is in live code."))
    sections = list(FIXED_SECTION.finditer(text))
    if len(FIXED_SECTION_LOOSE.findall(text)) > len(sections):
        found.append(reason("live-code", "a `Fixed on master` section", "",
                            "The section could not be read, so its entries may be "
                            "CRITICAL or HIGH and unreleased."))
    heads = [h.group(1) for m in sections for h in FIXED_ENTRY.finditer(m.group(1))]
    for head in heads:
        was = FIXED_WAS.search(head)
        if not was or was.group(1).upper() in ("CRITICAL", "HIGH"):
            found.append(reason("live-code", heading_title(head), "",
                                "Fixed on master but not in a release, or its severity "
                                "could not be read."))
    stamps = STAMP_FIXED.findall(text)
    if stamps and int(stamps[-1]) > len(heads):
        found.append(reason("live-code", "the coverage stamp", "",
                            f"It counts {stamps[-1]} fixed-on-master entries and the "
                            f"section holds {len(heads)}."))
    return found


def markers(text):
    """The reason on every disclosure marker, `unknown` for one whose reason
    is missing or not one we know."""
    found = []
    for match in MARKER.finditer(text):
        why = MARKER_REASON.search(match.group(1))
        found.append(why.group(1).lower() if why and why.group(1).lower() in KNOWN_REASONS
                     else "unknown")
    if not found and LOOSE_MARKER.search(text):
        found.append("unknown")
    return found


def fallback_reasons(text):
    """With no verdict: the review's markers and every CRITICAL or HIGH
    finding not plainly this change's own."""
    found = []
    marks = markers(text)
    if "security-fix" in marks:
        found.append(reason("critical-fix", "the pull request", "",
                            "The review marked it a security fix and the disclosure gate "
                            "gave no usable verdict."))
    for head, block in severe_findings(text):
        if "live-code" in marks or not INTRODUCED.search(block):
            found.append(reason("live-code", head, locator(block),
                                "The disclosure gate gave no usable verdict, and the report "
                                "does not show this finding is only in unmerged code."))
    return found


def verdict_reasons(text, verdict):
    """The gate's private reasons, or None when the verdict does not hold up
    against the report."""
    if not isinstance(verdict, dict):
        return None
    private, public = verdict.get("private"), verdict.get("public")
    if not isinstance(private, list) or not isinstance(public, list):
        return None
    severe = {same_finding(head): head for head, _ in severe_findings(text)}
    placed = set()
    found = []
    for is_private, entry in [(True, e) for e in private] + [(False, e) for e in public]:
        if not isinstance(entry, dict):
            return None
        why = entry.get("why")
        if not isinstance(why, str) or not why.strip():
            return None
        if is_private and entry.get("rule") == "critical-fix":
            if not all(isinstance(entry.get(k), str) and entry[k].strip()
                       for k in ("finding", "where")):
                return None
            found.append(reason("critical-fix", entry["finding"].strip(),
                                entry["where"].strip(), why.strip()))
            continue
        head = entry.get("finding")
        if not isinstance(head, str) or same_finding(head) not in severe:
            return None
        head = severe[same_finding(head)]
        placed.add(head)
        if is_private:
            if entry.get("rule") != "live-code":
                return None
            found.append(reason("live-code", head,
                                str(entry.get("where") or "").strip(), why.strip()))
    if placed != set(severe.values()):
        return None
    return found


def same_finding(title):
    """A heading as the gate may quote it: with or without its severity
    bracket, in any case and spacing."""
    title = re.sub(r"^\[[^\]]*\]\s*", "", title.strip().lstrip("#").strip())
    return " ".join(title.split()).casefold()


def read_verdict(path):
    if not path:
        return None
    try:
        with open(path, errors="replace") as fh:
            raw = fh.read()
    except OSError:
        return None
    # The gate answers with one JSON object, perhaps inside a fence.
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        return json.loads(raw[start:end + 1])
    except ValueError:
        return None


def reasons_for(text, verdict):
    """Every private reason, floor first, each finding once."""
    found = floor_reasons(text)
    if any(m == "unknown" for m in markers(text)):
        found.append(reason("unknown", "a disclosure marker", "",
                            "The marker's reason is not one this script knows."))
    gate = verdict_reasons(text, verdict)
    if gate is None:
        found += fallback_reasons(text)
        # A critical fix the gate named, in a verdict that did not hold up,
        # still counts.
        claimed = verdict.get("private") if isinstance(verdict, dict) else None
        for entry in claimed if isinstance(claimed, list) else []:
            if isinstance(entry, dict) and entry.get("rule") == "critical-fix":
                found.append(reason("critical-fix", str(entry.get("finding") or "the pull request"),
                                    str(entry.get("where") or ""),
                                    str(entry.get("why") or "The disclosure gate named a critical fix.")))
    else:
        found += gate
    seen, unique = set(), []
    for item in found:
        key = (item["rule"], item["finding"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique, gate is not None


def route(text, verdict=None):
    found, _ = reasons_for(text, verdict)
    if found:
        return "private", found[0]["rule"]
    return "public", ""


WHY = {
    "live-code": "A CRITICAL or HIGH finding is in code that is already live.",
    "critical-fix": "The pull request patches a CRITICAL vulnerability in live code.",
    "unknown": "A disclosure marker with a reason this script does not know. Routed private by default.",
}


def summary(text, verdict=None):
    """Every reason the report is private, with the exact finding or change
    that met it."""
    if not text.strip():
        return "**Why this is private**: the report is empty.\n"
    found, gated = reasons_for(text, verdict)
    lines = ["**Why this is private**", ""]
    for rule in WHY:
        items = [i for i in found if i["rule"] == rule]
        if not items:
            continue
        lines.append(f"- **{rule}**: {WHY[rule]}")
        for item in items:
            where = f" · {item['where']}" if item["where"] else ""
            lines.append(f"  - {item['finding']}{where}: {item['why']}")
    if not found:
        lines.append("- No reason could be read, so it routes private by default.")
    if not gated:
        lines += ["", "The disclosure gate gave no usable verdict, so the review's own "
                      "markers and provenance decided."]
    return "\n".join(lines) + "\n"


def strip(text):
    """The report with every marker, and the line it sat on when alone, cut."""
    text = re.sub(r"(?m)^[ \t]*" + MARKER.pattern + r"[ \t]*\n?", "", text,
                  flags=re.IGNORECASE | re.DOTALL)
    return MARKER.sub("", text)


def main():
    args = sys.argv[1:]
    verdict_path = None
    if "--verdict" in args:
        i = args.index("--verdict")
        verdict_path = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
    if args[:1] == ["--strip"]:
        path = args[1] if len(args) > 1 else "review.md"
        with open(path, errors="replace") as fh:
            sys.stdout.write(strip(fh.read()))
        return
    if args[:1] == ["--severe"]:
        path = args[1] if len(args) > 1 else "review.md"
        with open(path, errors="replace") as fh:
            for head, _ in severe_findings(fh.read()):
                print(head)
        return
    if args[:1] == ["--summary"]:
        path = args[1] if len(args) > 1 else "review.md"
        try:
            with open(path, errors="replace") as fh:
                sys.stdout.write(summary(fh.read(), read_verdict(verdict_path)))
        except Exception:  # noqa: BLE001 -- the summary must not block filing
            sys.stdout.write("**Why this is private**: the report could not be read.\n")
        return
    path = args[0] if args else "review.md"
    try:
        with open(path, errors="replace") as fh:
            text = fh.read()
    except OSError:
        # Missing included. See FAILS CLOSED above.
        where, why = "private", "none"
    else:
        if not text.strip():
            where, why = "private", "none"
        else:
            try:
                where, why = route(text, read_verdict(verdict_path))
            except Exception:  # noqa: BLE001 -- any parsing failure fails closed
                where, why = "private", "unreadable"
    print(f"route={where}")
    print(f"reason={why}")


if __name__ == "__main__":
    main()
