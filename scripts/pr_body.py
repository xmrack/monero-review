#!/usr/bin/env python3
"""Assemble the body of a reference-corrections pull request.

    RUN_URL=... pr_body.py <out.md> [SUMMARY.md] [SKIPPED.md] [proposals.json]

The writer produces prose; this turns it into something that renders on GitHub
and says where its claims came from. Four jobs, and each exists because the
published pull requests got it wrong:

1. PROVENANCE. A correction is observed while reading some upstream pull
   request's HEAD -- the target branch plus that author's unmerged changes.
   The references describe the target branch. So "line 14523" in a correction
   may be a line only that pull request has, and a reader of the body could not
   tell: nothing in it named the tree. The block this writes names the pull
   request, its head and its base, and says plainly which of the two a citation
   describes.

2. HEADINGS. The caller used to print `### Skipped` and then cat a SKIPPED.md
   that opened with its own `# Skipped`, so the body carried the heading twice,
   the second as an H1 -- larger than anything around it. Headings from the
   writer are demoted to H3 and a leading heading that merely repeats the
   section name is dropped.

3. WRAPPED CODE SPANS. The writer hard-wraps at about 80 columns, including
   inside backticks. A code span containing a newline renders with the newline
   AND the continuation line's indent collapsed into the code, so
   `drop_connection(context, false,\n  false)` shows up with a gap in the
   middle of the call. Whitespace inside a span that got wrapped is collapsed
   to one space.

4. HARD-WRAPPED PARAGRAPHS. GitHub renders a single newline inside an issue or
   pull request body as a visible line break -- unlike a plain markdown file
   read elsewhere, where the same newline is a soft break and the paragraph
   flows as one line. The writer hard-wraps at about 80 columns on the
   assumption that it does not matter outside a code span; on GitHub it does,
   and a hard-wrapped bullet publishes as a stack of short lines that break
   well before the reader's actual line width. Lines that are part of the same
   paragraph or list item are rejoined with a single space; a heading, a list
   marker's own first line, a block quote, a table row, a thematic break and a
   blank line each stay exactly where they are, so no visible structure moves.

Exit status is always 0 where it can be. A body that fails to assemble would
throw away a correction the pipeline already paid to find, so every failure
degrades to writing what it has.
"""
import json
import os
import re
import sys

# A fenced block is copied out verbatim: everything below reflows or rewrites
# text, and none of it may touch what is inside a fence.
FENCE = re.compile(r"^(\s*)(```+|~~~+)")
# Inline code, shortest run of backticks first, across line breaks. The body is
# markdown the writer produced, so this sees the same spans GitHub will.
CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.DOTALL)
HEADING = re.compile(r"^(#{1,6})(\s+)(.*)$")
# Lines that must never be folded into a neighbour: each stays exactly where
# it is, and each also ends whatever paragraph or list item came before it.
LIST_MARKER = re.compile(r"^\s*([-*+]|\d+[.)])(\s+|$)")
BLOCK_QUOTE = re.compile(r"^\s*>")
TABLE_ROW = re.compile(r"^\s*\|")
THEMATIC_BREAK = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")


def split_fences(text):
    """Yield (is_fenced, chunk) so rewrites can skip fenced blocks."""
    out, buf, fence = [], [], None
    for line in text.split("\n"):
        m = FENCE.match(line)
        if fence is None and m:
            if buf:
                out.append((False, "\n".join(buf)))
                buf = []
            fence = m.group(2)[0] * 3
            buf.append(line)
        elif fence is not None:
            buf.append(line)
            if m and m.group(2).startswith(fence):
                out.append((True, "\n".join(buf)))
                buf, fence = [], None
        else:
            buf.append(line)
    if buf:
        out.append((fence is not None, "\n".join(buf)))
    return out


def unwrap_code_spans(text):
    """Collapse whitespace inside inline code that was hard-wrapped."""
    def fix(m):
        inner = m.group(2)
        if "\n" not in inner:
            return m.group(0)
        return m.group(1) + " ".join(inner.split()) + m.group(1)
    return CODE_SPAN.sub(fix, text)


def _standalone(line):
    """A line that is never folded into a neighbour, in either direction."""
    return (not line.strip() or HEADING.match(line) or BLOCK_QUOTE.match(line)
            or TABLE_ROW.match(line) or THEMATIC_BREAK.match(line))


def unwrap_paragraphs(text):
    """Rejoin a paragraph or list item the writer hard-wrapped across lines.

    GitHub turns a single newline inside an issue or pull request body into a
    visible line break, so text hard-wrapped at ~80 columns -- fine in a plain
    markdown file, where the same newline is a soft break -- publishes as a
    stack of short lines instead of the paragraph it was written as. A line
    that opens a list item starts a fresh line of its own; anything that
    follows it without itself being standalone or a new list item is a
    continuation and is folded back onto it with a single space.
    """
    out, buf = [], []

    def flush():
        if buf:
            out.append(" ".join(part.strip() for part in buf))
            buf.clear()

    for line in text.split("\n"):
        if _standalone(line):
            flush()
            out.append(line)
        elif LIST_MARKER.match(line):
            flush()
            buf.append(line)
        else:
            buf.append(line)
    flush()
    return "\n".join(out)


