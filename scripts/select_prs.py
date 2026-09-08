#!/usr/bin/env python3
"""Pick which upstream PRs to review next.

Prints `prs=<json array>` on stdout for $GITHUB_OUTPUT; diagnostics on stderr.

Selection is a queue, not a recency window:
  - open, non-draft, updated within MAX_AGE_DAYS
  - head SHA not already present in this repo's issue titles (the dedup record)
  - a PR already reviewed once is held until its head stops moving
  - touches something worth reviewing (see WORTHLESS)
  - most recently active first, take BATCH

There is exactly one entry per PR and it is keyed on the LIVE head SHA, read
from the pull request list on this tick. Nothing is carried between ticks, so
an old head can never sit in the queue behind a newer one.

Doc-only PRs are skipped rather than marked, so they cost one cheap API probe
per tick and become eligible automatically if they later add code. Every
queued PR is probed, not just enough to fill BATCH, so the counters can
separate the PRs actually in line from the doc-only residue:

  prs       the PRs to review this tick
  queue     unreviewed non-draft PRs, doc-only included (unchanged meaning)
  ready     of those, the ones with reviewable code -- the real backlog
  docs      of those, the doc-only ones, which will never be picked
  settling  of those, the re-reviews being held until the head stops moving
  unprobed  queued PRs the MAX_PROBES budget did not reach
  open      open PRs upstream

Env: UPSTREAM, REVIEW_REPO, MAX_AGE_DAYS, BATCH, SETTLE_MINUTES,
     GH_TOKEN (optional), API (optional base URL, for testing).
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
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

# A PR whose every changed file matches this has nothing for a security review
# of consensus / memory safety / crypto to act on. Deliberately narrow: build
# files, CI, and anything under src/ or contrib/ stay reviewable, because a
# malicious build or workflow change is a real supply-chain concern.
WORTHLESS = re.compile(
    r"(^docs/"
    r"|^translations/"
    # NB: no bare \.txt$ -- that would swallow CMakeLists.txt and silently
    # skip build-config changes. Fail open on anything not clearly prose.
    r"|\.md$|\.rst$"
    r"|^LICENSE|^COPYING"
    r"|^\.gitignore$|^\.gitattributes$|^\.editorconfig$"
    r"|^\.github/(ISSUE_TEMPLATE|PULL_REQUEST_TEMPLATE)"
    r")",
    re.IGNORECASE,
)

# How many queued PRs one tick will classify. Every tick probes up to this many
# rather than stopping once BATCH is filled, so this is the routine cost, not
# an exceptional one: one file listing each, twice an hour, against a 1000/hour
# authenticated budget.
#
# It also bounds how far the counters can see, and THAT is what this number is
# really for. A queue deeper than this leaves the tail unclassified, which the
# `unprobed` output reports rather than hiding.
#
# RAISED 20 -> 40, on the condition the old comment named. Measured across four
# consecutive runs as the queue crossed the cap:
#
#     run   queue  probed  ready  docs  unclassified
#     478      20      20      8    12       0
#     479      27      20     15     5       7
#     480      30      20     18     2      10
#
# `ready` appearing to more than double is an artifact, not a backlog. The
# queue is sorted most-recently-updated first, and doc-only PRs are stale by
# nature -- nobody pushes to a README -- so they sort to the bottom and are the
# first to fall past the cap. Run 480's own log shows it: the only two docs it
# found were probed 19th and 20th. So the docs did not go anywhere, they moved
# from `docs` into `unclassified`, and the footer read "18 in line" where the
# comparable earlier number was 8.
#
# A counter whose two visible buckets stop summing to the queue is worse than
# no counter: it is read as a backlog spike by whoever looks at it. 40 restores
# a true census at the depth seen so far. It is a ceiling, not a target -- the
# cost is one API call per queued PR per tick, so 40 twice an hour is 80 of a
# 1000/hour budget. If `unclassified` starts appearing again, raise it again,
# and keep the table above going.
MAX_PROBES = 40

# Failed attempts at the same head SHA before the queue moves on. 2 gives a
# transient failure one retry without letting a reliably-failing PR block
# everything behind it.
MAX_ATTEMPTS = 2

# Quiet time a pull request must have before it is reviewed A SECOND time.
#
# The dedup record is the head SHA, so every push to an already-reviewed pull
# request puts it back in the queue at a new SHA. That is right in principle
# and expensive in practice: a review costs $2 to $32 and 5 to 50 minutes, and
# an author pushing fixups three times an afternoon buys three of them, of
# which the first two are obsolete before they publish. Measured over the four
# days to 8 September, twelve pull requests were reviewed at more than one head
# in a window of about a hundred reviews, two of them three times each: 11247
# at c294e417, 52f3a245 and 2c3a87d0, and 11249 at 4190d738, e3eadf88 and
# 736be2d4.
#
# THE SECOND COST IS WORSE THAN THE MONEY. The queue is sorted most recently
# updated first and BATCH is 1, so a pull request being actively edited is the
# newest unreviewed item on every tick and takes the only slot each time, while
# the backlog behind it does not move. It is the same starvation the
# MAX_ATTEMPTS counter above exists to prevent, arriving through a different
# door.
#
# So a re-review waits for quiet. A pull request nobody has reviewed yet is
# never delayed by this: new work is exactly what should be reviewed promptly,
# and holding it would be a straight loss. Only a SECOND look at a pull request
# this repo has already paid for is made to wait, and it waits only while the
# head is still moving. One that keeps moving for a week is held for a week,
# which is the wanted answer: nothing is lost, because the review it would have
# bought was going to be superseded anyway, and it stops occupying the slot.
SETTLE_MINUTES = int(os.environ.get("SETTLE_MINUTES", "90"))

# Pages of open PRs to consider, 100 each. Upstream runs ~300 open, so one page
# would hide the backlog behind the most-recently-updated 100.
MAX_PR_PAGES = 5


def get(path, params=None):
    url = f"{API}{path}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "monero-review",
        **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}),
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def review_state(repo):
    """Read this repo's issue titles as the record of what has been attempted.

    Returns (done, failed, seen): SHAs with a completed review, a count of
    failed attempts per SHA, and the PR numbers carrying at least one
    completed review. A SHA is retried after a failure -- but only
    MAX_ATTEMPTS times, or a PR that reliably fails would be the newest
    unreviewed item on every tick and block the queue forever.

    `seen` is what separates a first review from a re-review, and only the
    second kind waits for the head to settle. A PR whose only issues are
    `Review FAILED:` is deliberately NOT in it: that PR has never actually
    been reviewed, so its retry is a first look and must not be delayed.
    """
    done, failed, seen = set(), collections.Counter(), set()
    for page in range(1, 11):
        try:
            issues = get(f"/repos/{repo}/issues",
                         {"state": "all", "per_page": 100, "page": page})
        except urllib.error.HTTPError as exc:
            print(f"warn: issue listing failed ({exc.code}); "
                  "assuming nothing reviewed", file=sys.stderr)
            return done, failed, seen
        if not issues:
            break
        for issue in issues:
            title = issue.get("title", "")
            shas = re.findall(r"\b[0-9a-f]{12}\b", title)
            if title.startswith("Review FAILED:"):
                failed.update(shas)
            else:
                done.update(shas)
                number = re.search(r"#(\d+)\b", title)
                if number:
                    seen.add(int(number.group(1)))
        if len(issues) < 100:
            break
    return done, failed, seen


def local_reviewed(dirpath):
    """SHAs and PR numbers already reviewed locally.

    review-local.sh names its output reviews/pr-<number>-<sha12>.md, so the
    directory listing *is* the local dedup record -- no extra state file. The
    number is read from the same filename, so a locally driven drip holds a
    re-review for the settle window exactly as CI does.
    """
    shas, numbers = set(), set()
    if not dirpath or not os.path.isdir(dirpath):
        return shas, numbers
    for name in os.listdir(dirpath):
        shas.update(re.findall(r"\b[0-9a-f]{12}\b", name))
        number = re.match(r"pr-(\d+)-", name)
        if number:
            numbers.add(int(number.group(1)))
    return shas, numbers


def head_pushed_at(upstream, sha):
    """When the head commit was written, or None if that cannot be read.

    The committer date rather than the author date, because a rebase rewrites
    the first and preserves the second, and a rebase is a push. It is a proxy
    for the push and not the push itself: GitHub does not expose a push time
    on a pull request, and a force-push of an OLD commit therefore reads as
    settled. That direction is the safe one, since the cost of being wrong is
    one review, and the cost of the other direction is a PR held forever.
    """
    try:
        commit = get(f"/repos/{upstream}/commits/{sha}")
    except (urllib.error.HTTPError, urllib.error.URLError, KeyError) as exc:
        print(f"warn: commit date for {sha[:12]} failed ({exc}); "
              "treating it as settled", file=sys.stderr)
        return None
    stamp = (commit.get("commit", {}).get("committer", {}) or {}).get("date")
    if not stamp:
        return None
    try:
        return datetime.datetime.strptime(
            stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def worth_reviewing(upstream, number):
    """False only if every changed file is documentation-ish."""
    try:
        files = get(f"/repos/{upstream}/pulls/{number}/files", {"per_page": 100})
    except urllib.error.HTTPError as exc:
        # Fail open: an API hiccup should not silently drop a PR from review.
        print(f"warn: file listing for #{number} failed ({exc.code}); "
              "reviewing anyway", file=sys.stderr)
        return True, []
    names = [f["filename"] for f in files]
    if not names:
        return False, names
    # A full page means there are more files we cannot see. Fail open rather
    # than judge a large PR on a truncated list.
    if len(names) >= 100:
        return True, names
    return (not all(WORTHLESS.search(n) for n in names)), names


def main():
    upstream = os.environ["UPSTREAM"]
    repo = os.environ["REVIEW_REPO"]
    batch = int(os.environ.get("BATCH", "1"))
    max_age = int(os.environ.get("MAX_AGE_DAYS", "1"))

    # MAX_AGE_DAYS=0 means no age limit: every open PR is eligible, so the queue
    # chips through the backlog once recent work is done. Sorting is still
    # most-recently-active first, so fresh PRs keep priority and old ones are
    # only reached when nothing newer is unreviewed.
    if max_age <= 0:
        cutoff = ""
    else:
        cutoff = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(days=max_age)
                  ).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Paginate: upstream has far more than one page of open PRs, and a single
    # page silently caps the queue at the 100 most-recently-updated -- which
    # makes the backlog permanently invisible however wide MAX_AGE_DAYS is.
    prs = []
    for page in range(1, MAX_PR_PAGES + 1):
        batch_of_prs = get(f"/repos/{upstream}/pulls", {
            "state": "open", "per_page": 100, "page": page,
            "sort": "updated", "direction": "desc",
        })
        if not batch_of_prs:
            break
        prs.extend(batch_of_prs)
        if len(batch_of_prs) < 100:
            break
    done, failed, reviewed_before = review_state(repo)

    # Local runs record themselves as filenames; count those as done too, so a
    # locally driven drip and the CI workflow don't duplicate each other's work.
    local, local_numbers = local_reviewed(os.environ.get("REVIEWS_DIR"))
    if local:
        print(f"{len(local)} SHA(s) already reviewed locally", file=sys.stderr)
        done |= local
        reviewed_before |= local_numbers

    def pending(p):
        sha = p["head"]["sha"][:12]
        if sha in done:
            return False
        if failed[sha] >= MAX_ATTEMPTS:
            print(f"  give up on #{p['number']}: {failed[sha]} failed attempts "
                  f"at {sha}", file=sys.stderr)
            return False
        return True

    queue = [p for p in prs
             if not p["draft"]
             and p["updated_at"] > cutoff
             and pending(p)]
    queue.sort(key=lambda p: p["updated_at"], reverse=True)
    scope = f"updated since {cutoff}" if cutoff else "of any age"
    print(f"{len(queue)} unreviewed PR(s) {scope}, out of {len(prs)} open",
          file=sys.stderr)

    # Probing continues past the point where BATCH is filled, which is the
    # whole reason the footer can distinguish a real backlog from a pile of
    # README PRs. Stopping at BATCH classified one or two PRs per tick and
    # left the rest unknown, so "13 unreviewed" was reported on a queue whose
    # real depth was 1 -- the other 12 were doc-only and never going to be
    # reviewed. That number is what a reader uses to decide whether the bot is
    # stuck or simply done, and it said "stuck" for a week of being done.
    #
    # Cost is one file listing per queued PR, MAX_PROBES capped, against a
    # 1000/hour authenticated budget at two ticks an hour. Doc-only PRs are
    # still not marked anywhere: re-probing them each tick is what makes one
    # eligible again the moment it grows a code file.
    picked, ready, docs, settling, probes = [], 0, 0, 0, 0
    now = datetime.datetime.now(datetime.timezone.utc)
    window = datetime.timedelta(minutes=SETTLE_MINUTES)
    for pr in queue:
        if probes >= MAX_PROBES:
            break
        probes += 1
        # Hold a re-review while the head is still moving. Two gates, cheap
        # one first: `updated_at` bumps on a push, so a pull request that has
        # not been touched inside the window is settled and costs no call at
        # all. It also bumps on a comment or a label, which is why the second
        # gate reads the head commit's own date -- a busy discussion on stable
        # code should not hold a review forever. Both must be recent.
        if (SETTLE_MINUTES > 0 and pr["number"] in reviewed_before
                and pr["updated_at"] > (now - window).strftime(
                    "%Y-%m-%dT%H:%M:%SZ")):
            pushed = head_pushed_at(upstream, pr["head"]["sha"])
            if pushed is not None and pushed > now - window:
                settling += 1
                age = int((now - pushed).total_seconds() // 60)
                print(f"  hold #{pr['number']}: reviewed before and its head "
                      f"is {age}m old, under the {SETTLE_MINUTES}m settle "
                      "window", file=sys.stderr)
                continue
        ok, names = worth_reviewing(upstream, pr["number"])
        if not ok:
            docs += 1
            print(f"  skip #{pr['number']}: no reviewable code "
                  f"({', '.join(names[:4])})", file=sys.stderr)
            continue
        ready += 1
        if len(picked) < batch:
            picked.append(str(pr["number"]))
            print(f"  take #{pr['number']} ({len(names)} file(s))",
                  file=sys.stderr)
        else:
            print(f"  queued #{pr['number']} ({len(names)} file(s))",
                  file=sys.stderr)

    # Everything the probe budget did not reach. Reported rather than folded
    # into either bucket, so the footer never implies a classification that
    # was not made.
    unprobed = len(queue) - probes
    print(f"{ready} in line, {docs} doc-only"
          + (f", {settling} settling" if settling else "")
          + (f", {unprobed} unclassified (probe cap)" if unprobed else ""),
          file=sys.stderr)

    # For $GITHUB_OUTPUT. All of these describe the queue as of the moment the
    # run started, which is the only moment this process can speak for: by the
    # time the review job finishes, an hour of upstream pushes later,
    # recomputing would answer a different question.
    #
    # `queue` is kept at its original meaning -- every unreviewed non-draft PR
    # in the age window, doc-only ones included -- because 400-odd published
    # issues already carry that number in their footers and silently redefining
    # it would make them incomparable. `ready` is the new one worth reading,
    # and it counts the PR this run is about to review. A settling PR is in
    # `queue` and in NEITHER `ready` nor `docs`: it has reviewable code and it
    # is not being reviewed, and folding it into either would hide a decision
    # this tick made. ready + docs + settling + unprobed == queue.
    print("prs=" + json.dumps(picked))
    print(f"queue={len(queue)}")
    print(f"ready={ready}")
    print(f"docs={docs}")
    print(f"settling={settling}")
    print(f"unprobed={unprobed}")
    print(f"open={len(prs)}")


if __name__ == "__main__":
    main()
