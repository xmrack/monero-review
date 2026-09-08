#!/usr/bin/env python3
"""Put the Rust dependencies a PR pins on disk, so a review can read them.

TWO HALVES, with different threat models and different costs.

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

THE CRATES.IO HALF, added after issue #514 had to publish two more gaps of the
same shape: "the six new crates.io checksums were not compared against the
registry's published hashes -- no network. Only that all 67 registry sources
carry SOME checksum was verified", and "whether the [patch.crates-io]
crypto-bigint fork is semantically equivalent to registry crypto-bigint 0.5.5
... upstream sources are not on disk". Registry packages were not merely
unfetched, they were invisible: every `[[package]]` without a `git+` source was
skipped, so RUST_DEPS.md did not even name them.

Its threat model is NOT the git half's. A `git+` URL is attacker-chosen, hence
the allowlist. A registry source is not -- the index URL is a constant and only
the crate name and version come from the lockfile -- so the rule here is a
pinned host, a sanitised name/version that cannot climb out of a path or a URL,
a redirect check, and a mandatory sha256 match before anything is unpacked.

And the two jobs are split by cost. CHECKING is cheap and covers everything:
one sparse-index request per package says what crates.io published for that
exact version, and comparing it to the lockfile's `checksum` is the question
#514 could not answer. FETCHING covers only what a reviewer will open -- the
packages this pull request adds or bumps, plus the registry original of
anything `[patch.crates-io]` replaces, which is the only way a fork gets
compared to what it replaced rather than taken on trust.

Usage: fetch_rust_deps.py <checkout-root>
Writes <root>/rust-deps/<repo>/, <root>/rust-deps/crates/<name>-<version>/ and
<root>/RUST_DEPS.md. Always exits 0: a dependency that cannot be fetched is a
limit on the review, not a failure of the run, and RUST_DEPS.md is where that
limit is recorded.
"""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request

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

# A bump patch is read by a person, and an enormous one is read by nobody. The
# --stat above always lists every changed file, so truncating the patch loses
# detail rather than the shape of the change.
MAX_PATCH_BYTES = 2_000_000

# THE REGISTRY HALF, and its threat model is NOT the git half's.
#
# A `git+` URL is chosen by whoever opened the pull request, which is why the
# owner allowlist above exists. A registry source is not: every crates.io
# package carries the same fixed index URL, and only the crate NAME and VERSION
# come from the lockfile. So the rule here is a pinned host rather than an
# allowlist -- both URLs below are built from a constant and a sanitised
# name/version, never from a string in the lockfile, and a redirect away from
# these hosts aborts the fetch.
INDEX_HOST = "index.crates.io"
CRATE_HOST = "static.crates.io"
PINNED_HOSTS = (INDEX_HOST, CRATE_HOST)

# The index URLs cargo itself recognises as crates.io. Anything else is some
# other registry: reported, never fetched, because nothing here knows what its
# index looks like or who runs it.
CRATES_IO_INDEX = (
    "https://github.com/rust-lang/crates-io-index",
    "sparse+https://index.crates.io/",
)

# Cargo's own naming rules, tightened. These reach a filesystem path and a URL,
# so a name is accepted only if it cannot climb out of either: no slash, no
# backslash, no `..`, no leading dot.
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}$")
SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}$")

HTTP_TIMEOUT = 30
# One index entry is a few KB of JSON lines; a crate is a gzipped tarball.
MAX_INDEX_BYTES = 4_000_000
MAX_CRATE_BYTES = 16_000_000
# Extraction bombs are the reason this is a separate limit from the download.
MAX_UNPACKED_BYTES = 64_000_000
# How many crate sources land on disk. Only what this PR ADDS OR BUMPS, plus
# whatever `[patch.crates-io]` overrides, is fetched -- the rest of a 67-crate
# graph is noise a reviewer never opens and weight on every `rg` they run. The
# cap is a backstop for a lockfile rewrite that touches everything.
MAX_CRATES_FETCHED = 25

