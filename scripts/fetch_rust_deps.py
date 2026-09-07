#!/usr/bin/env python3
"""Put the Rust git dependencies a PR pins on disk, so a review can read them.

Monero's FCMP++ work lives half in C++ and half in Rust, and the Rust half
depends on monero-oxide by git revision rather than by crates.io version:

    [[package]]
    name = "full-chain-membership-proofs"
    source = "git+https://github.com/monero-oxide/monero-oxide?rev=31c26d9#31c26d96..."

Nothing else in this harness reaches that. `external/` is submodules, and the
submodule fetch covers rapidjson, randomx, supercop and gtest; a Cargo git
dependency is neither a submodule nor vendored in the tree, so it has always
been simply absent.

That cost real coverage, twice in one review (issue #509, the FCMP++
point-to-cycle-scalar change):

  - whether `full_chain_membership_proofs::tree::hash_grow` returns `None` or
    PANICS on an out-of-range offset was left unsettled -- and a panic across
    an `extern "C"` boundary aborts the process, so the difference is a
    remote-crash finding versus nothing at all;
  - whether SELENE_CHUNK_WIDTH=38 and HELIOS_CHUNK_WIDTH=18 match the pinned
    crate's generator counts could not be checked.

Both are answerable by reading the crate. This fetches it.

WHAT THIS DOES NOT DO. It never builds, runs, or resolves anything -- no cargo,
no network beyond `git fetch` of one pinned object per repository. The result
is source on disk that the reviewer reads like any other file.

THE URL COMES FROM THE PULL REQUEST, so it is attacker-chosen, and that is why
there is an allowlist below. A `Cargo.lock` pointing at an arbitrary host would
otherwise turn this harness into an outbound request to a URL a stranger picked
-- the one capability the rest of this pipeline is built to withhold. A source
that is not on the allowlist is NOT fetched, and is named in RUST_DEPS.md as
not fetched, so the review reports a gap instead of silently having one.

Usage: fetch_rust_deps.py <checkout-root>
Writes <root>/rust-deps/<repo>/ and <root>/RUST_DEPS.md. Always exits 0: a
dependency that cannot be fetched is a limit on the review, not a failure of
the run, and RUST_DEPS.md is where that limit is recorded.
"""
import os
import re
import shutil
import subprocess
import sys

# Where a pinned Rust dependency may be fetched from. Match is on the URL after
# the scheme, as a prefix, so an entry ends with "/" and names an owner rather
# than a host -- "github.com/" alone would allow anything on GitHub, which is
# the whole internet for this purpose.
#
# Add an owner here when upstream starts depending on one, and expect to: the
# FCMP++ work has already moved between serai-dex and monero-oxide once. The
# cost of a missing entry is visible (RUST_DEPS.md says the source was refused,
# and the review reports it as not covered), where the cost of a wildcard is
# not.
ALLOWED_OWNERS = (
    "github.com/monero-oxide/",
    "github.com/monero-project/",
    "github.com/serai-dex/",
    "github.com/kayabaNerve/",
)

# One pinned object from one repository is a small fetch, but the host is not
# ours and a hung clone would burn the review's whole clock.
CLONE_TIMEOUT = 180

# `source = "git+<url>[?rev=..|?branch=..|?tag=..]#<sha>"`
GIT_SOURCE = re.compile(r'^\s*source\s*=\s*"git\+([^"]+)"\s*$', re.M)
NAME = re.compile(r'^\s*name\s*=\s*"([^"]+)"\s*$', re.M)


def find_lockfiles(root):
    """Cargo.lock files in the checkout, skipping anything we put there."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        # `.harness` is this repository checked out inside the monero one, and
        # `deps-include` is a copy of /usr/include -- neither holds a
        # dependency of the change under review, and both are large.
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", ".harness", "rust-deps",
                                    "deps-include")]
        if "Cargo.lock" in filenames:
            out.append(os.path.join(dirpath, "Cargo.lock"))
    return sorted(out)


def parse_sources(path):
    """Return [(url, sha, [crate names])] for the git deps in one Cargo.lock."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        print(f"warn: cannot read {path}: {exc}", file=sys.stderr)
        return []

    found = {}
    # Split on the package table header so a `source` is attributed to the
    # `name` above it rather than to whichever name the regex reaches first.
    for block in text.split("[[package]]"):
        src = GIT_SOURCE.search(block)
        if not src:
            continue
        spec = src.group(1)
        base, _, sha = spec.partition("#")
        url = base.split("?", 1)[0].rstrip("/")
        if not sha:
            # A branch or tag with no resolved commit. Cargo always writes the
            # commit, so this means a hand-edited lock; refuse to guess.
            print(f"warn: {url} has no pinned commit in {path}", file=sys.stderr)
            continue
        name = NAME.search(block)
        entry = found.setdefault((url, sha), [])
        if name:
            entry.append(name.group(1))
    return [(u, s, sorted(set(n))) for (u, s), n in found.items()]


def allowed(url):
    stripped = re.sub(r"^[a-z+]+://", "", url)
    stripped = re.sub(r"^[^/@]+@", "", stripped)          # strip any userinfo
    return any(stripped.startswith(o) for o in ALLOWED_OWNERS)


