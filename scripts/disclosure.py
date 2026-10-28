#!/usr/bin/env python3
"""Decide where a review is published: this public repository, or the private
disclosure repository.

    python3 scripts/disclosure.py [review.md]          # decide
    python3 scripts/disclosure.py --strip review.md    # body for the issue
    python3 scripts/disclosure.py --summary review.md [reason...]  # why it is private

Deciding prints two lines and nothing else:

    route=public|private
    reason=<why, or empty>

--strip prints the report with every disclosure marker removed, using the same
pattern that decided the route, so a marker that routed a review private can
never survive into the issue it files.

--summary prints a markdown list of every reason that applies, each with the
findings that met it, for the top of the private issue.

NEVER echo the decision into the job log, and never hand it to a later step
through `env:` or a step output: GitHub prints a step's `env:` block in the
public log. This repository is public, and so are its run logs, step
summaries and artifacts. The workflow writes it to a file outside the
workspace, and each consumer reads that file inside its own `run:`.

A review goes private when any of these holds:

  pre-existing  a CRITICAL or HIGH finding that survived the panel and is not
                this pull request's own. It is in code that is already live,
                so publishing it is publishing a zero-day.
  security-fix  the review carries `<!-- disclosure reason=security-fix -->`:
                the pull request is an obvious fix, by Monero developers, for a
                critical or high severity security bug -- a cryptographic flaw,
                a consensus bug, a remote crash. A public review of the patch
                points at the hole before the release ships.
  fixed-on-master  a CRITICAL or HIGH entry under `## Fixed on master`. A fix
                on master is not a fix in a release. Also any entry whose
                severity cannot be read, and a coverage stamp counting more
                fixed entries than the section holds.
  live-code     the review carries `<!-- disclosure reason=live-code -->`: a
                CRITICAL or HIGH finding that this pull request did not add to
                the surviving list as pre-existing, but which still affects
                code that is live (the change is already merged, or the same
                defect sits in the base branch or a release).
  merged        a surviving CRITICAL or HIGH finding when `PR_STATE` in the
                environment is not `open` or `closed`: the pull request is
                merged, or its state is unknown, so the code is live whatever
                the report says.
  privacy       a privacy break, at any severity: `privacy=N` on the stamp
                (missing counts), `reason=privacy`, or the report's text.
                Except a LOW finding in code an unmerged change introduces:
                the stamp leaves it out, and the text test skips its block.
                That matters only beside a finding above LOW; see EXCEPT.
  funds         a soundness, inflation or burning bug, on the same tests with
                `funds=N` and `reason=funds`.

EXCEPT a review whose findings are all LOW, or that has none, which is public
whatever the privacy and funds tests say. Only a `security-fix`, `live-code`
or unknown marker, or the pre-existing and fixed-on-master rules, still send
it private. Read strictly: every severity heading a plain `### [LOW]`, as many
as the stamp's `published=`, `unverified=0`, no non-zero `unaccounted=`,
nothing under `## Needs human review`, and no earlier finding above LOW quoted
anywhere, except a MEDIUM marked Fixed.

Anything else is public.

FAILS CLOSED. A report that is missing, empty or unreadable, or a marker with
a reason this script does not know, routes private. Missing is the important
one: a run that died before writing its report still left a transcript full
of candidate findings, and "public" would let that reach a public artifact.
Filing a harmless review in the private repository costs a maintainer a
minute; filing a harmful one in public cannot be undone.
"""
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
# The two provenances that make a finding this change's own, and so publishable
# here. A surviving CRITICAL or HIGH that does not state one of them routes
# private, so the default for an unclear report is the private repository.
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
STAMP = re.compile(r"<!--\s*deep-scan\b([^>]*)-->", re.IGNORECASE)
STAMP_PRIVACY = re.compile(r"\sprivacy=(\d+)\b", re.IGNORECASE)
STAMP_FUNDS = re.compile(r"\sfunds=(\d+)\b", re.IGNORECASE)
# Privacy-break wording.
_WHO = (r"(?:sender|recipient|receiver|payer|payee|origin(?!/)|real\s+(?:spend|input|output)|"
        r"true\s+spend|change\s+(?:amount|address|output|enote)|"
        r"which\s+(?:one|outputs?|address(?:es)?|wallets?|enotes?|inputs?))\b")