# `source = "git+<url>[?rev=..|?branch=..|?tag=..]#<sha>"`
GIT_SOURCE = re.compile(r'^\s*source\s*=\s*"git\+([^"]+)"\s*$', re.M)
NAME = re.compile(r'^\s*name\s*=\s*"([^"]+)"\s*$', re.M)
# `source = "registry+<index url>"`, plus the two keys that make a registry
# package checkable: the exact version, and the sha256 cargo recorded for it.
REGISTRY_SOURCE = re.compile(r'^\s*source\s*=\s*"registry\+([^"]+)"\s*$', re.M)
VERSION = re.compile(r'^\s*version\s*=\s*"([^"]+)"\s*$', re.M)
CHECKSUM = re.compile(r'^\s*checksum\s*=\s*"([0-9a-fA-F]{64})"\s*$', re.M)
# `[patch.crates-io]` in a Cargo.toml, and the crate names under it. A patch
# swaps a registry crate for somebody's fork with nothing in the lockfile
# saying what it replaced, so these are the entries most worth putting the
# registry original beside.
PATCH_HEADER = re.compile(r'^\s*\[patch\.(?:crates-io|"[^"]*crates\.io[^"]*")\]\s*$', re.M)
PATCH_KEY = re.compile(r'^\s*([A-Za-z0-9_.+-]+)\s*(?:=|\.\w)')


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
    return parse_sources_text(text)


def parse_sources_text(text):
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
            print(f"warn: {url} has no pinned commit", file=sys.stderr)
            continue
        name = NAME.search(block)
        entry = found.setdefault((url, sha), [])
        if name:
            entry.append(name.group(1))
    return [(u, s, sorted(set(n))) for (u, s), n in found.items()]


def parse_registry_text(text):
    """Registry packages in one Cargo.lock.

    Returns {(name, version): {"checksum": str|None, "index": url}} for every
    `[[package]]` whose source is a registry. Cargo writes the sha256 of the
    published `.crate` as `checksum`, which is what makes these checkable at
    all -- a package with no checksum is reported rather than trusted.
    """
    found = {}
    for block_text in text.split("[[package]]"):
        src = REGISTRY_SOURCE.search(block_text)
        if not src:
            continue
        name = NAME.search(block_text)
        ver = VERSION.search(block_text)
        if not name or not ver:
            continue
        digest = CHECKSUM.search(block_text)
        found[(name.group(1), ver.group(1))] = {
            "checksum": digest.group(1).lower() if digest else None,
            "index": src.group(1).strip(),
        }
    return found


def parse_locked_versions(text):
    """{name: version} for EVERY package in a lock, whatever its source.

    A `[patch.crates-io]` target keeps its version in the lock even though its
    source is the fork, so this is how the registry original to compare against
    is identified. Guessing the newest published version instead would put the
    wrong crate on disk beside the fork, which is worse than an admitted gap.
    """
    out = {}
    for block_text in text.split("[[package]]"):
        name = NAME.search(block_text)
        ver = VERSION.search(block_text)
        if name and ver:
            out.setdefault(name.group(1), ver.group(1))
    return out


def parse_patch_targets(path):
    """Crate names under `[patch.crates-io]` in one Cargo.toml."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return []
    names, inside = [], False
    for line in text.splitlines():
        stripped = line.strip()
        if PATCH_HEADER.match(line):
            inside = True
            continue
        if stripped.startswith("["):
            inside = False
            continue
        if inside and stripped and not stripped.startswith("#"):
            key = PATCH_KEY.match(line)
            if key:
                names.append(key.group(1).split(".", 1)[0])
    return names


def is_crates_io(index_url):
    stripped = index_url.strip().rstrip("/")
    return any(stripped == c.rstrip("/") for c in CRATES_IO_INDEX)


def safe_pair(name, version):
    return bool(SAFE_NAME.match(name) and SAFE_VERSION.match(version)
                and ".." not in name and ".." not in version)


def index_path(name):
    """crates.io sparse-index layout, which is keyed on the lowercased name."""
    n = name.lower()
    if len(n) == 1:
        return "1/" + n
    if len(n) == 2:
        return "2/" + n
    if len(n) == 3:
        return "3/" + n[0] + "/" + n
    return n[:2] + "/" + n[2:4] + "/" + n


def http_get(url, max_bytes):
    """GET a URL this script built, refusing a redirect off the pinned hosts.

    Every caller composes the URL from a constant host and a name/version that
    passed `safe_pair`, so nothing from the lockfile reaches the network as a
    URL. The post-hoc host check covers the one thing that composition cannot:
    a 3xx pointing somewhere else.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "monero-review-harness"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        final = urllib.parse.urlsplit(resp.geturl()).hostname or ""
        if final not in PINNED_HOSTS:
            raise ValueError(f"redirected off the pinned hosts, to {final}")
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"response larger than {max_bytes} bytes")
    return data