def fetch(url, sha, dest):
    """Fetch exactly the pinned commit. Returns (ok, detail)."""
    def run(*args, cwd=None):
        return subprocess.run(args, cwd=cwd, timeout=CLONE_TIMEOUT,
                              capture_output=True, text=True)
    os.makedirs(dest, exist_ok=True)
    try:
        r = run("git", "init", "--quiet", dest)
        if r.returncode:
            return False, r.stderr.strip()[:200]
        run("git", "remote", "add", "origin", url, cwd=dest)
        # By SHA, so what lands is exactly what the lockfile pins and nothing
        # else -- no branch tip, no tags, no history to be confused by.
        r = run("git", "fetch", "--depth", "1", "--no-tags",
                "origin", sha, cwd=dest)
        if r.returncode:
            return False, (r.stderr.strip() or "fetch failed")[:200]
        r = run("git", "checkout", "--quiet", "FETCH_HEAD", cwd=dest)
        if r.returncode:
            return False, r.stderr.strip()[:200]
    except subprocess.TimeoutExpired:
        return False, f"timed out after {CLONE_TIMEOUT}s"
    except OSError as exc:
        return False, str(exc)[:200]
    return True, ""


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."

    # Clear whatever a previous run left. review-local.sh reuses one checkout
    # across pull requests, so a stale rust-deps/ would be a DIFFERENT PR's
    # pinned revision sitting where this one's should be -- and a reviewer
    # reading it would cite the wrong source with no way to notice. The GitHub
    # runner gets a fresh checkout and does not need this; it is free there.
    stale = os.path.join(root, "rust-deps")
    if os.path.isdir(stale):
        shutil.rmtree(stale, ignore_errors=True)

    locks = find_lockfiles(root)

    sources = {}
    for lock in locks:
        rel = os.path.relpath(lock, root)
        for url, sha, crates in parse_sources(lock):
            sources.setdefault((url, sha), {"crates": set(), "locks": set()})
            sources[(url, sha)]["crates"].update(crates)
            sources[(url, sha)]["locks"].add(rel)

    lines = ["# Rust git dependencies", ""]
    if not locks:
        lines += ["No `Cargo.lock` in this checkout, so this pull request pins",
                  "no Rust dependencies by git revision.", ""]
    elif not sources:
        lines += [f"Found {len(locks)} `Cargo.lock` file(s), none of which pin a",
                  "dependency by git revision. Everything comes from crates.io",
                  "and is not fetched here.", ""]
    else:
        lines += ["Pinned by git revision in this pull request's lockfile(s), and",
                  "fetched at exactly that commit so a review can read them. These",
                  "are NOT in the git tree: `git ls-files` and `git grep` cannot see",
                  "them, so use `rg` or `find` under `rust-deps/`.", ""]

    ok = refused = failed = 0
    for (url, sha), meta in sorted(sources.items()):
        name = url.rstrip("/").rsplit("/", 1)[-1]
        if name.endswith(".git"):
            name = name[:-4]
        crates = ", ".join(sorted(meta["crates"])) or "(unnamed)"
        where = ", ".join(sorted(meta["locks"]))

        if not allowed(url):
            refused += 1
            lines += [f"## {name} — NOT FETCHED", "",
                      f"- URL: `{url}`",
                      f"- Pinned at: `{sha}`",
                      f"- Crates: {crates}",
                      f"- Declared in: `{where}`",
                      "- **Why not:** that URL is not on this harness's allowlist of",
                      "  Rust dependency sources. The URL is chosen by whoever opened",
                      "  the pull request, so an unrestricted fetch would let a",
                      "  stranger direct an outbound request from this runner. The",
                      "  source was not read. Report this as not covered rather than",
                      "  reasoning about what the crate does.",
                      "- If the URL is legitimate, add its owner to `ALLOWED_OWNERS`",
                      "  in `scripts/fetch_rust_deps.py` and re-run.", ""]
            continue

        dest = os.path.join(root, "rust-deps", name)
        good, detail = fetch(url, sha, dest)
        if good:
            ok += 1
            lines += [f"## {name}", "",
                      f"- Source: `rust-deps/{name}/`",
                      f"- URL: `{url}`",
                      f"- Pinned at: `{sha}`",
                      f"- Crates used from it: {crates}",
                      f"- Declared in: `{where}`", ""]
        else:
            failed += 1
            lines += [f"## {name} — FETCH FAILED", "",
                      f"- URL: `{url}`",
                      f"- Pinned at: `{sha}`",
                      f"- Crates: {crates}",
                      f"- Declared in: `{where}`",
                      f"- Error: `{detail}`",
                      "- The source was not read. Report this as not covered.", ""]

    try:
        with open(os.path.join(root, "RUST_DEPS.md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
    except OSError as exc:
        # The report is the whole mechanism -- it is how a reviewer learns a
        # source was refused or failed. Losing it silently is the one outcome
        # worth shouting about, even though both callers treat this script as
        # non-fatal.
        print(f"warn: could not write RUST_DEPS.md: {exc}", file=sys.stderr)

    print(f"rust deps: {ok} fetched, {refused} refused by allowlist, "
          f"{failed} failed, from {len(locks)} lockfile(s)", file=sys.stderr)


if __name__ == "__main__":
    # Non-fatal by construction: a dependency this cannot fetch is a limit on
    # the review, recorded in RUST_DEPS.md, not a reason to fail the run. Both
    # callers already tolerate a bad exit; this makes the docstring's promise
    # true rather than merely intended.
    try:
        main()
    except Exception as exc:                                   # noqa: BLE001
        print(f"warn: rust dependency fetch failed outright: {exc}",
              file=sys.stderr)