_LINK = (r"\b(?:links|linked|linking|link(?=\s+(?:the|a|an|its|their|that|this|these|those|"
         r"every|each|two|payments?|transactions?|them|it)\b))\b")
_TRACE = r"\b(?:(?:can|could|to|will|would)\s+trace|traces|tracing)\b"
_OBJ = (r"(?:sender|recipient|receiver|payer|payee|address(?:es)?|outputs?|enotes?|"
        r"transactions?|spends?|inputs?|key\s+images?|subaddress(?:es)?|wallets?|"
        r"identit(?:y|ies)|IP|payments?|origin(?!/))")
PRIVACY_BREAK = re.compile(
    r"de-?anonymi[sz]"
    r"|\b(?:un)?link(?:ab|ag)"
    r"|\b(?:un)?traceab"
    r"|anonymity\s+set"
    r"|\bdox(?:x|es|ed|ing)\b"
    r"|privacy\s+(?:break|leak|loss|regression|flaw|bug)"
    r"|\b(?:sender|recipient|receiver|payer|payee|user|owner)'s\s+(?:\w+\s+){0,2}(?:change|address|identity|"
    r"amount|outputs?|enotes?|balance|subaddress|keys?|secret|IP)\b"
    r"|" + _LINK + r"[^.\n]{0,60}\b" + _OBJ +
    r"|" + _TRACE + r"[^.\n]{0,40}\b" + _OBJ +
    r"|\b(?:identif(?:y|ies)|reveal(?:s|ed|ing)?|learn(?:s|ed)?|expos(?:e|es|ed)|"
    r"leak(?:s|ed)?|tells?|deduce(?:s|d)?|infer(?:s|red)?)\b[^.\n]{0,60}\b" + _WHO
    + r"|\b(?:wallet|transaction|tx|user|node)\s+fingerprint"
    r"|\bfingerprint(?:s|ed|ing)?\s+(?:the\s+|a\s+|its\s+)?(?:wallet|transaction|tx|user|node|sender)"
    r"|\bfingerprintab"
    r"|\bdistinguish(?:es|ed|able)?\b[^.\n]{0,40}\b(?:wallets?|transactions?|users?|txs?)\b",
    re.IGNORECASE,
)
PRIVACY_TOPIC = re.compile(r"\bdecoys?\b|\bring\s+members?\b|\bview[\s-]+tags?\b",
                           re.IGNORECASE)
DEFECT_SECTIONS = re.compile(r"^(?:findings|fixed on master|earlier findings|"
                             r"needs human review|comment discrepancy)\b", re.IGNORECASE)
# The title in an Earlier findings line: "· `#N` · <title> (was SEVERITY)".
EARLIER_TITLE = re.compile(r"`#\d+`\s*·[^\n]*?\(\s*was\s+(?:CRITICAL|HIGH|MEDIUM|LOW)\s*\)",
                           re.IGNORECASE)
# Soundness, inflation and burning wording.
_PROOF = (r"(?:proofs?|signatures?|range\s+proofs?|bulletproofs?|clsag|mlsag|"
          r"membership|commitments?|key\s+images?|sa/?l|ring\s+signatures?)")
FUNDS_BREAK = re.compile(
    r"\bunsound"
    r"|\b(?:breaks?|broken|loses?|lost|violat\w*)\s+(?:the\s+)?soundness\b"
    r"|\bsoundness\s+(?:bug|break|flaw|hole|failure|issue)"
    r"|\bforg(?:e|es|ed|ing|ery|eries)\b[^.\n]{0,40}\b" + _PROOF +
    r"|\b" + _PROOF + r"\b[^.\n]{0,40}\bforg(?:e|es|ed|ing|ery|eries)\b"
    r"|\binflation\s+(?:bug|attack|flaw|hole)|\binflates?\s+(?:the\s+)?(?:supply|money\s+supply|coins?)"
    r"|\bcounterfeit"
    r"|\b(?:create|creates|created|creating|mint|mints|minted|minting|print|prints)\b[^.\n]{0,30}"
    r"\b(?:monero|xmr|coins?|money|funds)\b[^.\n]{0,20}\b(?:from\s+nothing|out\s+of\s+(?:thin\s+air|nothing)|that\s+do(?:es)?\s+not\s+exist)"
    r"|\b(?:can|could|lets?|allows?|enables?|to)\b[^.\n]{0,40}\bdouble[\s-]+spend\b"
    r"|\bspen(?:d|ds|t)\s+(?:the\s+same|one|an?)\s+(?:output|enote|coin|key\s+image)s?\s+(?:twice|more\s+than\s+once)"
    r"|\bburn(?:s|ed|t|ing)?\b[^.\n]{0,40}\b(?:outputs?|enotes?|funds|coins?|monero|xmr|amounts?|payments?)\b"
    r"|\b(?:outputs?|enotes?|funds|coins?|monero|xmr|amounts?|payments?)\b[^.\n]{0,40}\bburn(?:s|ed|t|ing)?\b"
    r"|\bburning\s+bug"
    r"|\bunspendable\b"
    r"|\b(?:can|could)\s*not\s+(?:ever\s+)?be\s+spent\b|\bnever\s+be\s+spent\b"
    r"|\bpermanently\s+(?:lost|locked|unspendable)\b",
    re.IGNORECASE,
)
FUNDS_TOPIC = re.compile(r"\bsoundness\b|\binflation\b|\bdouble[\s-]+spen(?:d|ds|t|ding)\b",
                         re.IGNORECASE)