def index_entry(name, version):
    """(published_sha256, yanked, error) for one crate version, from the index.

    The sparse index answers "what did crates.io actually publish for this
    version" in a few KB, without downloading the crate. That is the whole of
    what the lockfile's `checksum` needs to be compared against, and it is
    cheap enough to do for every registry package in the graph.
    """
    url = f"https://{INDEX_HOST}/{index_path(name)}"
    try:
        raw = http_get(url, MAX_INDEX_BYTES).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, None, "no such crate in the crates.io index"
        return None, None, f"HTTP {exc.code}"
    except Exception as exc:                                   # noqa: BLE001
        return None, None, str(exc)[:160]
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("vers") == version:
            return (str(rec.get("cksum", "")).lower(),
                    bool(rec.get("yanked")), "")
    return None, None, "that version is not in the index"


def unpack_crate(data, dest):
    """Extract a verified .crate tarball. (ok, detail).

    Called only after the sha256 matched, so the bytes are the ones crates.io
    published -- but a published crate is still a stranger's tarball, and the
    reviewer's checkout is what it would be unpacking into. `filter="data"`
    (3.12+) rejects absolute paths, `..`, links pointing outside, and device
    nodes; the fallback does the same checks by hand for an older interpreter,
    because silently extracting unfiltered would be the wrong way to degrade.
    """
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            members = tar.getmembers()
            for m in members:
                total += max(0, m.size)
                if total > MAX_UNPACKED_BYTES:
                    return False, f"unpacks to more than {MAX_UNPACKED_BYTES} bytes"
            os.makedirs(dest, exist_ok=True)
            try:
                tar.extractall(dest, filter="data")
            except TypeError:
                safe = []
                for m in members:
                    if m.issym() or m.islnk() or m.isdev():
                        continue
                    name = m.name.replace("\\", "/")
                    if name.startswith("/") or os.path.isabs(name):
                        continue
                    if any(part == ".." for part in name.split("/")):
                        continue
                    safe.append(m)
                tar.extractall(dest, members=safe)
    except Exception as exc:                                   # noqa: BLE001
        return False, str(exc)[:160]

    # A `.crate` carries its own `<name>-<version>/` top level, which would
    # otherwise give `rust-deps/crates/serde-1.0.0/serde-1.0.0/src/lib.rs` and
    # a reviewer citing the wrong-looking path. Flatten it AFTER extraction
    # rather than by stripping components during it: placement then never
    # depends on what the tarball claims its top directory is called.
    try:
        entries = os.listdir(dest)
        if len(entries) == 1:
            inner = os.path.join(dest, entries[0])
            if os.path.isdir(inner) and not os.path.islink(inner):
                for item in os.listdir(inner):
                    shutil.move(os.path.join(inner, item), os.path.join(dest, item))
                os.rmdir(inner)
    except OSError:
        pass          # the source is on disk either way; only the path is uglier
    return True, ""


def fetch_crate(name, version, expected, dest):
    """Download one published crate, verify its sha256, unpack it. (ok, detail).

    `expected` is the sha256 to hold it to -- the lockfile's `checksum` for a
    registry package, or the index's `cksum` for a `[patch.crates-io]` original
    the lock has no checksum for. There is no path that extracts unverified
    bytes: without an expected digest the fetch is refused and reported, since
    unpacking a tarball nothing vouches for is exactly the outcome this is
    meant to rule out.
    """
    if not safe_pair(name, version):
        return False, "the crate name or version is not a shape this will fetch"
    if not expected:
        return False, "no sha256 to verify against, so it was not downloaded"
    url = f"https://{CRATE_HOST}/crates/{name}/{name}-{version}.crate"
    try:
        data = http_get(url, MAX_CRATE_BYTES)
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code} from the registry"
    except Exception as exc:                                   # noqa: BLE001
        return False, str(exc)[:160]
    got = hashlib.sha256(data).hexdigest()
    if got != expected.lower():
        # Not a fetch failure. Either the lockfile pins a digest crates.io did
        # not publish, or the bytes changed in flight -- and both are findings
        # rather than gaps, so say the two digests out loud.
        return False, (f"SHA256 MISMATCH: expected `{expected.lower()}`, "
                       f"the registry served `{got}`")
    return unpack_crate(data, dest)


