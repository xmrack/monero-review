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

Outside code, it also formats @mentions as code, shows links outside
github.com as plain text, and leaves out images hosted elsewhere.
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


LINK_HOSTS = ("github.com", "www.github.com")
CODE = re.compile(r"(^```.*?^```[^\n]*$|^~~~.*?^~~~[^\n]*$|(?<![\\`])(`+)(?!`)[^\n]*?(?<!`)\2(?!`))",
                  re.MULTILINE | re.DOTALL)
MENTION = re.compile(r"(?<![\w/.@-])@([A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:/[A-Za-z0-9_.-]+)?)\b")
IMAGE = re.compile(r"!\[([^\]]*)\]\(\s*<?([^)\s>]+)>?[^)]*\)")
MDLINK = re.compile(r"(?<!!)\[([^\]]*)\]\(\s*<?([^)\s>]+)>?[^)]*\)")
AUTOLINK = re.compile(r"<(https?://[^>\s]+)>")
BARE = re.compile(r"(?<![(<\w`\[])((?:https?://|www\.)[^\s<>()\[\]`]+)", re.IGNORECASE)
HTML_TAG = re.compile(r"</?(?:a|img)\b[^>]*>", re.IGNORECASE)


def _offsite(url):
    m = re.match(r"(?:https?:)?//([^/:?#]+)", url, re.IGNORECASE)
    if not m:
        return not url.startswith(("#", "/"))
    return m.group(1).lower() not in LINK_HOSTS


def defang(text):
    """Mentions, off-site links and images, outside code. (text, count)"""
    count = 0
    out = []
    pos = 0

    def prose(seg):
        nonlocal count
        def n(f):
            def g(m):
                nonlocal count
                r = f(m)
                if r != m.group(0):
                    count += 1
                return r
            return g
        seg = HTML_TAG.sub(n(lambda m: ""), seg)
        seg = IMAGE.sub(n(lambda m: m.group(0) if not _offsite(m.group(2))
                          else (f"[image: {m.group(1)}]" if m.group(1) else "")), seg)
        seg = MDLINK.sub(n(lambda m: m.group(0) if not _offsite(m.group(2))
                           else f"{m.group(1)} (`{m.group(2)}`)"), seg)
        seg = AUTOLINK.sub(n(lambda m: m.group(0) if not _offsite(m.group(1))
                             else f"`{m.group(1)}`"), seg)
        seg = BARE.sub(n(lambda m: m.group(0) if not _offsite(
            m.group(1) if "://" in m.group(1) else "//" + m.group(1))
            else f"`{m.group(1)}`"), seg)
        seg = MENTION.sub(n(lambda m: f"<code>@{m.group(1)}</code>"
                            if "`" in seg[max(m.start() - 1, 0):m.end() + 1]
                            else f"`@{m.group(1)}`"), seg)
        return seg

    for m in CODE.finditer(text):
        out.append(prose(text[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(prose(text[pos:]))
    return "".join(out), count


def main():
    path = sys.argv[1]
    upstream = (sys.argv[2] if len(sys.argv) > 2
                else os.environ.get("UPSTREAM", "monero-project/monero"))
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    text, count = neutralise(text, upstream)
    text, defanged = defang(text)
    count += defanged
    if count:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(count)


if __name__ == "__main__":
    main()
