#!/usr/bin/env python3
"""Rewrite references to upstream pull requests and issues so GitHub does not
turn them into cross-reference events on the upstream repository.

    python3 scripts/neutralise.py FILE [UPSTREAM]

Rewrites FILE in place and prints how many references it rewrote. UPSTREAM
defaults to $UPSTREAM, then monero-project/monero.

GitHub files a reference event on the target for `owner/repo#N` and for a
github.com pull or issue URL -- a notification on a stranger's pull request,
from a pipeline whose premise is that it reads upstream without touching it.
Both shapes match case-insensitively on GitHub's side, and the URL form works
with or without the scheme and `www.`, so this does too. Everything becomes
`owner/repo PR N`, which GitHub leaves alone.
"""
import os
import re
import sys


def neutralise(text, upstream):
    repo = re.escape(upstream)
    url = re.compile(
        r"(?:https?://)?(?:www\.)?github\.com/" + repo
        + r"/(?:pull|issues)/(\d+)(?:/[^\s)\]>]*)?(?:#[^\s)\]>]*)?",
        re.IGNORECASE,
    )
    short = re.compile(r"(?<![\w/.-])" + repo + r"#(\d+)\b", re.IGNORECASE)
    count = 0

    def sub(match):
        nonlocal count
        count += 1
        return f"{upstream} PR {match.group(1)}"

    text = url.sub(sub, text)
    text = short.sub(sub, text)
    return text, count


def main():
    path = sys.argv[1]
    upstream = (sys.argv[2] if len(sys.argv) > 2
                else os.environ.get("UPSTREAM", "monero-project/monero"))
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    text, count = neutralise(text, upstream)
    if count:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(count)


if __name__ == "__main__":
    main()