SAFE_SECTIONS = re.compile(r"^(?:refuted|checked and clear|coverage)\b", re.IGNORECASE)


def marked_refuted(match):
    """True when a heading's bracket, not its title, says refuted: a title
    like "bounds check refuted by the caller" is a finding like any other."""
    bracket = (match.group(2) or "").split("]", 1)
    return len(bracket) == 2 and bool(re.search(r"refuted", bracket[0], re.IGNORECASE))


def severe_pre_existing(text):
    """True when a surviving CRITICAL or HIGH finding predates the PR, or does
    not say that it does not."""
    return bool(pre_existing_findings(text))


def heading_title(line):
    return line.strip().lstrip("#").strip()


def pre_existing_findings(text):
    """The headings of the findings severe_pre_existing counts."""
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
        block = text[match.end():end.start() if end else len(text)]
        if PRE_EXISTING.search(block) or not INTRODUCED.search(block):
            found.append(heading_title(match.group(0)))
    return found


def merged_findings(text):
    """The surviving CRITICAL and HIGH findings, when the pull request may be
    merged."""
    if os.environ.get("PR_STATE") in ("open", "closed"):
        return []
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
        found.append(heading_title(match.group(0)))
    return found


def severe_fixed_on_master(text):
    """True when a fixed-on-master entry is CRITICAL or HIGH, or cannot be read.

    Fails closed: an entry heading without `(was SEVERITY)`, or a stamp
    counting more entries than the section holds, counts as severe."""
    return bool(fixed_on_master_findings(text))


def fixed_on_master_findings(text):
    """The entries severe_fixed_on_master counts, or a note on what could not
    be read."""
    sections = list(FIXED_SECTION.finditer(text))
    if len(FIXED_SECTION_LOOSE.findall(text)) > len(sections):
        return ["a `Fixed on master` section that could not be read"]
    heads = [h.group(1) for m in sections for h in FIXED_ENTRY.finditer(m.group(1))]
    found = []
    for head in heads:
        was = FIXED_WAS.search(head)
        if not was or was.group(1).upper() in ("CRITICAL", "HIGH"):
            found.append(heading_title(head))
    stamps = STAMP_FIXED.findall(text)
    if stamps and int(stamps[-1]) > len(heads):
        found.append(f"the stamp counts {stamps[-1]} fixed entries, the section holds {len(heads)}")
    return found


def stamp_counts(text, field):
    """True when the stamp counts one, or there is no stamp or no count on
    it: an unknown count is treated as a non-zero one."""
    stamps = STAMP.findall(text)
    count = field.search(" " + stamps[-1]) if stamps else None
    return not count or int(count.group(1)) > 0


def reporting_sections(text):
    """(name, body) for every section that reports a problem: all but
    `## Refuted`, `## Checked and clear` and `## Coverage`. The preamble,
    with the title and the Result line, is the one named ""."""
    bounds = [(m.start(), m.group(1).strip()) for m in SECTION.finditer(text)]
    starts = [0] + [b[0] for b in bounds]
    names = [""] + [b[1] for b in bounds]
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        name = names[i].lstrip("*_ ")
        if not SAFE_SECTIONS.match(name):
            yield name, STAMP.sub("", text[start:end])


