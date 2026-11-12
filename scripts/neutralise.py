#!/usr/bin/env python3
"""Rewrite references to pull requests and issues so GitHub does not turn them
into cross-reference events on upstream or any other repository.

    python3 scripts/neutralise.py FILE [UPSTREAM] [--verify REPO]

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

What counts as code is a guess at GitHub's Markdown parser, so --verify
renders the result with GitHub's own (`gh api markdown`, in REPO's context;
rendering notifies nobody). If anything is still live -- a mention, an
off-site link or image, a reference to another repository -- the original is
rewritten again with nothing exempt as code, and checked again. Still live,
or no render, exits 2 and leaves FILE as it was.
"""
import json
import os
import re
import subprocess
import sys
from urllib.parse import urlparse


def neutralise(text, upstream):
    # Any repository's, not only upstream's: each one notifies its target.
    repo = r"([A-Za-z0-9-]+/[A-Za-z0-9_.-]+?)"
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
        name = upstream if match.group(1).lower() == upstream.lower() else match.group(1)
        return f"{name} PR {match.group(2)}"

    text = url.sub(sub, text)
    text = short.sub(sub, text)
    return text, count


LINK_HOSTS = ("github.com", "www.github.com")
# Fences as GitHub reads them (CommonMark): up to three spaces of indent; a
# backtick fence's info string has no backtick; the closer is the same
# character, at least as long, with nothing after it. An unclosed fence is
# treated as prose, so a misread errs toward defanging. An HTML block runs
# from a line opening with `<` to a blank line, or past its closer for
# comments and pre/script/style/textarea; GitHub reads no fence or backtick
# inside one as code.
HTML_OPEN = re.compile(r"^ {0,3}<(?:(!--)|(\?)|(!\[CDATA\[)|(!)[A-Za-z]|(pre|script|style|textarea)\b)?",
                       re.IGNORECASE)
RAW_CLOSE = ("</pre>", "</script>", "</style>", "</textarea>")
FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
FENCE_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
INLINE = re.compile(r"(?<![\\`])(`+)(?!`)[^\n]*?(?<!`)\1(?!`)")


def blocks(text):
    """([(start, end)] of closed fenced code blocks, [(start, end)] of HTML
    blocks), in one pass in document order."""
    lines = text.splitlines(keepends=True)
    offs, pos = [], 0
    for line in lines:
        offs.append(pos)
        pos += len(line)
    offs.append(pos)
    fenced, html, i = [], [], 0
    while i < len(lines):
        line = lines[i].rstrip("\r\n")
        m = FENCE_OPEN.match(line)
        if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            fence = m.group(1)
            for j in range(i + 1, len(lines)):
                c = FENCE_CLOSE.match(lines[j].rstrip("\r\n"))
                if c and c.group(1)[0] == fence[0] and len(c.group(1)) >= len(fence):
                    fenced.append((offs[i], offs[j] + len(lines[j].rstrip("\r\n"))))
                    i = j + 1
                    break
            else:
                i += 1
            continue
        h = HTML_OPEN.match(line)
        if not h:
            i += 1
            continue
        comment, pi, cdata, decl, tag = h.groups()
        closers = (("-->",) if comment else ("?>",) if pi else ("]]>",) if cdata
                   else (">",) if decl else RAW_CLOSE if tag else ())
        start = i
        if closers:
            # Types 1-5 end on the line holding the closer.
            while i < len(lines) and not any(c in lines[i].lower() for c in closers):
                i += 1
            i = min(i + 1, len(lines))
        else:
            # Types 6 and 7 end before a blank line.
            while i < len(lines) and lines[i].strip():
                i += 1
        html.append((offs[start], offs[i]))
    return fenced, html


def code_spans(text):
    """(start, end) of fenced blocks and inline code, in order. Inside an HTML
    block GitHub reads backticks literally, so no inline code there."""
    fenced, html = blocks(text)
    spans, pos = [], 0
    for start, end in fenced + [(len(text), len(text))]:
        for m in INLINE.finditer(text, pos, start):
            if not any(s < m.end() and m.start() < e for s, e in html):
                spans.append((m.start(), m.end()))
        if start < end:
            spans.append((start, end))
        pos = end
    return spans


