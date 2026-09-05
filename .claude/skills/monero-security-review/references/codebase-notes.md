# Codebase notes

Orientation for reviewing this tree: what lives where, what each subsystem is
supposed to guarantee, and the questions that have historically been worth
asking of each. Verify paths against the checkout — this is a map, not a
substitute for reading the code.

**This file is the judgement half.** For how the code actually works — the
library graph, end-to-end traces, per-subsystem symbol maps, the macro
families, the coding dialects, threading — see `.claude/references/monero/`,
which every skill here shares. Read `macros.md` there before trusting any
grep result.

## Four serialization systems, not one

This is the most important structural fact about the codebase, and the easiest
to get wrong. Two of them carry most of the risk and are described below; the
full set — including the newer epee `wire` layer (write-only on master) and
`boost::serialization` for persisted local state — is in
`.claude/references/monero/architecture.md`.

**`contrib/epee/`** is a general-purpose library predating much of the project,
with its own conventions. It carries `portable_storage` (the object
serialization used by RPC and P2P payloads), the Levin protocol, and an HTTP
client and server. It is written in a different style from `src/` — heavier on
macros, looser on error handling — and it sits directly on the network.

**`src/serialization/`** is the template-based binary/JSON archive machinery
used for blocks, transactions, and the wallet cache.

Because both parse attacker-supplied bytes, both are worth checking, and a
change to either has a blast radius much wider than the diff suggests. When a
PR touches `contrib/epee`, ask which network-facing callers inherit the change —
the answer is usually "all of them".

Recurring questions for either system:

- Does a length, count, or size field read from the wire reach an allocation
  before it is bounded? Bounds must exist in the read path, not in the caller.
- Is the bound proportional to what actually arrived, or absolute? A count that
  is "checked" against a constant much larger than any real message still
  permits large allocation from a small input.
- Do serialization and deserialization agree? An object that serializes to
  something that will not deserialize — or that deserializes to a *different*
  object — is a consensus problem, not a cosmetic one.
- Is the parse depth bounded? Nested structures invite recursion.

## Consensus surfaces

`src/cryptonote_core/blockchain.cpp`, `tx_pool.cpp`,
`src/cryptonote_basic/`, `src/blockchain_db/lmdb/`

The question here is never only "does it crash". It is **"would a node running
this code reach a different accept/reject verdict than the rest of the network
on some input"**. That reframing catches changes that look like refactors.

Fork gating lives in `src/hardforks/hardforks.cpp` with `HF_VERSION_*`
constants. Any behaviour change must be gated to the correct version. Ask
explicitly: if this node and an unpatched node both see the same block, do they
agree? An ungated change to validation is a consensus split even when the new
behaviour is more correct.

Watch for ordering and tie-breaks. Sorting, iteration order over an unordered
container, and comparator changes can all alter a verdict while looking
innocuous.

## Crypto

`src/crypto/` holds the primitives — Ed25519 group operations
(`crypto-ops.c`, `crypto-ops-data.c`), key derivation, hashing, and RNG.
`src/ringct/` holds the transaction-level constructions: CLSAG, Bulletproofs
and Bulletproofs+, multiexponentiation.

Questions that repeatedly matter:

- **Point validation.** Is a point deserialized from the wire checked to be on
  the curve, and checked for torsion / small-subgroup membership where the
  protocol requires it? Missing torsion checks are a recurring theme, and the
  requirement is not uniform — some places legitimately do not need one.
- **Consistency between wallet and consensus.** If the wallet and the daemon
  apply *different* validation to the same object, that divergence is itself the
  bug, independent of which one is stricter.
- **Scalar range.** Is a scalar reduced, and is reduction checked rather than
  assumed?
- **Constant time.** Comparison or branching on secret material. Note that
  `memcmp` on key material is a finding even when the timing channel is small.
- **Degenerate inputs.** Identity, zero, and negated points. Can a proof be
  satisfied by a degenerate value that the verifier accepts?

Bulletproofs/BP+ indexing and buffer-sizing bugs are usually fenced by
dimension validation during deserialization — see `refutations.md` before
reporting one.

## Proof-of-work

RandomX is vendored under `external/`. Its defining property for review purposes
is that **the same computation is implemented several ways** — interpreter and
JIT, with and without hardware AES, across architectures — and consensus
requires that every path produce identical output for identical input.

So the highest-value question for any RandomX change is not "is this
instruction correct" but "do all execution paths still agree". A change that is
correct in the interpreter and subtly different in the JIT is a chain split.
Buffer sizing, dataset initialisation, and floating-point rounding-mode handling
are where paths diverge in practice. Note that a bug on a path no production
node uses (an unusual architecture, a disabled build option) is a LOW, not a
consensus break — establish which paths ship before assigning severity.