def allowed(url):
    stripped = re.sub(r"^[a-z+]+://", "", url)
    stripped = re.sub(r"^[^/@]+@", "", stripped)          # strip any userinfo
    return any(stripped.startswith(o) for o in ALLOWED_OWNERS)


def git_in(dest, *args, timeout=None):
    return subprocess.run(("git", "-C", dest) + args,
                          timeout=timeout or CLONE_TIMEOUT,
                          capture_output=True, text=True)


def fetch(url, sha, dest, also=None):
    """Fetch the pinned commit, and optionally a second one. (ok, detail).

    `also` is the revision the BASE branch pinned, when this pull request moves
    the pin. Both land in one repository so the two trees can be compared; the
    working tree is checked out at `sha`, which is what the PR pins.
    """
    os.makedirs(dest, exist_ok=True)
    try:
        r = subprocess.run(("git", "init", "--quiet", dest),
                           timeout=CLONE_TIMEOUT, capture_output=True, text=True)
        if r.returncode:
            return False, r.stderr.strip()[:200]
        git_in(dest, "remote", "add", "origin", url)
        # By SHA, so what lands is exactly what the lockfile pins and nothing
        # else -- no branch tip, no tags, no history to be confused by.
        r = git_in(dest, "fetch", "--depth", "1", "--no-tags", "origin", sha)
        if r.returncode:
            return False, (r.stderr.strip() or "fetch failed")[:200]
        r = git_in(dest, "checkout", "--quiet", "FETCH_HEAD")
        if r.returncode:
            return False, r.stderr.strip()[:200]
        if also:
            # Best effort: a bump whose old side cannot be fetched still leaves
            # the new side readable, which is strictly better than nothing.
            git_in(dest, "fetch", "--depth", "1", "--no-tags", "origin", also)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {CLONE_TIMEOUT}s"
    except OSError as exc:
        return False, str(exc)[:200]
    return True, ""


def bump_report(dest, old_sha, new_sha, patch_path):
    """Precompute what a revision bump changed. Returns a list of md lines.

    THE REVIEWER CANNOT RUN GIT HERE. `git -C` is not allowlisted and
    `cd <dir> && git` is refused by a hooks-safety heuristic, so a bump that is
    only "two commits in a repository on disk" is a bump nobody can diff -- which
    is exactly what a published review reported (issue #514: "every git
    invocation against its .git was refused by the sandbox, so 71da8f03 ->
    31c26d96 could not be diffed"). Everything a reviewer needs is written out
    here, the same way PR_SUBMODULES.md precomputes a moved submodule's log.
    """
    out = []
    have_old = git_in(dest, "cat-file", "-e", old_sha + "^{commit}").returncode == 0
    if not have_old:
        out += ["- **The previous revision could not be fetched**, so this bump",
                "  was not diffed. Report the content of the bump as not covered.", ""]
        return out

    # `git diff A B` needs only the two trees, so it works across two shallow
    # fetches with no history connecting them. `git log A..B` does NOT -- it
    # needs the commits between, which a depth-1 fetch of each end does not
    # have. So the diff is the reliable half and the log is best effort.
    stat = git_in(dest, "diff", "--stat", old_sha, new_sha)
    if stat.returncode == 0 and stat.stdout.strip():
        body = stat.stdout.strip().splitlines()
        out += ["- **What changed between the two revisions** "
                f"(`git diff --stat {old_sha[:12]} {new_sha[:12]}`):", "",
                "  ```"]
        out += ["  " + ln for ln in body[:200]]
        if len(body) > 200:
            out.append(f"  ... {len(body) - 200} more lines")
        out += ["  ```", ""]

    log = git_in(dest, "log", "--oneline", "--no-decorate",
                 f"{old_sha}..{new_sha}")
    if log.returncode != 0:
        # One bounded deepen, then give up. Unshallowing a large dependency to
        # print a commit list is not worth a review's clock.
        git_in(dest, "fetch", "--depth", "250", "--no-tags", "origin", new_sha)
        git_in(dest, "fetch", "--depth", "250", "--no-tags", "origin", old_sha)
        log = git_in(dest, "log", "--oneline", "--no-decorate",
                     f"{old_sha}..{new_sha}")
    if log.returncode == 0 and log.stdout.strip():
        commits = log.stdout.strip().splitlines()
        out += [f"- **{len(commits)} commit(s) between them:**", "", "  ```"]
        out += ["  " + c[:160] for c in commits[:100]]
        if len(commits) > 100:
            out.append(f"  ... {len(commits) - 100} more")
        out += ["  ```", ""]
    else:
        out += ["- The commit list between the two revisions is **not available**:",
                "  both ends were fetched shallow and the history joining them was",
                "  not, so nothing can enumerate them. The file-level diff above is",
                "  complete regardless -- it needs only the two trees.", ""]

    patch = git_in(dest, "diff", old_sha, new_sha)
    if patch.returncode == 0 and patch.stdout:
        text = patch.stdout
        note = ""
        if len(text) > MAX_PATCH_BYTES:
            text = text[:MAX_PATCH_BYTES]
            note = (f"\n... truncated at {MAX_PATCH_BYTES} bytes; the stat above"
                    " lists every file that changed.\n")
        try:
            with open(patch_path, "w", encoding="utf-8", errors="replace") as fh:
                fh.write(text + note)
            rel = os.path.relpath(patch_path, os.path.dirname(os.path.dirname(patch_path)))
            out += [f"- **The full patch is at `{rel}`**"
                    + (" (truncated)." if note else "."), ""]
        except OSError as exc:
            out += [f"- The full patch could not be written: `{exc}`.", ""]
    return out