def without_low_introduced(text):
    """The report without the block of any LOW finding introduced by this
    change. Its locator must not say pre-existing or newly reachable."""
    cuts = []
    for match in HEADING.finditer(text):
        head = match.group(0)
        if not re.match(r"###[ \t]+\[LOW\][ \t]", head) or re.search(r"\b(?:CRITICAL|HIGH|MEDIUM)\b", head, re.IGNORECASE):
            continue
        section = None
        for section in SECTION.finditer(text, 0, match.start()):
            pass
        if not section or not re.match(r"findings\b", section.group(1).strip(), re.IGNORECASE):
            continue
        end = BLOCK_END.search(text, match.end())
        block = text[match.end():end.start() if end else len(text)]
        made = INTRODUCED.search(block)
        if made and made.group(1).lower().startswith("introduced") and not PRE_EXISTING.search(block):
            cuts.append((match.start(), end.start() if end else len(text)))
    for start, stop in reversed(cuts):
        text = text[:start] + text[stop:]
    return text


def privacy_break(text):
    """True when the stamp counts a privacy break or lacks the count, or any
    section that reports a problem reads like one."""
    return bool(privacy_findings(text))


def funds_break(text):
    """The same, for a soundness, inflation or burning bug."""
    return bool(funds_findings(text))


def stamp_note(text, field, name):
    """Why the stamp counts, or None when it does not."""
    if not stamp_counts(text, field):
        return None
    stamps = STAMP.findall(text)
    count = field.search(" " + stamps[-1]) if stamps else None
    if not count:
        return f"the scan stamp has no `{name}=` count, which counts as one"
    return (f"the scan stamp counts {count.group(1)} {name} candidate(s), refuted ones "
            "included; it does not name them")


def text_findings(text, matches):
    """Where `matches(section name, chunk)` returns a match, per finding: the
    heading of each matching finding, or the section's name for text above its
    first, with the words that matched."""
    found = []
    for name, body in reporting_sections(text):
        # An earlier finding's title is quoted from this repository's public
        # issues only (prior_findings.py), so its words are public already.
        # What the run wrote about it is read as usual.
        if re.match(r"earlier findings\b", name, re.IGNORECASE):
            body = EARLIER_TITLE.sub("", body)
        for i, chunk in enumerate(re.split(r"(?m)^(?=#{3,6}\s)", body)):
            hit = matches(name, chunk)
            if not hit:
                continue
            label = heading_title(chunk.split("\n", 1)[0]) if i else (f"the `{name}` section" if name else "the report's opening")
            words = " ".join(hit.group(0).split())[:80]
            found.append(f"{label}: matched \"{words}\"")
    return found


def privacy_findings(text):
    note = stamp_note(text, STAMP_PRIVACY, "privacy")
    return ([note] if note else []) + text_findings(
        without_low_introduced(text),
        lambda name, body: PRIVACY_BREAK.search(body)
        or (DEFECT_SECTIONS.match(name) and PRIVACY_TOPIC.search(body)))


def funds_findings(text):
    note = stamp_note(text, STAMP_FUNDS, "funds")
    return ([note] if note else []) + text_findings(
        text,
        lambda name, body: FUNDS_BREAK.search(body)
        or ((name == "" or DEFECT_SECTIONS.match(name)) and FUNDS_TOPIC.search(body)))


def only_low(text):
    """True when the report's findings are all LOW, or it has none. See the
    docstring."""
    stamps = STAMP.findall(text)
    if not stamps:
        return False
    published = re.search(r"\spublished=(\d+)\b", " " + stamps[-1])
    unverified = re.search(r"\sunverified=(\d+)\b", " " + stamps[-1])
    unaccounted = re.search(r"\sunaccounted=(\d+)\b", " " + stamps[-1])
    if not published or not unverified or int(unverified.group(1)) or \
            (unaccounted and int(unaccounted.group(1))):
        return False
    lows = 0
    for name, body in reporting_sections(text):
        if re.match(r"needs human review\b", name, re.IGNORECASE) and body.partition("\n")[2].strip():
            return False
        # An earlier finding above LOW, quoted here, may be a private one.
        for line in body.splitlines():
            was = re.search(r"\(\s*was\s+(CRITICAL|HIGH|MEDIUM)\s*\)", line, re.IGNORECASE)
            if was and (was.group(1).upper() != "MEDIUM" or not re.match(r"[-*\s]*\**Fixed\b", line)):
                return False
        for match in HEADING.finditer(body):
            head = match.group(0)
            if not re.match(r"###[ \t]+\[LOW\][ \t]", head) or \
                    re.search(r"\b(?:CRITICAL|HIGH|MEDIUM)\b", head, re.IGNORECASE):
                return False
            if re.match(r"findings\b", name, re.IGNORECASE):
                lows += 1
    return lows == int(published.group(1))


