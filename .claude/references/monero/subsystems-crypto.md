# Cryptography subsystems

`src/crypto`, `src/ringct`, `src/fcmp_pp`, `src/multisig`, and the
proof-of-work path through `external/randomx`.

The distinguishing property of this area is that **the same computation is
implemented several ways** — C and assembly, interpreter and JIT, with and
without hardware AES, per architecture — and consensus requires every path to
agree bit for bit. So the highest-value question about a change here is usually
not "is this instruction correct" but **"do all the paths still produce the
same bytes"**.

Verified against master `3d3920d7`.

---

## `src/crypto/` — the primitives

`cncrypto` is five things that live together for historical reasons.

1. **Ed25519 group and scalar arithmetic**, plain C: `crypto-ops.c` (4042
   lines) and `crypto-ops-data.c` (882 lines of precomputed tables, no
   functions). SUPERCOP `ref10` with Monero-specific additions grafted on —
   `ge_fromfe_frombytes_vartime` (the legacy hash-to-point),
   `fe_batch_invert`, `ge_p3_is_point_at_infinity_vartime`, and newer
   FCMP++/Carrot helpers at the end of the file.
2. **The CryptoNote key API**: `crypto.h` / `crypto.cpp`. Key derivation
   (`generate_key_derivation` = `r*A` then mul-by-8), `derive_public_key`,
   `derive_subaddress_public_key`, `derive_view_tag`, Schnorr signatures, tx
   proofs, key images, the legacy ring signature. Only `crypto::crypto_ops`
   has the real implementations; the free functions in `crypto.h` are `inline`
   friend forwarders.
3. **The hash set**: `hash.c` (`cn_fast_hash` = legacy Keccak-1600),
   `keccak.c`, `blake2b.c` (with a Monero-personalised variant),
   `hmac-keccak.c`, `tree-hash.c` (the block Merkle tree), plus the four
   CryptoNight finalizers (blake256, groestl, jh, skein).
4. **Randomness and symmetric crypto**: `random.c` is a Keccak-sponge CSPRNG
   seeded once from `/dev/urandom` by a GCC
   `__attribute__((constructor(101)))` initializer, wrapped in a Boost mutex
   in `crypto.cpp`. `chacha.c` provides chacha8/chacha20 for wallet file and
   cache encryption.
5. **Proof-of-work**: `slow-hash.c` (legacy CryptoNight) and `rx-slow-hash.c`
   (the RandomX shim) — see below.

**`src/crypto/wallet/` is a build-time swap, and it is not opt-in.**
`MONERO_WALLET_CRYPTO_LIBRARY` defaults to `auto`; `monero_crypto_autodetect`
(`external/supercop/functions.cmake`) selects `amd64-64-24k` whenever an
ASM-ATT compiler is available on UNIX with an x86_64 processor, and only falls
back to the in-tree C (`cn`, an alias for `cncrypto`) otherwise. **Exactly two
functions are swapped**: `monero_crypto_generate_key_derivation` and
`monero_crypto_derive_subaddress_public_key`. So on a typical Linux release
build the wallet's hot derivation path is hand-written assembly from
`external/supercop`, not `crypto-ops.c` — and the two must agree. Note
supercop's `generate_key_derivation` performs three doublings after the scalar
multiplication to clear the cofactor, described in the source as
"non-standard, monero specific".

**Comparison and hashing idioms** (`generic-ops.h`):
`CRYPTO_MAKE_COMPARABLE` is a plain `memcmp`;
`CRYPTO_MAKE_COMPARABLE_CONSTANT_TIME` uses libsodium's `crypto_verify_32`.
Which macro a key type is registered with decides whether comparing it leaks
timing. `CRYPTO_DEFINE_HASH_FUNCTIONS` uses SipHash-2-4 keyed by a process
`crypto_siphash_key`.

**Recurring questions worth asking of any change here.** Is a point
deserialized from the wire checked to be on the curve, and for torsion where
the protocol requires it? Is a scalar reduced, and is reduction *checked*
rather than assumed? Is a comparison on secret material constant time
(`memcmp` on key material is a finding even when the channel is small)? Do
identity, zero and negated points behave? And — the one specific to this tree
— **do the wallet and the daemon apply the same validation to the same
object**? A divergence is itself the bug, independent of which side is
stricter.

---

## `src/ringct/` — RingCT

