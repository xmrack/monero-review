#!/usr/bin/env python3
"""Pick which upstream PRs to review next.

Prints `prs=<json array>` on stdout for $GITHUB_OUTPUT; diagnostics on stderr.

Selection is a queue, not a recency window:
  - open, non-draft, targeting BASE_BRANCH, updated within MAX_AGE_DAYS
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
  offbranch open PRs not targeting BASE_BRANCH, dropped before the queue
  open      open PRs upstream

Env: UPSTREAM, REVIEW_REPO, MAX_AGE_DAYS, BATCH, SETTLE_MINUTES,
     BASE_BRANCH, GH_TOKEN (optional), API (optional base URL, for testing).
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

# Only pull requests targeting the upstream's main development branch are
# swept. `master` for monero-project/monero, confirmed against the remote
# rather than assumed: `git ls-remote --symref <upstream> HEAD` answers
# `ref: refs/heads/master`.
#
# The rest are backports and long-lived branch work. They are real changes and
# the harness reviews them correctly when asked by number -- `origin/base` is
# whatever branch the pull request targets, which is what stopped a two-file
# backport diffing as 353 files -- but they are not where this queue's money
# should go: a backport is code that already landed on master and was already
# read there, and the branch it lands on is maintained by people who chose it
# deliberately.
#
# Set to an empty string to sweep every branch again.
BASE_BRANCH = os.environ.get("BASE_BRANCH", "master")

# Pages of open PRs to consider, 100 each. Upstream runs ~300 open, so one page
# would hide the backlog behind the most-recently-updated 100.
MAX_PR_PAGES = 5

# Pages of THIS repo's issues to read, 100 each, when reconstructing what has
# already been reviewed. This was 10, which is 1000 items -- and the endpoint
# counts pull requests as issues too, so the repository was at 600 with nothing
# anywhere saying a ceiling existed. Crossing it would not have failed loudly:
# the OLDEST reviews would simply have stopped being visible, their pull
# requests would have looked unreviewed, and the queue would have re-reviewed
# them at $1 to $18 each -- publishing another issue every time, pushing more
# of the record out of the window. The failure feeds itself and its only
# symptom is the bill.
#
# 100 pages is a bound against a runaway, not a budget: pagination stops at the
# first short page, so today's 600 items still cost six requests. Reaching it
# is treated as a FAILED read rather than a complete one (see review_state).
MAX_ISSUE_PAGES = 100


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

    Returns None when the record could not be read IN FULL -- a failed request
    or a listing longer than MAX_ISSUE_PAGES. It used to return whatever it had
    managed to read, announcing "assuming nothing reviewed", and that default
    is backwards for this caller: an empty `done` makes every pull request look
    unreviewed, so the queue answers a transient 502 by spending $1 to $18
    re-reading something it already read. Nothing is lost by selecting nothing
    for one tick -- the sweep runs twice an hour -- and a partial record cannot
    be told from a complete one by anyone downstream.
    """
    done, failed, seen = set(), collections.Counter(), set()
    for page in range(1, MAX_ISSUE_PAGES + 1):
        try:
            issues = get(f"/repos/{repo}/issues",
                         {"state": "all", "per_page": 100, "page": page})
        # OSError covers HTTPError and URLError both, so a 502, a rate limit,
        # a timeout and a DNS failure all land here rather than only the first.
        except (OSError, ValueError) as exc:
            print(f"warn: issue listing failed on page {page} ({exc})",
                  file=sys.stderr)
            return None
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
        # A short page is the end of the listing, and an empty one is the end
        # when the count divides exactly by 100.
        if len(issues) < 100:
            return done, failed, seen
    print(f"warn: this repository holds more than {MAX_ISSUE_PAGES * 100} "
          "issues and pull requests; the review record cannot be read in full",
          file=sys.stderr)
    return None


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
    else:
        # Ran the whole range without a short page: upstream has more open
        # pull requests than this fetches, and the oldest-updated are invisible
        # this tick. Not fatal -- they are the least likely to matter and the
        # count below still reports what WAS seen -- but it must not be silent,
        # because "N open" reading lower than reality looks like upstream got
        # quieter rather than like a cap being hit.
        print(f"warn: stopped at {MAX_PR_PAGES} pages of open pull requests "
              f"({len(prs)}); older ones are not in this tick's queue",
              file=sys.stderr)
    state = review_state(repo)
    if state is None:
        # Select NOTHING. The record of what has been reviewed is the only
        # thing standing between this queue and re-reading work it has already
        # paid for, and a partial record is indistinguishable from a complete
        # one once it leaves this function. Skipping a tick costs nothing: the
        # sweep runs twice an hour and the backlog is not going anywhere.
        print("refusing to select: the record of what has already been "
              "reviewed could not be read in full", file=sys.stderr)
        print("prs=[]")
        for name in ("queue", "ready", "docs", "settling", "unprobed",
                     "offbranch"):
            print(f"{name}=0")
        print(f"open={len(prs)}")
        return
    done, failed, reviewed_before = state

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

    # Off-branch pull requests are dropped BEFORE the queue rather than
    # probed and skipped like doc-only ones, because nothing about them can
    # change: a doc-only pull request becomes eligible the moment it grows a
    # code file, while a backport's target branch is what it is. Probing them
    # would spend a file listing each, every tick, to reach the same answer.
    offbranch = collections.Counter()
    if BASE_BRANCH:
        for p in prs:
            ref = (p.get("base") or {}).get("ref") or "(unknown)"
            if ref != BASE_BRANCH:
                offbranch[ref] += 1
        prs_on_branch = [p for p in prs
                         if ((p.get("base") or {}).get("ref") == BASE_BRANCH)]
    else:
        prs_on_branch = prs
    if offbranch:
        detail = ", ".join(f"{ref} ({n})" for ref, n in offbranch.most_common())
        print(f"{sum(offbranch.values())} open PR(s) not targeting "
              f"{BASE_BRANCH}, not swept: {detail}", file=sys.stderr)

    queue = [p for p in prs_on_branch
             if not p["draft"]
             and p["updated_at"] > cutoff
             and pending(p)]
    queue.sort(key=lambda p: p["updated_at"], reverse=True)
    scope = f"updated since {cutoff}" if cutoff else "of any age"
    on = f" targeting {BASE_BRANCH}" if BASE_BRANCH else ""
    print(f"{len(queue)} unreviewed PR(s){on} {scope}, "
          f"out of {len(prs)} open", file=sys.stderr)

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
    # `queue` keeps its original shape -- every unreviewed non-draft PR in the
    # age window, doc-only ones included -- because 400-odd published issues
    # already carry that number in their footers and silently redefining it
    # would make them incomparable. It is now narrowed to pull requests
    # targeting BASE_BRANCH, which IS a redefinition, and a deliberate one:
    # counting work this pipeline has decided never to do would report a
    # backlog that can never drain, which is the exact failure the doc-only
    # probing was built to fix. `offbranch` is published beside it so the
    # difference from `open` is visible rather than inferred. `ready` is the new one worth reading,
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
    print(f"offbranch={sum(offbranch.values())}")
    print(f"open={len(prs)}")


if __name__ == "__main__":
    main()
