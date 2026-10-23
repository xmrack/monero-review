# Monero codebase reference

What the `monero-project/monero` tree is, how its parts fit together, and how
to read it without being misled. **Shared by every skill in this repository** —
this directory belongs to no one skill.

Written against master `8308dee67` (2026-10-13). Where a file names its own
verification commit, that commit is what it was last checked against. Every
path and symbol was confirmed against a checkout. Cite files and symbols, never line numbers or
counts that drift; give the grep that finds them instead. When something disagrees with the tree in front of you, **the tree
wins** — and fix the file.

## What is here

| file | read it when |
|---|---|
| **`architecture.md`** | you need the shape: what ships, the layer graph, the four serialization systems, vendored code and the Rust boundary, where the consensus fence is |
| **`flows.md`** | a change sits somewhere in one of six end-to-end paths and you need to know what happens before and after it |
| **`subsystems-node.md`** | the diff touches epee, serialization, p2p or `src/net`, the protocol handler, core, blockchain, the DB, rpc, the daemon or `src/common` |
| **`subsystems-wallet.md`** | the diff touches `wallet2`, wallet-rpc, `wallet_api`, simplewallet or the device layer |
| **`subsystems-crypto.md`** | the diff touches `src/crypto`, `src/ringct`, `src/fcmp_pp`, multisig or proof-of-work |
| **`subsystems-fcmp-carrot.md`** | the diff is FCMP++/Carrot integration work: `src/carrot_core`, `src/carrot_impl`, `RCTTypeFcmpPlusPlus`, Carrot outputs, the curve tree in the DB, wallet tree sync, fork gating or `external/mx25519` |
| **`macros.md`** | **before believing any grep result**, and before saying "nothing calls this" or "this field is unvalidated" |
| **`coding-style.md`** | you are about to comment on style, or need to know which of the four dialects a hunk belongs to |
| **`errors-and-concurrency.md`** | before judging a failure path, and before calling anything a race |
| **`build-and-tests.md`** | the diff touches CMake, `contrib/depends`, `contrib/guix`, CI or `tests/` |
| **`navigation.md`** | you are looking for something and want the recipe that actually works |

The four below are the **judgement half** — not what the code is, but what to
suspect of it and what has already been refuted:

| file | read it when |
|---|---|
| **`trust-boundaries.md`** | you need the threat model: what is protected, who the adversaries are, where untrusted data enters, and how to rate what you find |
| **`codebase-notes.md`** | you want the questions that have historically been worth asking of the subsystem in front of you |
| **`lenses.md`** | you were given a weakness class: where in this tree that class lives, what to ask, and the parallel implementations a guard has to cover |
| **`refutations.md`** | **before reporting anything** — the recurring reasons candidate findings here turn out to be unreachable |

The four below are the **history half** — what audits, papers and past
incidents found, and the diff shapes that would repeat them. They were checked
against master `8340be5e9`, fcmp++-stage `62bb16299` and monero-oxide
`31c26d96e`; cite the audit, paper or disclosure a section names.

| file | read it when |
|---|---|
| **`audits-crypto.md`** | the diff touches key images, ring signatures (CLSAG/MLSAG), Bulletproofs or BP+, the multi-exponentiation code, RingCT amounts, hashing or hash-to-point, RandomX, multisig, or off-chain protocols (atomic swaps, payment channels) |
| **`audits-fcmp-carrot.md`** | the diff touches FCMP++, the membership proof, SA/L, Generalized Bulletproofs, the divisor gadget, curve trees, Helios/Selene, monero-oxide, Carrot, or Seraphis and post-quantum successors; its "Looks like a bug, is not" section goes with `refutations.md` before calling a torsion or "unconstrained value" observation a bug |
| **`past-vulnerabilities.md`** | the diff touches wallet scanning and `tx_extra`, deserialization, RPC or P2P handlers, hardware wallets, decoy selection or P2Pool-facing code: what broke before and the diff shape that would break it again |
| **`privacy-and-network.md`** | the diff touches decoy selection, relay and Dandelion++, anonymity networks, peer selection, what the wallet asks a daemon, or subaddresses and address privacy; and for every privacy (OBSERVER-angle) verdict |

> Nothing in this resource is intended to express any opinions for any audit firms. Please review their source documents for their own words. Summaries here may not fully cover the nuances of their opinions and observations.

## Suggested order for a change you have not seen before

1. `architecture.md` — 5 minutes, and it prevents most category errors.
2. The one flow in `flows.md` that the change sits inside.
3. The matching section of the relevant `subsystems-*.md`.
4. `macros.md` before you trust a search.

## The five facts most likely to save you

1. **`.inl` files are implementations.** `src/p2p/net_node.inl` and
   `src/cryptonote_protocol/cryptonote_protocol_handler.inl` are roughly three
   thousand lines each (`wc -l` them) of production networking code. A search that skips `*.inl` misses the
   two most attacker-exposed files in the daemon.
2. **Four serialization systems, not two** — epee `portable_storage` (RPC and
   P2P payloads), `src/serialization` (consensus blobs), the newer epee `wire`
   (write-only on master), and `boost::serialization` (persisted local state).
   A type can be in three of them, and the one nearest its definition is often
   not the one that runs.
3. **The epee KV serializer almost never fails.** A missing RPC request
   field, or a blob field of the wrong size, leaves the member at its default
   and parsing continues; only a scalar whose type or range does not fit the
   member throws. The consensus serializer is the opposite — it fails closed.
4. **Most control flow is macro-generated.** `CHECK_AND_ASSERT_MES` is a
   `return`; `THROW_WALLET_EXCEPTION_IF` is a `throw` — and a bare `if`.
   `grep 'throw '` finds only a fraction of the raise sites (see `macros.md`).
5. **"Affects the wallet" is not specific enough.** `monero-wallet-rpc`,
   `wallet_api` and `monero-wallet-cli` have different threat models and
   different concurrency. Name the one you mean.

## The three halves, and why all of them

Most of this directory describes **what the code is**. `trust-boundaries.md`,
`codebase-notes.md` and `refutations.md` describe **what to suspect of it**.
The audit, vulnerability and privacy files record **what has already been
found**. Use all three: the first to understand the code, the second to judge
it, the third to recognise a known bug class or a settled question. A finding
that skips the first is usually a category error; one that skips the others
has usually already been refuted or reported.

## Keeping it honest

A reference nobody re-checks is worse than no reference. Two rules:

- **When you find something here that is wrong, fix it in the same change**
  that discovered it, and say so. Every skill reads these files; a correction
  here improves all of them at once.
- **Prefer a symbol name to a line number**, and a measured count to an
  impression. Where a claim was measured, the command that measured it is
  usually next to it — re-run it rather than trusting the number.

Known gaps, deliberately left rather than guessed at: the `src/device_trezor`
protobuf layer, the Ledger implementation of the signing protocol, and the
internals of the FCMP++ Rust crate are described only at their boundaries.