Everything a v2 transaction must prove: that each output commitment encodes a
value in range, that the signer owns a ring member and the commitments
balance, and that the whole thing is bound to a specific prefix and mix ring.

**The CMake split matters.** Everything except `rctSigs.cpp` builds as
`ringct_basic` (links only `common` + `cncrypto`); `rctSigs.cpp` builds as
`ringct` and is the only part that pulls in `device` and `fcmp_pp`.

**The type zoo** (`rctTypes.h`, an **anonymous** enum, so these are untyped
`int` constants and `rctSigBase::type` is a `uint8_t`):

```
RCTTypeNull = 0   RCTTypeFull = 1   RCTTypeSimple = 2   RCTTypeBulletproof = 3
RCTTypeBulletproof2 = 4   RCTTypeCLSAG = 5   RCTTypeBulletproofPlus = 6
```

**The predicates do not partition the way their names suggest.**
`is_rct_bulletproof` covers exactly `{Bulletproof, Bulletproof2, CLSAG}` — it
is **false** for `RCTTypeBulletproofPlus`. Check the definition before relying
on one.

**Where dimension validation lives.** `serialize_rctsig_prunable` in
`rctTypes.h` is the first line of defence, and `n_bulletproof_max_amounts_base`
/ `n_bulletproof_amounts_base` in `rctTypes.cpp` are the single place the
L-vector length is bounded: `6 <= L.size() <= 6 + extra_bits`,
`L.size() == R.size()`, and a `V`/`L` consistency pair. **Bulletproof indexing
and buffer-sizing bugs are usually fenced by this** — check it before
reporting one.

**Invariants.**

- Every scalar read from an untrusted proof passes `sc_check` before use —
  CLSAG `s[]` and `c1`, MLSAG `ss[][]` and `cc`, the Bulletproof and
  Bulletproof+ scalars via `is_reduced`.
- Every group element is either decoded with `ge_frombytes_vartime` (which
  rejects non-canonical encodings) or multiplied by the cofactor via
  `rct::scalarmult8` before it can influence a decision.
- Points that must not be the identity are checked explicitly: CLSAG `sig.I`
  and `D_8`, MLSAG `rv.II[i]`, each derived bulletproof generator.
- Fiat-Shamir challenges must be non-zero; both provers loop rather than emit
  a proof with a zero challenge.
- `get_pre_mlsag_hash` is the **single definition of what a signature covers** —
  the prefix, the rct base fields and the range-proof fields. A new proof type
  has to be folded in there.
- The balance equation `sum(outPk.mask) + txnFee*H == sum(pseudoOuts)` is
  checked in `verRctSemanticsSimple` *before* any signature work.
- Batch verification draws random weights, but they change only which linear
  combination is tested, never the verdict.

**Traps.**

- **`rctTypes.h` is not a header of declarations** — the consensus
  deserializer lives there, so a shape-validation change is a header change
  that recompiles most of the tree.
- **`bulletproofs.cc` and `bulletproofs_plus.cc` contain independent static
  definitions of the same helper names** — `multiexp`, `is_reduced`,
  `get_exponent`, `init_exponents`, `invert`, `Hi_p3`, `Gi_p3`, `TWO`,
  `MINUS_ONE`. Always check which file you are in.
- **`rct::cn_fast_hash` and `rct::hash_to_scalar` shadow the `crypto::`
  versions**, and both `rctSigs.cpp` and `rctOps.cpp` say `using namespace
  crypto;` at the top. `rctOps.h` carries a comment warning about it.
- **Two key-equality routines, both used.** `rct::key::operator==` is
  `crypto_verify_32` (constant time); `rct::equalKeys` is a hand-written byte
  loop.
- **`Bulletproof::V` is commented out of the serializer** and reconstructed by
  `expand_transaction_1`, so it is not covered by the transaction hash.
- **A second, independent CLSAG challenge implementation lives in
  `src/multisig/multisig_clsag_context.cpp`** and must reproduce
  `verRctCLSAGSimple`'s `mu_P`, `mu_C` and round hashes exactly.
- `make_dummy_bulletproof`, `make_dummy_bulletproof_plus` and
  `make_dummy_clsag` (anonymous namespace at the top of `rctSigs.cpp`) produce
  structurally valid, cryptographically meaningless proofs for fee estimation.
- `bulletproof_PROVE` has a `goto try_again` backwards jump for a zero
  challenge.
- `bos_coster_heap_conv_robust` in `multiexp.cc` has no production caller — it
  is a reference implementation for tests.