MENTION = re.compile(r"(?<![A-Za-z0-9/.@-])@([A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:/[A-Za-z0-9_.-]+)?)(?![A-Za-z0-9-])")
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

    for start, end in code_spans(text):
        out.append(prose(text[pos:start]))
        out.append(text[start:end])
        pos = end
    out.append(prose(text[pos:]))
    return "".join(out), count


ZWSP = "\u200b"
URL_TEXT = re.compile(r"(?i)\b(https?)://([^/\s?#<>()\[\]`'\"]+)|\bwww\.([^/\s?#<>()\[\]`'\"]+)")


def strict(text):
    """Defang with nothing exempt as code, in a form no context undoes: a
    zero-width space after `@` and inside off-site URLs, no <a> or <img>.
    (text, count)"""
    count = 0

    def url(m):
        nonlocal count
        host = (m.group(2) or "www." + (m.group(3) or "")).lower()
        if host in LINK_HOSTS:
            return m.group(0)
        count += 1
        return (f"{m.group(1)}:{ZWSP}//{m.group(2)}" if m.group(1)
                else f"www{ZWSP}.{m.group(3)}")

    def text_of(f):
        def g(m):
            nonlocal count
            count += 1
            return f(m)
        return g

    text, n = HTML_TAG.subn("", text)
    count += n
    text = IMAGE.sub(lambda m: m.group(0) if not _offsite(m.group(2)) else text_of(
        lambda m: f"[image: {m.group(1)}]" if m.group(1) else "")(m), text)
    text = MDLINK.sub(lambda m: m.group(0) if not _offsite(m.group(2)) else text_of(
        lambda m: f"{m.group(1)} ({m.group(2)})")(m), text)
    text = URL_TEXT.sub(url, text)
    text, n = re.subn(r"@(?=[A-Za-z0-9])", "@" + ZWSP, text)
    return text, count + n


SAFE_HOST = re.compile(r"(^|\.)(github\.com|githubusercontent\.com)$")
ATTR = re.compile(r"\b(href|src|data-canonical-src|srcset|data-url)=\"([^\"]*)\"", re.IGNORECASE)


def live(html, repo):
    """What in GitHub's rendering of the body would notify or leave GitHub."""
    found = []
    for m in re.finditer(r'class="[^"]*\b(user-mention|team-mention)\b[^"]*"[^>]*>([^<]*)', html):
        found.append(f"{m.group(1)} {m.group(2)}")
    for m in ATTR.finditer(html):
        for url in m.group(2).split(","):
            url = url.strip().split(" ")[0]
            u = urlparse(url)
            if u.scheme in ("", "mailto") and not u.netloc:
                continue
            if not SAFE_HOST.search((u.hostname or "").lower()):
                found.append(f"off-site {m.group(1)} {url}")
            elif re.match(r"(?i)/([^/]+/[^/]+)/(issues|pull)/\d+", u.path or "") and \
                    u.hostname.lower() in LINK_HOSTS and \
                    not u.path.lower().startswith(f"/{repo.lower()}/"):
                found.append(f"reference {url}")
    return found


def render(text, repo):
    p = subprocess.run(["gh", "api", "-X", "POST", "markdown", "--input", "-"],
                       input=json.dumps({"text": text, "mode": "gfm", "context": repo}),
                       capture_output=True, text=True, timeout=120)
    if p.returncode:
        raise RuntimeError("render failed: " + p.stderr.strip()[:200])
    return p.stdout


def main():
    args = sys.argv[1:]
    repo = None
    if "--verify" in args:
        i = args.index("--verify")
        repo = args[i + 1]
        del args[i:i + 2]
    path = args[0]
    upstream = (args[1] if len(args) > 1
                else os.environ.get("UPSTREAM", "monero-project/monero"))
    with open(path, encoding="utf-8", errors="replace") as fh:
        original = fh.read()
    text, count = neutralise(original, upstream)
    text, defanged = defang(text)
    count += defanged
    if repo:
        try:
            left = live(render(text, repo), repo)
            if left:
                text, count = neutralise(original, upstream)
                text, n = strict(text)
                count += n
                left = live(render(text, repo), repo)
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            print(f"neutralise: {e}", file=sys.stderr)
            sys.exit(2)
        if left:
            print("neutralise: still live after the strict rewrite: " + "; ".join(left[:5]),
                  file=sys.stderr)
            sys.exit(2)
    if count:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(count)


if __name__ == "__main__":
    main()