def registry_report(root, registry, base_registry, locked_versions, patch_targets):
    """Check every crates.io package, and put the changed ones on disk.

    TWO DIFFERENT JOBS, deliberately split by cost.

    Checking is cheap and applies to everything: one sparse-index request per
    package says what crates.io actually published for that exact version, and
    comparing it to the lockfile's `checksum` answers a question no review here
    could answer before. Issue #514 had to write "only that all 67 registry
    sources carry SOME checksum was verified" -- a statement about the file's
    shape, not about the registry, and worth much less than it looks.

    Fetching is not cheap and applies only to what a reviewer will open: the
    packages this pull request ADDS OR BUMPS, and any crate `[patch.crates-io]`
    overrides. Unpacking a 67-crate graph would put tens of megabytes of code
    nobody reads under every `rg` the review runs, to answer questions the diff
    did not raise.
    """
    if not registry:
        return []

    out = ["", "# Rust crates.io dependencies", "",
           "Every registry package in this pull request's lockfile(s) is checked",
           "against the crates.io index below: the lockfile records a sha256 for",
           "each one, and the index says what crates.io actually published for",
           "that exact version. A MATCH means the lock pins the real published",
           "artifact. Anything else is named individually.", ""]

    changed, unchanged, missing, mismatched, yanked, unknown_registry = [], [], [], [], [], []
    for (name, version), meta in sorted(registry.items()):
        if not is_crates_io(meta["index"]):
            unknown_registry.append((name, version, meta))
            continue
        was = base_registry.get(name)
        # New crate, or the same crate at a version the base branch did not have.
        is_new = was is None or version not in was
        if not safe_pair(name, version):
            missing.append((name, version, "the name or version is not a shape this will check"))
            continue
        published, is_yanked, err = index_entry(name, version)
        if err:
            missing.append((name, version, err))
        elif meta["checksum"] is None:
            missing.append((name, version, "the lockfile records no checksum for it"))
        elif published != meta["checksum"]:
            mismatched.append((name, version, meta["checksum"], published))
        else:
            (changed if is_new else unchanged).append((name, version))
        if is_yanked:
            yanked.append((name, version))

    out += [f"- **{len(unchanged) + len(changed)} package(s) verified against the index**"
            f" ({len(changed)} of them added or moved by this pull request).",
            f"- **{len(mismatched)} checksum mismatch(es).**"
            + (" See below -- a mismatch is a finding, not a gap." if mismatched else ""),
            f"- **{len(missing)} package(s) could not be checked.**"
            + (" Named below; report them as not covered." if missing else ""),
            ""]

    if mismatched:
        out += ["## Checksum mismatches", "",
                "The lockfile pins a digest crates.io did not publish for that",
                "version. Nothing here explains that away: read it as a finding",
                "and say which crate.", ""]
        for name, version, want, got in mismatched:
            out += [f"- `{name} {version}` — lockfile `{want}`, index "
                    + (f"`{got}`" if got else "(no digest)")]
        out += [""]

    if yanked:
        out += ["## Yanked versions", "",
                "Still installable and still pinned, but withdrawn by their",
                "publisher — often for a defect or an advisory. Worth a line in",
                "the report, and worth asking why the pin is on one.", ""]
        out += [f"- `{name} {version}`" for name, version in yanked] + [""]

    if unknown_registry:
        out += ["## NOT crates.io", "",
                "These come from some other registry. Nothing here knows what its",
                "index looks like or who runs it, so they were neither checked nor",
                "fetched. Report them as not covered.", ""]
        for name, version, meta in unknown_registry:
            out += [f"- `{name} {version}` from `{meta['index']}`"]
        out += [""]

    if missing:
        out += ["## Could not be checked", "",
                "The pin stands unverified for each of these. That is a limit on",
                "the review, not a clean result.", ""]
        for name, version, why in missing:
            out += [f"- `{name} {version}` — {why}"]
        out += [""]

    # ---- source on disk, for what the diff actually raises -----------------
    wanted = []
    for name, version in changed:
        wanted.append((name, version, registry[(name, version)]["checksum"], "added or moved by this pull request"))
    for name in sorted(patch_targets):
        version = locked_versions.get(name)
        if not version:
            out += [f"- `[patch.crates-io]` overrides `{name}`, but no lockfile "
                    "records a version for it, so the registry original could not "
                    "be identified. Report the patch as uncompared.", ""]
            continue
        if any(w[0] == name and w[1] == version for w in wanted):
            continue
        # The lock has no `checksum` for a patched crate -- its source is the
        # fork -- so hold the download to what the index publishes instead.
        published, _, err = (index_entry(name, version) if safe_pair(name, version)
                             else (None, None, "unsafe name or version"))
        if err or not published:
            out += [f"- `[patch.crates-io]` overrides `{name} {version}`, and the "
                    f"registry original could not be identified ({err or 'no digest'}). "
                    "Report the patch as uncompared.", ""]
            continue
        wanted.append((name, version, published,
                       "the REGISTRY ORIGINAL of a crate `[patch.crates-io]` replaces"))

    if not wanted:
        out += ["No crates.io package was added, moved or patched by this pull",
                "request, so no registry source was put on disk. The verification",
                "above still covers the whole graph.", ""]
        return out

    truncated = len(wanted) > MAX_CRATES_FETCHED
    wanted = wanted[:MAX_CRATES_FETCHED]

    out += ["## Source on disk", "",
            "Fetched from the registry and verified byte-for-byte against the",
            "sha256 above before being unpacked — nothing here extracts bytes",
            "that failed that check. Untracked, so `git ls-files` and `git grep`",
            "cannot see them: use `rg` or `find` under `rust-deps/crates/`.", ""]
    if truncated:
        out += [f"**Only the first {MAX_CRATES_FETCHED} are on disk**; this pull",
                "request changed more registry packages than that. The rest are",
                "verified above but unread — report that as not covered.", ""]

    fetched = crate_failed = 0
    for name, version, digest, why in wanted:
        rel = f"rust-deps/crates/{name}-{version}"
        good, detail = fetch_crate(name, version, digest,
                                   os.path.join(root, "rust-deps", "crates",
                                                f"{name}-{version}"))
        if good:
            fetched += 1
            out += [f"- `{name} {version}` — `{rel}/`. {why[0].upper() + why[1:]}."]
        else:
            crate_failed += 1
            out += [f"- `{name} {version}` — **NOT ON DISK**: {detail}. "
                    "The source was not read; report it as not covered."]
    out += [""]
    print(f"crates.io: {len(unchanged) + len(changed)} verified, "
          f"{len(mismatched)} mismatched, {len(missing)} unchecked, "
          f"{fetched} fetched, {crate_failed} fetch failed", file=sys.stderr)
    return out


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
    registry = {}
    locked_versions = {}
    for lock in locks:
        rel = os.path.relpath(lock, root)
        for url, sha, crates in parse_sources(lock):
            sources.setdefault((url, sha), {"crates": set(), "locks": set()})
            sources[(url, sha)]["crates"].update(crates)
            sources[(url, sha)]["locks"].add(rel)
        try:
            with open(lock, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        for key, meta in parse_registry_text(text).items():
            registry.setdefault(key, dict(meta, locks=set()))["locks"].add(rel)
        locked_versions.update(parse_locked_versions(text))

    # `[patch.crates-io]` lives in Cargo.toml, not the lock, and it is the one
    # thing in a Rust dependency graph that swaps a crate for somebody's fork
    # with nothing in the lockfile recording what it replaced.
    patch_targets = set()
    for lock in locks:
        manifest = os.path.join(os.path.dirname(lock), "Cargo.toml")
        if os.path.isfile(manifest):
            patch_targets.update(parse_patch_targets(manifest))

    # What the BASE branch pinned, so a bump can be told from a first
    # appearance -- and, when it is a bump, so both ends can be fetched and the
    # delta precomputed. `git -C` is fine HERE: the restriction that bites is on
    # the reviewer's Bash tool, not on this script, which is an ordinary
    # subprocess in the harness.
    base_revs = {}
    base_registry = {}
    for lock in locks:
        rel = os.path.relpath(lock, root)
        r = git_in(root, "show", f"origin/base:{rel}")
        if r.returncode:
            # The lockfile is new in this pull request, or origin/base is absent
            # (a checkout not prepared by the harness). Either way there is no
            # previous pin to compare against, which is not an error.
            continue
        for url, sha, _ in parse_sources_text(r.stdout):
            base_revs[url] = sha
        for (bname, bver) in parse_registry_text(r.stdout):
            base_registry.setdefault(bname, set()).add(bver)

    lines = ["# Rust git dependencies", ""]
    if not locks:
        lines += ["No `Cargo.lock` in this checkout, so this pull request pins",
                  "no Rust dependencies by git revision.", ""]
    elif not sources:
        lines += [f"Found {len(locks)} `Cargo.lock` file(s), none of which pin a",
                  "dependency by git revision. The crates.io half is below.", ""]
    else:
        lines += ["Pinned by git revision in this pull request's lockfile(s), and",
                  "fetched at exactly that commit so a review can read them. These",
                  "are NOT in the git tree: `git ls-files` and `git grep` cannot see",
                  "them, so use `rg` or `find` under `rust-deps/`.",
                  "",
                  "**You cannot run git in `rust-deps/`.** `git -C` is not allowlisted",
                  "and `cd <dir> && git` is refused by a hooks-safety heuristic, so",
                  "anything that needs history is precomputed below rather than left",
                  "for you to derive. Where this pull request MOVES a pin, the entry",
                  "says so and carries the file-level diff, the commit list where it",
                  "could be obtained, and a path to the full patch.", ""]

    ok = refused = failed = bumps = 0
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
        prev = base_revs.get(url)
        bumped = bool(prev) and prev != sha
        good, detail = fetch(url, sha, dest, also=prev if bumped else None)
        if good:
            ok += 1
            lines += [f"## {name}" + (" — BUMPED BY THIS PULL REQUEST" if bumped else ""), "",
                      f"- Source: `rust-deps/{name}/`, checked out at the revision this PR pins",
                      f"- URL: `{url}`",
                      f"- Pinned at: `{sha}`",
                      f"- Crates used from it: {crates}",
                      f"- Declared in: `{where}`"]
            if bumped:
                bumps += 1
                lines += [f"- **Previous revision (`origin/base`): `{prev}`**", ""]
                lines += bump_report(dest, prev, sha,
                                     os.path.join(root, "rust-deps", name + ".bump.diff"))
            else:
                lines += [""]
        else:
            failed += 1
            lines += [f"## {name} — FETCH FAILED", "",
                      f"- URL: `{url}`",
                      f"- Pinned at: `{sha}`",
                      f"- Crates: {crates}",
                      f"- Declared in: `{where}`",
                      f"- Error: `{detail}`",
                      "- The source was not read. Report this as not covered.", ""]

    lines += registry_report(root, registry, base_registry, locked_versions,
                             patch_targets)

    try:
        with open(os.path.join(root, "RUST_DEPS.md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
    except OSError as exc:
        # The report is the whole mechanism -- it is how a reviewer learns a
        # source was refused or failed. Losing it silently is the one outcome
        # worth shouting about, even though both callers treat this script as
        # non-fatal.
        print(f"warn: could not write RUST_DEPS.md: {exc}", file=sys.stderr)

    print(f"rust deps: {ok} fetched ({bumps} bumped by this PR), "
          f"{refused} refused by allowlist, {failed} failed, "
          f"from {len(locks)} lockfile(s)", file=sys.stderr)


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