## The wallet has three different consumers

`src/wallet/wallet2.cpp` is the library. Three things build on it, and they do
**not** share a threat model:

- **`wallet-rpc`** (`wallet_rpc_server.cpp`) — long-running, often on a server,
  often automated. Something that requires user interaction to trigger may be
  unreachable here; something that processes daemon responses automatically is
  worse here than elsewhere.
- **`wallet_api` / libwallet** (`src/wallet/api/`) — what the GUI and mobile
  wallets use. Threading behaviour differs from the CLI: background refresh
  runs concurrently with user-driven calls, so state that the CLI touches
  serially can be touched concurrently here.
- **`simplewallet`** — the CLI.

A finding that is real in one of these may be unreachable in another. **State
which consumer you mean.** "Affects the wallet" is not specific enough to act
on, and getting this wrong in either direction wastes the reader's time.

The governing threat model for wallet-side findings: a user runs a wallet
against a **remote node they do not control**, which is the common
configuration. The daemon is untrusted. Severity is high because keys are in
the process.

## Concurrency

Wallet refresh, RPC handling, and user-driven calls run on different threads.
Two questions, in order:

1. Is the state genuinely reachable from two threads at once, or is it
   serialized by an existing lock or by the refresh cycle? A great many
   apparent races turn out to be sequenced by something already there — and if
   an operation is serialized, an attacker-influenced write to it is
   deterministic rather than racy, which changes both the analysis and the
   severity.
2. If it is genuinely concurrent, what does the attacker control about the
   timing? A race that requires winning a window an attacker cannot influence
   is weaker than one they can drive.

Both directions are errors: calling a serialized operation a race overstates it;
missing that a refresh writer runs alongside an API reader understates it.

## Multisig

`src/multisig/` and the messaging layer in `src/wallet/` handle multi-party key
setup and signing. The security question is usually **authentication of
configuration**, not arithmetic: can a participant, or someone impersonating
one, alter the set of signers, their addresses, or the threshold, and would the
other participants notice?

Any confirmation step that a user is expected to check is only a control if it
is actually shown. Automated or batched flows that skip a prompt turn a
"the user would notice" defence into no defence at all. Check the flow, not just
the prompt's existence.

## Hardware wallet interface

`src/device/` and `src/device_trezor/` mediate between wallet logic and an
external signer. The device is supposed to be the thing that cannot be tricked,
so the question is what the host can convince it to do: whether every value the
device commits to is one it derived or verified itself, rather than one the host
supplied. Key derivation, output-index handling, and change-detection are where
host-supplied values do damage.

## FCMP++ work

`src/fcmp_pp/` is on master and in the build, and it is **not
consensus-reachable**. Get that right in both directions: the only consumer
outside the directory is `rct::verPointsForTorsion` in `src/ringct/rctSigs.cpp`,
and that function has no production caller at all — only
`tests/unit_tests/crypto.cpp`. `RCTType` still stops at
`RCTTypeBulletproofPlus = 6`.

**It also means Monero master builds Rust.** `src/fcmp_pp/fcmp_pp_rust/` is a
staticlib crate linked as `libfcmp_pp_rust.a`, pulling `helioselene` from a git
revision and patching `crypto-bigint` to a fork branch. A change under there is
a supply-chain change whatever the diff looks like.

If the branch under review touches Full-Chain Membership Proofs, it brings new
curve arithmetic (a curve cycle with its own field implementations), divisor
constructions, and a generalized Bulletproofs variant. Treat it as new code
rather than as an extension of `src/ringct/`.

Two notes from prior review of this area: apparent problems with divisor
arithmetic modulo the field prime, and with point-vs-negation handling, are
frequently refuted by the surrounding construction — check the protocol's own
constraints before reporting. And the wallet-side tree/state caching is
ordinary memory-safety territory, distinct from the proof mathematics.

## `tests/fuzz/` is a map

The fuzz targets in `tests/fuzz/` tell you which surfaces upstream already
considers untrusted, and which parsers are meant to be robust. Two useful
readings:

- A PR that touches a surface with an existing fuzz target is touching something
  known to be attacker-reachable.
- A PR that *weakens* a harness — reduces coverage, stubs out a check, narrows
  the input space — is worth a LOW note even though it ships nothing, because
  it reduces the chance of catching the next bug.

Changes confined to `tests/` are not vulnerabilities. Say so and move on.

## Build and packaging

`CMakeLists.txt`, `contrib/depends/`, `.github/workflows/`, and the Guix
configuration are a supply-chain surface. Removing a hardening flag
(`_FORTIFY_SOURCE`, stack protector, RELRO, PIE), changing a dependency's source
URL or pinned hash, or altering a reproducible-build input is a real finding
even though it is not a memory-safety bug.