- `rct::zeroCommitVartime` is fast for ~180 tabulated amounts and
  slow-and-data-dependent otherwise; the name is the only warning.
- `rct::key64` is `typedef key key64[64]` — an array type, so a parameter
  declared `const key64` is a pointer and `cn_fast_hash(const key64)` hashes
  exactly 64×32 bytes with no size argument.
- `rctOps.cpp` is 749 lines but 58 KB: about 190 of those lines are one static
  table of precomputed zero commitments. Line count misrepresents it.

---

## `src/fcmp_pp/` — Full-Chain Membership Proofs, as of master

**Staged, not live.** Get this right in both directions: the code is present
and in the build, and it is not consensus-reachable today.

What exists: `curve_trees.{h,cpp}`, `fcmp_pp_crypto.{h,cpp}`,
`fcmp_pp_types.{h,cpp}`, `tower_cycle.{h,cpp}`, `ffi_api_c_compat.c` (a 46-byte
C-compatibility probe), and `fcmp_pp_rust/` — a Rust crate.

**Monero master builds Rust.** `src/fcmp_pp/CMakeLists.txt` links
`libfcmp_pp_rust.a`, whose manifest pulls `ciphersuite 0.4.2` and
`dalek-ff-group 0.5.0` from crates.io, `helioselene` from a git revision of
`github.com/monero-oxide/monero-oxide`, and patches `crypto-bigint` to a branch
of a personal fork. Both profiles set `panic = "abort"` and
`overflow-checks = true`. CI pins a rustup toolchain by SHA-256; `contrib/depends`
carries a `rust_host` per cross target. **A change under `fcmp_pp_rust/` is a
supply-chain change**, whatever the diff looks like.

CMake `try_compile`s `ffi_api_c_compat.c` and fails the build with "The FCMP++
FFI API header 'fcmp++.h' has broken compatibility with C" if the generated
header stops being C-compatible.

**The only live consumer** is `src/ringct/rctSigs.cpp`, which includes
`fcmp_pp/fcmp_pp_crypto.h` and calls
`fcmp_pp::get_valid_torsion_cleared_point_vartime` from
`rct::verPointsForTorsion`. That function has **no production caller** — it
appears only in `rctSigs.h`, `rctSigs.cpp` and `tests/unit_tests/crypto.cpp`.
`RCTType` still stops at `RCTTypeBulletproofPlus = 6`.

`fcmp_pp_crypto.h` exports `mul8_is_identity_vartime`,
`clear_torsion_vartime`, `get_valid_torsion_cleared_point_vartime`,
`point_to_ed_derivatives`, `ed_derivatives_to_wei_x_y`, `point_to_wei_x_y` and
`struct EdDerivatives`.

Treat FCMP++ as **new code**, not as an extension of `src/ringct/` — it brings
a curve cycle with its own field implementations, divisor constructions, and a
generalized Bulletproofs variant. Two notes from prior review of this area:
apparent problems with divisor arithmetic modulo the field prime, and with
point-versus-negation handling, are frequently refuted by the surrounding
construction; and the wallet-side tree/state caching is ordinary memory-safety
territory, distinct from the proof mathematics.

---

## `src/multisig/` — N-of-M key setup and signing

3714 lines, dominated by `multisig_account_kex_impl.cpp` (952 — the key
exchange rounds) and `multisig_tx_builder_ringct.cpp` (1046 — collaborative
CLSAG signing). Plus `multisig_account.{h,cpp}`, `multisig_kex_msg.{h,cpp}`
and its serialization, `multisig_clsag_context.{h,cpp}`, and `multisig.{h,cpp}`.

The security question here is usually **authentication of configuration, not
arithmetic**: can a participant, or someone impersonating one, alter the set of
signers, their addresses, or the threshold — and would the others notice?
"Would notice" depends on a confirmation actually being shown, which depends on
which wallet consumer is in play (see `subsystems-wallet.md`).

Two structural facts worth carrying: `multisig_clsag_context.cpp` reimplements
the CLSAG challenge and must match `rct::verRctCLSAGSimple` exactly; and
multisig nonces are single-use, with `memwipe` sites in `wallet2.cpp` carrying
the comment "CRITICAL: a nonce may only be used once!".

The message transport (`src/wallet/message_store.*`) is in the wallet
directory, not here.

---

## Proof-of-work: `src/crypto/rx-slow-hash.c` and `external/randomx`

