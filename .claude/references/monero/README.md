# Monero codebase reference

What the `monero-project/monero` tree is, how its parts fit together, and how
to read it without being misled. **Shared by every skill in this repository** —
this directory belongs to no one skill.

Written against master `3d3920d7` (2026-09-03). Every path and symbol here was
confirmed against a checkout; line numbers are used sparingly, because they rot
first. When something disagrees with the tree in front of you, **the tree
wins** — and fix the file.

## What is here

| file | read it when |
|---|---|
| **`architecture.md`** | you need the shape: what ships, the library graph, the four serialization systems, where the consensus fence is |
| **`flows.md`** | a change sits somewhere in one of six end-to-end paths and you need to know what happens before and after it |
| **`subsystems-node.md`** | the diff touches epee, serialization, p2p, the protocol handler, core, blockchain, the DB, rpc, the daemon or `src/common` |
| **`subsystems-wallet.md`** | the diff touches `wallet2`, wallet-rpc, `wallet_api`, simplewallet or the device layer |
| **`subsystems-crypto.md`** | the diff touches `src/crypto`, `src/ringct`, `src/fcmp_pp`, multisig or proof-of-work |
| **`macros.md`** | **before believing any grep result**, and before saying "nothing calls this" or "this field is unvalidated" |
| **`coding-style.md`** | you are about to comment on style, or need to know which of the four dialects a hunk belongs to |
| **`errors-and-concurrency.md`** | before judging a failure path, and before calling anything a race |
| **`build-and-tests.md`** | the diff touches CMake, `contrib/depends`, `contrib/guix`, CI or `tests/` |
| **`navigation.md`** | you are looking for something and want the recipe that actually works |

## Suggested order for a change you have not seen before

1. `architecture.md` — 5 minutes, and it prevents most category errors.
2. The one flow in `flows.md` that the change sits inside.
3. The matching section of the relevant `subsystems-*.md`.
4. `macros.md` before you trust a search.

## The five facts most likely to save you

1. **`.inl` files are implementations.** `src/p2p/net_node.inl` and
   `src/cryptonote_protocol/cryptonote_protocol_handler.inl` are 3188 and 2917
   lines of production networking code. A search that skips `*.inl` misses the
   two most attacker-exposed files in the daemon.
2. **Four serialization systems, not two** — epee `portable_storage` (RPC and
   P2P payloads), `src/serialization` (consensus blobs), the newer epee `wire`
   (write-only on master), and `boost::serialization` (persisted local state).
   A type can be in three of them, and the one nearest its definition is often
   not the one that runs.
3. **The epee KV serializer never fails.** A missing or malformed RPC request
   field leaves the member at its default and parsing continues. The
   consensus serializer is the opposite — it fails closed.
4. **Most control flow is macro-generated.** `CHECK_AND_ASSERT_MES` is a
   `return`; `THROW_WALLET_EXCEPTION_IF` is a `throw` — and a bare `if`.
   `grep 'throw '` finds about a quarter of the raise sites.
5. **"Affects the wallet" is not specific enough.** `monero-wallet-rpc`,
   `wallet_api` and `monero-wallet-cli` have different threat models and
   different concurrency. Name the one you mean.

## Relationship to the review references

These files describe **what the code is**. The three files in
`.claude/skills/monero-security-review/references/` describe **what to suspect
and what has already been refuted**:

- `trust-boundaries.md` — where untrusted data enters, and severity anchoring.
- `codebase-notes.md` — the review-oriented map, and the questions worth asking
  of each subsystem.
- `refutations.md` — the recurring reasons candidate findings here turn out to
  be unreachable. **Read it before reporting anything.**

Use both: this directory to understand the code, those three to judge it.

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