def demote_headings(text, floor=3):
    """Push every heading to `floor` or deeper, keeping relative depth."""
    lines = text.split("\n")
    seen = [len(m.group(1)) for m in
            (HEADING.match(l) for l in lines) if m]
    if not seen:
        return text
    bump = max(0, floor - min(seen))
    if not bump:
        return text
    out = []
    for line in lines:
        m = HEADING.match(line)
        if m:
            level = min(6, len(m.group(1)) + bump)
            line = "#" * level + m.group(2) + m.group(3)
        out.append(line)
    return "\n".join(out)


def drop_leading_heading(text, word):
    """Drop a first heading that only repeats the section name."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        m = HEADING.match(line)
        if m and m.group(3).strip().strip(":").lower() == word.lower():
            return "\n".join(lines[i + 1:]).lstrip("\n")
        return text
    return text


def clean_block(text, floor=3, drop=None):
    """Normalise one writer-produced block, leaving fenced code alone."""
    parts = []
    for fenced, chunk in split_fences(text):
        if fenced:
            parts.append(chunk)
            continue
        chunk = unwrap_code_spans(chunk)
        chunk = unwrap_paragraphs(chunk)
        chunk = demote_headings(chunk, floor)
        parts.append(chunk)
    out = "\n".join(parts)
    if drop:
        out = drop_leading_heading(out, drop)
    return out.strip("\n")


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def sources(path):
    """The distinct reviewed pull requests behind these corrections."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            entries = json.load(fh)
    except (OSError, ValueError):
        return []
    if not isinstance(entries, list):
        return []
    seen, out = set(), []
    for e in entries:
        if not isinstance(e, dict):
            continue
        s = e.get("source")
        if not isinstance(s, dict):
            continue
        key = (s.get("upstream"), s.get("pr"), s.get("head"), s.get("base"))
        if not all(key) or key in seen:
            continue
        seen.add(key)
        out.append(dict(zip(("upstream", "pr", "head", "base"), key)))
    return out


def provenance(found):
    """The block that says which tree the citations below describe."""
    if not found:
        # Said plainly rather than omitted. A body with no provenance block at
        # all reads like one where provenance did not matter.
        return (
            "> **Where these observations come from: not recorded.** This run "
            "carried no reviewed-pull-request context, so the citations below "
            "cannot be attributed to a tree. Treat every line number and "
            "symbol as unverified until checked against the branch the "
            "reference describes."
        )
    lines = ["> **Where these observations come from.**", ">"]
    for s in found:
        lines.append(
            "> - `%s#%s` at head `%s`, which targets `%s`."
            % (s["upstream"], s["pr"], s["head"], s["base"])
        )
    lines += [
        ">",
        "> Every line number, symbol and quoted source below was read from "
        "**that pull request's head** -- the target branch plus changes that "
        "are not merged. The reference files describe the target branch "
        "itself. Where the change moved or added what a citation names, the "
        "correction describes the pull request and not Monero, and merging it "
        "here would write an unmerged branch's state into a file that claims "
        "to describe the tree.",
        ">",
        "> So check each citation against the base branch before merging. "
        "Nothing in this repository outside `.claude/references/` is touched "
        "by this pull request, whatever the prose below discusses.",
    ]
    return "\n".join(lines)


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "body.md"
    summary = sys.argv[2] if len(sys.argv) > 2 else "SUMMARY.md"
    skipped = sys.argv[3] if len(sys.argv) > 3 else "SKIPPED.md"
    proposals = sys.argv[4] if len(sys.argv) > 4 else "proposals.json"

    parts = [provenance(sources(proposals))]

    body = clean_block(read(summary))
    if body:
        parts.append(body)

    tail = clean_block(read(skipped), drop="Skipped")
    if tail:
        parts += ["### Skipped", tail]

    run_url = os.environ.get("RUN_URL", "")
    parts.append(
        "Opened by the review pipeline%s. The job that wrote these corrections "
        "has no Monero checkout and verified none of them against the tree; "
        "that is what a reviewer is for."
        % (" from %s" % run_url if run_url else "")
    )
    parts.append("---\n_Generated by [Claude Code](https://claude.ai/code)_")

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(parts).strip() + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:                          # noqa: BLE001
        print("pr-body: %s" % exc, file=sys.stderr)
        # Never lose the writer's prose to a formatting bug.
        try:
            with open(sys.argv[1] if len(sys.argv) > 1 else "body.md",
                      "w", encoding="utf-8") as fh:
                fh.write(read("SUMMARY.md") or "(no summary)\n")
        except OSError:
            pass