**`rx-slow-hash.c` (524 lines) is the entire Monero side.** Everything under
`external/randomx` is upstream `tevador/RandomX`, vendored as a submodule and
held to upstream's standards.

**Seed height arithmetic** is consensus:
`rx_seedheight(height) = (height <= blocks + lag) ? 0 : (height - lag - 1) & ~(blocks - 1)`
with `SEEDHASH_EPOCH_BLOCKS` 2048 and `SEEDHASH_EPOCH_LAG` 64. Both are
overridable from the environment, and both change consensus-visible behaviour.
`rx_set_main_seedhash` is called by `Blockchain` on init, pop, reorg and new
top block.

**Where the paths could disagree** — the questions that matter:

- **Interpreter vs JIT vs light vs full memory.** `randomx_create_vm` is a
  24-arm switch on `(FULL_MEM|JIT|HARD_AES|LARGE_PAGES)`. All must produce
  identical output.
- **Rounding mode.** The `CFROUND` instruction must set the same effective
  mode in every backend; `randomx_calculate_hash` brackets the whole
  computation with `_mm_getcsr`/`_mm_setcsr` or `fegetenv`/`fesetenv`, and the
  MXCSR default `0x9FC0` is baked into the x86 JIT byte sequence as well as
  `intrin_portable.h`.
- **Configuration.** Every consensus parameter is in
  `external/randomx/src/configuration.h`; changing one byte forks the chain.
  Instruction frequencies are pinned by `static_assert(wtSum == 256)`. For
  MSVC builds a checked-in generated `configuration.asm` must match the
  header.
- **A bug on a path no production node uses** (an unusual architecture, a
  disabled build option) is a LOW, not a consensus break. Establish which
  paths ship before assigning severity.

**Traps.**

- **`external/supercop` has nothing to do with proof of work**, despite often
  being listed alongside it. It is amd64 ed25519 for *wallet* key derivation
  (see `src/crypto/wallet/` above).
- **`slow-hash.c` contains four complete definitions of `cn_slow_hash`** (at
  four different lines), selected by nested `#if` on `NO_AES` / `__x86_64__` /
  MSVC / `__arm__` / `__aarch64__`. Read backwards to the nearest `#if` to
  know which one you are looking at.
- **PoW is frequently not computed at all.** With `PER_BLOCK_CHECKPOINT` (on
  by default) and a matching embedded hash, `handle_block_to_main_chain` sets
  `fast_check` and skips it.
- **`RANDOMX_FLAG_FULL_MEM` is opt-in on the verification side** —
  `rx_alloc_dataset` refuses unless `MONERO_RANDOMX_FULL_MEM` is set or the
  caller is a miner thread.
- **`RANDOMX_FLAG_SECURE` is added for non-miner JIT VMs only**
  (`if ((flags & RANDOMX_FLAG_JIT) && !miner_thread)`).
- **The VM alias names invert the `softAes` boolean** —
  `CompiledVmDefault = CompiledVm<…, true, false>` where the `true` is *not*
  soft AES. Read the template parameters, not the name.
- **Two unrelated families of `get_block_longhash`** exist, and the
  `blockchain.cpp` calls that look like they pass a thread count do not.
  `get_altblock_longhash` calls `rx_slow_hash` unconditionally — it does not
  check `major_version` and does not honour the 202612 exception; its caller
  guards that.
- `assert()` in the vendored code is compiled out under `-DNDEBUG`, taking
  `randomx_init_dataset`'s bounds assert and `initCache`'s input validation
  with it.
- `rx_slow_hash_allocate_state` is an **empty function** kept for symmetry;
  do not read its call site as evidence that RandomX allocates anything there.
- `slow_hash_allocate_state` / `slow_hash_free_state` are declared in **no
  header** — callers write a local `extern "C"` declaration.
- The error strategy in `rx-slow-hash.c` is `local_abort()`: log, then
  `_exit(1)` under NDEBUG. There is no error return.

---

## `tests/fuzz/` is a map of this area

The fuzz target list tells you which surfaces upstream already treats as
attacker-reachable. Cryptography-relevant targets: `bulletproof`,
`bulletproof-plus`, `clsag`, `clsag_cout`, `clsag_message`, `clsag_pubs`,
`signature`, `cold-outputs`, `cold-transaction`. A PR touching a surface with
an existing target is touching something known to be reachable; a PR that
*weakens* a harness is worth a note even though it ships nothing.