def markers(text):
    """The reason on every disclosure marker, `unknown` for one whose reason
    is missing or not one we know."""
    found = []
    for match in MARKER.finditer(text):
        reason = MARKER_REASON.search(match.group(1))
        found.append(reason.group(1).lower() if reason and reason.group(1).lower() in KNOWN_REASONS
                     else "unknown")
    if not found and LOOSE_MARKER.search(text):
        found.append("unknown")
    return found


def route(text):
    reasons = markers(text)
    for reason in reasons:
        if reason not in ("privacy", "funds"):
            return "private", reason
    if severe_pre_existing(text):
        return "private", "pre-existing"
    if merged_findings(text):
        return "private", "merged"
    if severe_fixed_on_master(text):
        return "private", "fixed-on-master"
    if only_low(text):
        return "public", ""
    if reasons:
        return "private", reasons[0]
    if privacy_break(text):
        return "private", "privacy"
    if funds_break(text):
        return "private", "funds"
    return "public", ""


WHY = {
    "security-fix": "The pull request fixes a critical or high severity security bug. "
                    "A public review would point at it before a release ships.",
    "live-code": "A CRITICAL or HIGH finding affects code that is already live.",
    "unknown": "A disclosure marker with a reason this script does not know. Routed private by default.",
    "pre-existing": "A CRITICAL or HIGH finding is not this pull request's own, so it is "
                    "already in live code.",
    "merged": "A CRITICAL or HIGH finding in a pull request that is merged, or whose state "
              "could not be read, so the code is live.",
    "previously-private": "An earlier review of this pull request is still open here.",
    "fixed-on-master": "A CRITICAL or HIGH finding is fixed on master but not yet in a release, "
                       "or its severity could not be read.",
    "privacy": "A privacy break in a review that has a finding above LOW.",
    "funds": "A soundness, inflation or burning bug.",
}


def summary(text, extra=()):
    """Every reason the report is private, each once, with what met it, after
    any reasons the workflow decided itself."""
    reasons = {reason: [] for reason in extra if reason in WHY}
    if not text.strip():
        return "**Why this is private**: the report is empty.\n"
    for marker in markers(text):
        reasons.setdefault(marker, [])
    for reason, find in (("pre-existing", pre_existing_findings),
                         ("merged", merged_findings),
                         ("fixed-on-master", fixed_on_master_findings),
                         ("privacy", privacy_findings), ("funds", funds_findings)):
        found = find(text)
        if found:
            reasons.setdefault(reason, []).extend(found)
    lines = ["**Why this is private**", ""]
    for reason, found in reasons.items():
        lines.append(f"- **{reason}**: {WHY[reason]}")
        lines.extend(f"  - {item}" for item in found)
    if not reasons:
        lines.append("- No reason could be read, so it routes private by default.")
    return "\n".join(lines) + "\n"


def strip(text):
    """The report with every marker, and the line it sat on when alone, cut."""
    text = re.sub(r"(?m)^[ \t]*" + MARKER.pattern + r"[ \t]*\n?", "", text,
                  flags=re.IGNORECASE | re.DOTALL)
    return MARKER.sub("", text)


def main():
    args = sys.argv[1:]
    if args[:1] == ["--strip"]:
        path = args[1] if len(args) > 1 else "review.md"
        with open(path, errors="replace") as fh:
            sys.stdout.write(strip(fh.read()))
        return
    if args[:1] == ["--summary"]:
        path = args[1] if len(args) > 1 else "review.md"
        try:
            with open(path, errors="replace") as fh:
                sys.stdout.write(summary(fh.read(), args[2:]))
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
                where, why = route(text)
            except Exception:  # noqa: BLE001 -- any parsing failure fails closed
                where, why = "private", "unreadable"
    print(f"route={where}")
    print(f"reason={why}")


if __name__ == "__main__":
    main()
