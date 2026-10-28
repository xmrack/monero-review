# Classic Monero cryptography: past audits, papers, and what they mean for a diff

> Nothing in this resource is intended to express any opinions for any audit firms. Please review their source documents for their own words. Summaries here may not fully cover the nuances of their opinions and observations.

Written against master `3fd0f88c2` (2026-10-25).

Past audits and papers on the cryptography Monero runs without FCMP++ or
Carrot: key images, ring signatures, Bulletproofs and BP+, RingCT amounts,
hash-to-point, the block Merkle tree, RandomX, multisig and off-chain
protocols. What the code *is* lives in `subsystems-crypto.md`; FCMP++ and
Carrot are in `subsystems-fcmp-carrot.md`. Severities are as each source rated
them; where a source gave none, this file says so. Read the section for the
code a diff touches, then run the checklist in section 9.

---

## 1. Key images and the cofactor

Ed25519 has order `8*l`; every CryptoNote proof assumes a prime-order group.
Where a value must be *unique* (key image, serial number, linking tag), the
code must enforce that itself. Where a value only *carries a quantity* (an
amount commitment), clearing the cofactor is enough.

### 1.1 The 2017 key-image bug (critical, public)

No subgroup check on key images: `I + T`, with `T` a torsion point, still
verified when the relevant scalars were multiples of 8 (chosen or ground for),
and the spent set is a byte lookup, so up to 8 spends per output, undetectable
inflation in every CryptoNote coin. Found by an MRL member on 2017-02-19; the
chain was unexploited; the fix shipped quietly (PR #1744), a hard fork made it
universal, and luigi1111 and Spagni disclosed it on 2017-05-17, rated
critical. The whitepaper's linkability proof takes `log_{Hp(P)} I`, which
exists only if `I` is in the prime-order subgroup.

**Where the fix lives.**

- `core::check_tx_inputs_keyimages_domain` (`src/cryptonote_core/cryptonote_core.cpp`)
  rejects `I == identity` and requires `scalarmultKey(I, curveOrder()) == identity`.
  It is called from `core::check_tx_semantic`, which
  `cryptonote::ver_non_input_consensus` (`tx_verification_utils.cpp`) runs for
  pool and block transactions.
- `crypto_ops::check_ring_signature` (`src/crypto/crypto.cpp`, pre-RingCT
  and reserve proofs) has rejected identity and torsioned key images itself
  (`ge_p3_is_point_at_infinity_vartime` on `l*I`) only since PR #11155
  (merged September 2026).
- `verRctCLSAGSimple` and `MLSAG_Ver` reject only `I == identity`. **For
  RingCT the subgroup check exists only in the core domain check.**
- `ge_frombytes_vartime` rejects non-canonical encodings, so a valid key
  image has one byte form.

**A PR is risky here if it** adds an ingest path that skips
`ver_non_input_consensus` or `check_tx_semantic`, moves the domain check after
a state change, runs `verRctCLSAGSimple` alone on untrusted input, or stores
or compares key images in any other form (after `mul8`, or via a decoder that
accepts non-canonical bytes).

### 1.2 The same class outside consensus: reserve proofs (fixed on master)

zkao (automated scan, 2026, rated Critical by the reporter; not consensus):
a reserve proof could carry `I + T` with `T` of order 2, verifying whenever
the challenge was even, and `wallet2::check_reserve_proof` asked the daemon
about the shifted bytes, reporting a spent output as unspent. On master
`wallet2::check_reserve_proof` rejects duplicates, `identity` and anything
failing `rct::isInMainSubgroup`, and `check_ring_signature` rejects identity
and torsioned key images. Other wallet entry points check subgroup membership
too (multisig partial key images and `L`/`R`, received output keys and masks).

**A PR is risky here if it** adds a caller of `check_ring_signature`,
`check_tx_proof` or `check_signature` on an external key image or point
without identity and subgroup checks on what that function does not check
(`check_tx_proof` and `check_signature` check none).

### 1.3 Torsion in tags versus torsion in values

In a **tag** (key image, CLSAG `D`, multisig partial image) torsion breaks
uniqueness and must be rejected. In a **value commitment** (`outPk.mask`,
range-proof points) it carries no amount: provers store points times
`INV_EIGHT` and verifiers multiply by 8 (`rct::scalarmult8`). ZenGo X raised
the missing identity check after `x8` and the transcript being hashed before
`x8`; MRL's position, accepted by the auditors, is that Fiat-Shamir blocks
both. zkao (2026, two reports, each rated High in the report) found monero-oxide's
BP, BP+ (`ZK-n3zsixe1`) and Borromean verifiers accept `C + T` with a proof
for `C` (for Borromean, an even challenge erases an order-2 `T`). The reports
demonstrate no inflation, note that consensus compatibility constrains the
fix, and suggest a strict API for non-consensus callers. monerod's
`verifyBorromean` also checks no subgroup.

Before rating a torsion report, ask: tag or value? Does the reference
implementation accept the same bytes (then rejecting them splits the chain)?
Is the property guarded elsewhere? Is there a real caller?

### 1.4 What `Hp` must be

Linkability needs `log_G Hp(P)` unknown; the whitepaper's anonymity proof
models `Hp` as a random oracle. MRL-0005's footnote writes
`Hp(P) = Keccak(P)*G`, which has a known discrete log and would link `I` to
its ring member; the code does not do this. **A PR is risky here if it**
derives a key-image base with a known discrete log or from anything but
`biased_hash_to_ec` / `rct::hash_to_p3` for legacy outputs.

---

## 2. Ring signatures: CryptoNote, MLSAG, CLSAG

### 2.1 CryptoNote ring signature and MLSAG

MRL-0003 maps the CryptoNote ring signature onto the Fujisaki-Suzuki traceable
ring signature: `L = r*G + c*P`, `R = r*Hp(P) + c*I`, and the `c_i` sum to
`Hs(prefix || L || R)`. `crypto_ops::generate_ring_signature` and
`check_ring_signature` follow it, with `sc_check` on every `c` and `r`.
Surae Noether's annotations flag that the real key must not sit at a
predictable ring position and that what is signed must be pinned down.

MRL-0005 defines MLSAG over a key matrix; the commitment row needs no key
image (its Remark 4.2), which is the `dsRows` split in `MLSAG_Gen` /
`MLSAG_Ver`. `MLSAG_Ver` checks the matrix shape, `II.size() == dsRows`,
`sc_check` on every `ss[i][j]` and `cc`, `II[i] != identity`, and a non-zero
round hash.

### 2.2 CLSAG: what the proofs need from the code

The CLSAG paper (Goodell, Noether, Blue, 2019) proves its properties,
including non-slanderability against adversarial keys, in a prime-order group
with aggregation coefficients hashed over the whole statement. In `CLSAG_Gen`
and `verRctCLSAGSimple` (`src/ringct/rctSigs.cpp`):

- `mu_P` and `mu_C` hash `[tag, P[0..n-1], C_nonzero[0..n-1], I, sig.D, C_offset]`;
  the round hash covers `[tag, P, C_nonzero, C_offset, message, L, R]`. `I` and
  `D` reach the round only through `mu`. The tags `HASH_KEY_CLSAG_AGG_0`,
  `HASH_KEY_CLSAG_AGG_1` and `HASH_KEY_CLSAG_ROUND` are in
  `src/cryptonote_config.h`; the paper used one hash for both roles.
- `D` is stored times `INV_EIGHT`; the verifier rejects `scalarmult8(sig.D)`
  equal to the identity. `mu` hashes the stored `sig.D`. Only `I` goes to the
  spent set.
- `I` in `rct::clsag` is not serialized; `Blockchain::expand_transaction_2`
  rebuilds it from `vin` and `expand_tx_and_ver_rct_non_sem` checks they match.
- The verifier checks sizes, `sc_check` on every `s[i]` and `c1`,
  `I != identity`, and rejects a zero round challenge.

`multisig::signing::CLSAG_context_t` (`src/multisig/multisig_clsag_context.cpp`)
reimplements the same hashes and must match byte for byte.

### 2.3 Aumasson-Vennard CLSAG review (2020)

Paper plus code as of May 2020, software device only. **3.4.1 key struct
misuse prevention, Low:** `rct::key` is a bare struct, so default copies of
secrets escape `memwipe`. Not adopted; secret copies must be wiped by hand
(`CLSAG_Gen` wipes the nonce, `proveRctCLSAGSimple` the zero-commitment key).
**3.4.2 code duplication, Informational:** the two `scalarmultKey` overloads,
unchanged. The paper review found no flaw in the main results and called the
linkable-anonymity proof "a bit hand-waved". Multisig CLSAG and hardware
devices were out of scope.

### 2.4 CLSAG security proof revisions (2024)

Reviewing Zano's d/v-CLSAG (sowle, v1.0, revised as v1.4), Cypher Stack found
two proof problems that also apply to CLSAG; Monero announced them with no
severity and no implementation impact. **A non-zero precondition** inherited
from LSAG: if the aggregated terms are zero, `c_{i+1}` stops depending on
`c_i`; in code this rests on `I != identity`, `D_8 != identity` and the
per-round `c_new != 0` check. **The reduction did not fit the one-more-DL
game**; it was restated against plain DL.

**A PR is risky here if it:**

- changes the contents, order or count of `mu_P_to_hash`, `mu_C_to_hash` or
  `c_to_hash` without changing `CLSAG_Gen`, `verRctCLSAGSimple` and
  `CLSAG_context_t` the same way (dropping a ring member, `I`, `sig.D`,
  `C_offset` or the message; hashing `C` for `C_nonzero` or `D_8` for `D`);
- edits, reuses or merges the CLSAG domain strings or their padding, or
  removes `sc_check` on `s` or `c1`, the `I`/`D_8` identity checks or the
  zero-challenge check;
- changes the `D/8` convention on any signing side (`rctSigs.cpp`,
  `multisig_tx_builder_ringct.cpp`, `src/device/`) or the verifier;
- uses `D` for linking, takes `I` from anything but `vin`, or leaves
  secrets unwiped;
- changes `get_pre_mlsag_hash`, the single definition of what a RingCT
  signature covers.

### 2.5 Designs not adopted, and why they still matter

- **Arcturus (Noether, 2020)** rested soundness on a new "dual-target discrete
  log" assumption. koe (2021) broke it: the two conditions are two linear
  equations in `n` unknowns, so fix `x_2..x_{n-1}` and solve for `x_0, x_1`.
  The proof does not hold as written; the author planned to update or
  withdraw the preprint.
- **Triptych (2021)** needs only DL and the random oracle; it builds on
  Groth-Kohlweiss one-out-of-many proofs (2014), and its parallel variant
  binds components with weights hashed over every component.
- **DLSAG (MRL-0008):** whether an output is single or dual must come from
  chain data, never the signer, or the signer gets a second key image.
- **MRL-0010 (cross-group DLEQ, 2018)** is a note without a proof; as printed
  its challenges hash no statement or domain tag and the bit length is never
  bounded. Atomic swaps and Grease rely on this primitive (8.3).
- **BulletCT (Wang et al., 2025)** reports that the ZGSX23 RingCT scheme's
  tags had no proof tying them to the ring keys, allowing double spends.

**A PR is risky here if it** replaces per-input checks with a random linear
combination whose weights are not hashed over every component, rests
soundness on a new or unreduced assumption, lets the signer choose a tag's
base point or classification, or adds a tag without a proof binding it to the
spent key.

---

## 3. Bulletproofs, Bulletproofs+ and the multi-exponentiation code

Two range-proof verifiers are live: `bulletproof_VERIFY`
(`src/ringct/bulletproofs.cc`, for `RCTTypeBulletproof`, `Bulletproof2` and
`CLSAG`, still run for historical transactions) and `bulletproof_plus_VERIFY`
(`src/ringct/bulletproofs_plus.cc`). Both feed one `multiexp`
(`src/ringct/multiexp.cc`).

### 3.1 What the papers require

From Bulletproofs (Bünz et al., revised ePrint) and BP+ (Chung et al., ePrint
2020/735):

- **Generators** with no known DL relation (a DL break is undetectable
  inflation), in a prime-order group; no paper treats the cofactor.
- **Fiat-Shamir** hashes the whole statement, every `V` included, before the
  first challenge, and chains each challenge to the transcript. The IEEE 2018
  text gives `y = H(A,S), z = H(y), x = H(T1,T2)` without `V`: the Frozen
  Heart form (7.1). The revised ePrint says to hash the statement.
- **Challenges** are non-zero; extractors need `x_i != ±x_j`, which
  Bulletproofs states and BP+ drops.
- **Aggregation**: powers of two, padded slots commit to zero; BP+ weights
  block `j` by `z^{2j}` from `j = 1`, and its soundness proof depends on those
  monomials.
- **Batching** uses independent, unpredictable, non-zero weights; zero
  knowledge needs fresh prover randomness per proof.

The BP+ IEEE Access version (2022) has no proof appendices and two copyable
typos (a scalar `g` in `Â`; `r'·s'` without `y`). Segev (2025) showed R1CS
Bulletproofs are complete for one relation and sound only for a weaker one;
this does not affect Monero's range proofs.

### 3.2 Kudelski Security, Bulletproofs (2018)

`src/ringct` on `bp-multi-aggregation-pippenger` plus the Java prototype.
Three Low findings, fixed before deployment, and seven observations.

- **BP-F-001 unsafe use of environment variables, Low.** `multiexp` read
  the Straus step from `getenv`. No `getenv` remains in `src/ringct`.
- **BP-F-002 lack of input validation in prover, Low.** Both provers check
  `sv` and `gamma` with `is_reduced`; both verifiers check their scalars
  (`taux`, `mu`, `a`, `b`, `t`; `r1`, `s1`, `d1`).
- **BP-F-003 integer overflow in L size computation, Low.** `1 << (L.size()-6)`
  with no bound let a huge `L` skip the layout check. Now
  `n_bulletproof_amounts_base` / `n_bulletproof_max_amounts_base`
  (`src/ringct/rctTypes.cpp`) bound `L`; `serialize_rctsig_prunable`
  (`rctTypes.h`) rejects proofs too small for the output count at parse time;
  `is_canonical_bulletproof_layout` / `is_canonical_bulletproof_plus_layout`
  (`tx_verification_utils.cpp`) require one proof of 1 to 16 amounts. The BP
  branch of `expand_transaction_1` still computes a raw `1 << (L.size()-6)`,
  safe only because parsing bounds `L` first.
- Observations, not fixed by design, include no test vectors (BP-O-002) and
  amount-range timing leaks in conversion functions (BP-O-005).

### 3.3 Quarkslab, Bulletproofs (2018)

The `bp-multi-aggregation` branch, 35 days. The report gives no fix status;
master status below is from the code.

- **5.1 zero value challenges, High.** Both verifiers reject zero challenges
  and both provers retry at `try_again`. BP's batch `invert(keyV)` has no zero
  guard outside `DEBUG_BP`, so these checks are all that stops one zero from
  zeroing every inverse.
- **5.2 dependent generators in the Java prototype**, severity undefined.
- **5.3 overflow in the double scalar multiplication, Critical.** `slide()`
  in `crypto-ops.c` assumes `a[31] <= 127`; an unreduced scalar gives a wrong
  result. `slide()` is unchanged and `rct::addKeys2` does not reduce, but the
  BP verifiers no longer call it. `ge_scalarmult` and `ge_scalarmult_base`
  share the precondition.
- **5.4 identity output in Bos-Coster, Critical.** Fixed in
  `bos_coster_heap_conv_robust`, which production no longer calls.
- **5.5 silently discarded element in Pippenger, Critical.** The top bit was
  lost when the largest scalar was a power of two. `pippenger_p3` and
  `straus_p3` now loop while `!(maxscalar < pow2(...))`.
- **5.6 invalid Verify input parameters, High.** Scalars are `is_reduced`,
  points decode inside `rct::scalarmult8`, sizes are capped; no subgroup
  check on proof points (1.3).
- **5.7 key compromise in Schnorr signature, High.** `generate_signature`
  retries on zero `c` or `r`; `check_signature` rejects zero `c` and an
  identity commitment.
- **5.8 deserialization size checks, Medium; 5.9 element counts,
  Informational; 5.10 unchecked `boost::get<txout_to_key>`, Medium.** Counts
  are now checked in `serialize_rctsig_prunable` and `do_serialize_container`;
  `expand_transaction_1` rejects unexpected output types.
- **Weakness 6.2.1: an empty proof vector verifies true**, still;
  `verRctSemanticsSimple` guards with `!bp_proofs.empty() &&` and
  `!bpp_proofs.empty() &&`. 6.2.3: `get_exponent` now rejects identity
  generators.

No false proof or amount leak was found. Not covered: exploitability of 5.3
to 5.5, small-subgroup attacks, prover side channels, the paper's soundness.

### 3.4 ZenGo X, Bulletproofs+ (2021)

`bulletproofs_plus.{h,cc}` and the paper, 40 days. The text says no critical
issues and no practically exploitable high ones; the summary table marks 5.1
Critical.

- **5.1 no point-at-infinity check after `x8`**, and **6.1 transcript hashed
  before `x8`, Medium.** MRL and the auditors agreed Fiat-Shamir blocks the
  torsion attack, and warned that hashing after `x8` alone would allow false
  proofs. No change.
- **5.2 no check that challenge `e` is 0, High.** Fixed.
- **6.2, 6.3, Low:** `n = 0` passed `sum_of_even_powers`,
  `sum_of_scalar_powers` and `vector_of_scalar_powers`. Fixed.
- **6.5 `V` is pre-scaled by `INV_EIGHT`, Low.** `V` is not serialized;
  `expand_transaction_1` rebuilds it from `outPk[i].mask` times `INV_EIGHT`.
  The range proof covers the torsion-free part of `outPk`; the balance check
  uses raw `outPk`.
- Context binding was not analysed. BP+ starts from `initial_transcript`
  (`HASH_KEY_BULLETPROOF_PLUS_TRANSCRIPT`); BP has no tag. Both are bound to
  the transaction through `get_pre_mlsag_hash`.

### 3.5 CSIRO, Bulletproofs+ aggregate range proof review (2026)

Nan Wang and Dongxi Liu reviewed the BP+ paper's proofs only, with no IDs or
severities. In their words: inconsistent extracted responses in the range
argument, "significant" (openings of each `V_j` are weighted by
`z^{2j} y^{mn+1}`; they supply a repaired extraction, and say this "does not
by itself imply" unsoundness); inconsistent responses in the final WIP round,
"comparatively minor"; extraction of `gamma` omitted, "relatively minor".
Conclusion: completeness, SHVZK and, once corrected, witness-extended
emulation; no attack. On master `z = hash_to_scalar(y)`, so a proof that
assumes independent `(y, z)` does not describe the deployed transcript.

### 3.6 Range proofs not on master

Bulletproofs++ (Eagen et al., 2023): Cypher Stack's 2024 review (no formal
severities) found the round-extractor Lemma 5 invalid as written, Lemma 6
misstated and gaps in the Theorem 1 and 2 proofs, with corrections. SuperRange
(Wang and Liu, 2026) puts the BP++ reciprocal idea inside the Bulletproofs
inner-product framework; Flashproofs, SwiftRange and FlashSwift are earlier
transparent designs by the same group; Cuproof (2022) needs a trusted RSA
setup. None has a Monero implementation or audit.

### 3.7 The code that carries all this

- **Transcripts.** BP: `hash_to_scalar(V)` seeds `hash_cache`, then
  `hash_cache_mash` gives `y` from `(A,S)`, `z = hash_to_scalar(y)`, `x` from
  `(z,T1,T2)`, `x_ip` from `(x,taux,mu,t)`, `w_i` from `(L_i,R_i)`. BP+:
  `transcript_update` from `initial_transcript` over `hash_to_scalar(V)`, `A`,
  each `(L_j,R_j)`, then `(A1,B)`. Raw bytes are hashed, before `x8`.
- **Generators.** `get_exponent(rct::H, idx)` hashes `H`, the tag and
  `varint(idx)` through `hash_to_p3`; `Hi` even, `Gi` odd, identity rejected.
- **Batch weights.** BP: `weight_y`, `weight_z` from `rct::skGen()`, no zero
  loop. BP+: one weight per proof, looped until non-zero.
- **Sizes.** `maxN = 64`, `maxM` from `BULLETPROOF_MAX_OUTPUTS` /
  `BULLETPROOF_PLUS_MAX_OUTPUTS` (16), `L.size() == 6+logM`, `max_length < 32`.
- **multiexp.** `straus` and `pippenger` with cached generator tables
  (`STRAUS_SIZE_LIMIT`, `PIPPENGER_SIZE_LIMIT`, `get_pippenger_c`); zero
  scalars are skipped, and `straus_p3` also skips identity points.
- The two files define their own static `multiexp`, `is_reduced`,
  `get_exponent`, `invert`, `Hi_p3`, `Gi_p3`; check which file a hunk is in.

**A PR is risky here if it:**

- adds, drops or reorders a transcript input, changes a tag, derives `z` from
  anything but `y`, or hashes `x8` or reduced forms instead of raw bytes;
- removes an `is_reduced`, zero-challenge, `try_again` or `scalarmult8`;
- changes the `INV_EIGHT` pre-scaling or how `expand_transaction_1` rebuilds
  `V`, or treats `V` as `outPk` outside the range proof;
- relaxes `L.size() == 6+logM`, `V.size() <= maxM`, the `n_bulletproof_*`
  bounds, the parse-time count check or the one-proof layout, or adds an
  unbounded `1 << L.size()`;
- calls a range-proof verifier on a possibly empty vector, or makes a batch
  weight deterministic, proof-derived, shared or possibly zero;
- passes an unreduced or prover-controlled scalar to `addKeys2`,
  `ge_double_scalarmult_base_vartime`, `ge_scalarmult` or `ge_scalarmult_base`;
- touches the Straus or Pippenger loops, `pow2` bounds, cache sizes or the
  algorithm switch, or revives `bos_coster_heap_conv_robust`, without
  differential tests over a power-of-two top scalar, one non-zero term, zero
  scalars, identity points and inputs larger than the cache;
- changes generator derivation or `rct::H`, reuses prover randomness, or
  claims a constant-time prover (no audit checked; it branches on amount bits);
- changes `maxN` or the output cap without re-checking that `M*2^N` stays far
  below `l`;
- adopts a new range proof without a reviewed proof of the exact variant,
  test vectors and an implementation audit.

---

## 4. Amounts, RingCT balance and addresses

### 4.1 What MRL-0005 established

RingCT (Shen Noether et al., 2016) hides amounts in Pedersen commitments
`C = x*G + a*H` and proves `sum(C_in) - sum(C_out) - fee*H` commits to zero.
Every output needs a range proof: without one, `-1 mod l` mints coins. `H`
must have an unknown discrete log to `G`; the paper argues this only
heuristically. Its ASNL range proof was never deployed (Borromean, then BP,
then BP+), and the single MLSAG became per-input pseudo-outputs with a public
sum check.

### 4.2 Where it lives

- `verRctSemanticsSimple` checks sizes, then
  `sum(pseudoOuts) == sum(outPk.mask) + scalarmultH(d2h(txnFee))`, then range
  proofs, before any signature work.
- `rct::H` (`rctTypes.h`, `ge_p3_H` in `crypto-ops-data.c`) is
  `8 * decompress(Keccak(G))`. `zeroCommitVartime(amount)` is `G + amount*H`
  (mask 1) for pre-RingCT and coinbase amounts.
- `ecdhEncode` / `ecdhDecode`: v2 XORs 8 amount bytes with
  `genAmountEncodingFactor` and derives the mask with `genCommitmentMask`.
  `decodeRct` re-checks the commitment.
- `Blockchain::check_tx_inputs` gates RCT types by hard fork and enforces the
  minimum ring size (MRL-0001 and MRL-0004 showed how low mixin enables
  chain-reaction tracing).

### 4.3 Subaddresses (MRL-0006)

Noether and Goodell (2017): `D_i = B + Hs(a, i)*G`, `C_i = a*D_i`, tx key
`R = s*D_i`, recipient lookup `D' = P - Hs(a*R)*G` in a table. On master
`get_subaddress_secret_key` (`src/device/device_default.cpp`) hashes
`HASH_KEY_SUBADDRESS` (`"SubAddr"` with its trailing NUL), `a`, and the
little-endian indices; `(0,0)` returns the main address.
`derive_subaddress_public_key` (`crypto.cpp`) and the `src/crypto/wallet/`
path must agree. `construct_tx_with_tx_key` uses `R = s*D` only for exactly
one subaddress destination and no standard ones, otherwise per-output
additional keys. The paper hashes `s*C_i`; the code hashes
`8*(shared point)` with the output index and a domain tag.

### 4.4 Wallet-side lessons and address proposals

- **Duplicate tx public keys (HackerOne, 2018, rated critical by the
  reporters).** One output was counted once per duplicated key; the first fix
  was bypassed with additional keys. Scanning now goes through
  `wallet2::check_acc_out_precomp_once`. Fix the invariant, not the instance.
- **Malformed `ecdhInfo` (HackerOne, 2019).** Consensus does not validate
  fields only the recipient reads; validate before mutating wallet state.
- **Guaranteed and Featured Addresses (kayabaNerve, 2022)**, a wallet-only
  proposal not on master: the Guaranteed feature hashes per-transaction
  uniqueness (input key images, or height for coinbase) into the shared
  secret to remove the burning bug. Featured Addresses replaced the
  deprecated format with a feature-flag varint and new network bytes; the
  author notes no formal analysis of the new shared key.

**A PR is risky here if it** changes the balance equation or its inputs,
skips `verRctSemanticsSimple` for any accepted type, lets an output go without
a range proof, loosens the size consistency checks, touches `rct::H`,
`ge_p3_H` or `zeroCommitVartime`'s mask, alters `ecdhEncode`/`ecdhDecode` or
the mask and amount factors, removes `decodeRct`'s re-check, changes
subaddress derivation, the `(0,0)` case or the tx-key rule, or relaxes
hard-fork type gating or the ring size.

---

## 5. Hashing, hash-to-point, Merkle tree and Schnorr proofs

### 5.1 The hash-to-point map

`ge_fromfe_frombytes_vartime` (`src/crypto/crypto-ops.c`) is in substance
Elligator 2 with `u = 2` on Curve25519, evaluated straight into Edwards
coordinates. Shen Noether's MRL note checks that the output is on the curve;
it does not appear to have included an analysis of distribution or timing.
Two of its justifications may not match the code (it calls the input load
ref10's `fe_frombytes`, but the map does not mask bit 255; and it says `-1` is
a non-residue, while `p = 1 mod 4` makes it a square, hence `fe_sqrtm1`).

The literature: one application of such a map is **not** indifferentiable
from a random oracle or uniform (Elligator 2 is 2-to-1 onto about half the
curve, and image membership is testable: Bernstein et al. 2013, Brier et al.
2010). `f(h1) + f(h2)` with independent hashes **is** indifferentiable, also
after the cofactor multiply (Farashahi et al. 2010, Brier et al. 2010).
Reducing a 256-bit hash mod `p` is fine (Kim and Tibouchi 2015). Decodable
encodings (Fouque, Joux, Tibouchi 2013) are not used. Secret inputs need
constant-time evaluation.

Monero's uses:

- **Biased:** `biased_hash_to_ec` (static, `crypto.cpp`) and `rct::hash_to_p3`
  (`rctOps.cpp`), both `8 * f(Keccak(input))`, for legacy key images, the ring
  signatures and the BP/BP+ generators. They must stay equivalent.
- **Unbiased:** `crypto_ops::unbiased_hash_to_ec`,
  `8*f(h[0..32]) + 8*f(h[32..64])` over a 64-byte `blake2b_monero` digest;
  `derive_key_image_generator` chooses.

The biased map is acceptable because inputs are public and the proofs need
only an unknown discrete log.

**A PR is risky here if it** touches `ge_fromfe_frombytes_vartime`,
`fe_divpowm1` or its constants, or "fixes" the unmasked 256-bit load (every
key image and generator changes); moves or removes a `ge_mul8`; uses the
biased map where a uniform point is assumed; collapses the unbiased map to one
encoding; feeds secret data to a `_vartime` map; or relies on its `assert`s.

### 5.2 The block Merkle tree (MRL-0002)

The original `tree-hash.c` rounded the leaf count to a power of two with a
shift loop that ran too few times on 64-bit. For 514 transactions it left the
last two hashes out of the root, so two different blocks had the same id. It
was exploited at block 202612 on 2014-09-04 and split the network; MRL-0002
(Macheta, Noether, Noether, Smooth) analysed it.

`tree_hash_cnt` (`src/crypto/tree-hash.c`) now doubles a power until it
reaches the count, with `assert`s on `3 <= count <= 2^28` (gone under
`NDEBUG`). `get_tx_tree_hash` hashes the miner transaction first, and
`get_block_hashing_blob` appends `varint(tx_hashes.size() + 1)`, binding the
count into the block id. `calculate_block_hash` and
`get_block_longhash_202612` (`cryptonote_format_utils.cpp`) hard-code the
block 202612 exception, with a guard against reusing its id.

**A PR is risky here if it** changes `tree_hash_cnt` or `tree_hash`, the leaf
order, the appended count, or the 202612 exception, or relies on those
`assert`s.

### 5.3 Domain separation

Tags live in `src/cryptonote_config.h`: `HASH_KEY_BULLETPROOF_EXPONENT`,
`HASH_KEY_BULLETPROOF_PLUS_EXPONENT`, `HASH_KEY_BULLETPROOF_PLUS_TRANSCRIPT`,
the three `HASH_KEY_CLSAG_*` tags, `HASH_KEY_CLSAG_ROUND_MULTISIG`,
`HASH_KEY_TXPROOF_V2`, `HASH_KEY_SUBADDRESS`, `HASH_KEY_MULTISIG`,
`HASH_KEY_MULTISIG_KEY_AGGREGATION` and others. The original CryptoNote hashes
(`derivation_to_scalar`, the ring signature, `generate_signature`) and the
original Bulletproof transcript have none. Look for a new proof or hash that
reuses a tag or omits one.

### 5.4 Schnorr signatures and transaction proofs

`generate_signature` / `check_signature` carry the Quarkslab 5.7 fix.
`generate_tx_proof` / `check_tx_proof` prove `log_{G or B}(R) = log_A(D)`. The
v1 challenge `Hs(msg || D || X || Y)` binds neither `R`, `A` nor `B`; v2 adds
`HASH_KEY_TXPROOF_V2`, `R`, `A`, `B`. The wallet still accepts v1 proofs.
`check_tx_proof` checks only that its points decode, with no identity or
subgroup check; wallet callers pass torsion-cleared keys
(`crypto::pubkey_clear_torsion`).

**A PR is risky here if it** extends v1 acceptance, adds a DLEQ-style proof
without statement and context in the challenge, or uses `check_tx_proof` on a
uniqueness-bearing point without clearing or rejecting torsion.

---

## 6. RandomX and proof of work

Four 2019 audits of `tevador/RandomX` (the `external/randomx` submodule);
Monero's side is `src/crypto/rx-slow-hash.c`.

- **Trail of Bits:** TOB-ARW-001 single AES rounds in the program generator,
  Low (moved to four rounds); TOB-ARW-002 insufficient testing of VM
  correctness, Low (any spec/code gap is a fork); TOB-ARW-003 brittle
  parameters, Informational.
- **Kudelski Security:** thirteen Observations, nothing exploitable:
  `AesHash1R` is not a secure hash; `AesGenerator4R` behaved like ECB (later
  given distinct column keys); NULL checks, a divide by zero and an unchecked
  BLAKE2 result became `assert`s that compile out in release builds.
- **X41 D-Sec:** RNDX-PT-19-01 to 19-04, Medium (JIT code size, jump offset,
  32-bit dataset size, emulation crash at non-default sizes), fixed; eleven
  "None" items, including writable-executable JIT pages (19-107, answered by
  opt-in `RANDOMX_FLAG_SECURE`).
- **Quarkslab:** RNDX-M1 Argon2 salt length, M2 spec AND versus code modulus
  (spec fixed), M3 key size unchecked (Monero passes 32 bytes), all Medium;
  three Low documentation items. It recommended interpreter-versus-JIT
  equivalence tests and warned the AES components are safe only inside
  RandomX.

**Must hold.** Every backend gives the same bytes (interpreter and JIT,
hardware and soft AES, light and full memory, secure and non-secure JIT, every
architecture); `MONERO_RANDOMX_UMASK` makes every combination reachable, and
Monero has no RandomX known-answer test of its own. `rx_seedheight` uses
`SEEDHASH_EPOCH_BLOCKS` (2048, equal to `BLOCKS_SYNCHRONIZING_MAX_COUNT`) and
`SEEDHASH_EPOCH_LAG` (64), both lowerable from the environment on any network.
`RANDOMX_FLAG_SECURE` is set for JIT VMs only when `miner_thread` is zero
(`rx_init_full_vm`, `rx_init_light_vm`). `rx_set_main_seedhash_thread` reseeds
under the dataset and cache locks; `rx_slow_hash` falls back to a light VM
when it cannot take the read lock and rebuilds the one secondary cache (200 to
500 ms of Argon2) under a write lock, which blocks from other epochs can force.

**A PR is risky here if it** bumps the `external/randomx` pin without proof of
byte-identical hashes across backends and modes; changes `rx_seedheight`, the
epoch constants or their environment handling, or seed choice for alternative
chains; reorders the locks or the light-VM fallback; drops
`RANDOMX_FLAG_SECURE` for verification; relies on RandomX `assert`s; reuses a
RandomX AES component as a hash; or lets a peer force secondary-cache reseeds
before cheaper checks run.

---

## 7. Lessons from other proof systems

### 7.1 Frozen Heart: the statement goes in the first challenge

Trail of Bits (Jim Miller, 2022) disclosed weak Fiat-Shamir bugs in Girault,
Bulletproofs and PlonK implementations, rated critical. Their Bulletproofs
post notes the paper's transcript does not appear to have included `V`, so an
implementation following it lets a prover fix the challenges, then solve for
a `V` committing to an out-of-range value. Monero is not affected: both
transcripts absorb `hash_to_scalar(V)` before `A`, and every later challenge
is chained to the running state.

**A PR is risky here if it** moves or drops the `V` absorption, hashes a
different `V` from the one the equations use, adds a variable parameter (bit
width, generators) without absorbing it, or computes a round challenge from
that round's `L`/`R` alone.

### 7.2 The Fiat-Shamir bug taxonomy

zkSecurity (Vu and Wong, 2026) sorts implementation bugs into seven classes,
each a question for a Monero transcript. **Weak:** is the whole statement
absorbed (v1 `check_tx_proof` omits `R`, `A`, `B`)? **Circuit substitution:**
is the proof's identity (type, bit width, generators) absorbed?
**Ambiguous:** does the encoding keep the statement (Solana absorbed only a
sum of bit lengths)? **Lossy:** one encoding per value (canonical points,
`sc_check`)? **Silent:** domain separation (BP+ and CLSAG have it; original
BP, MLSAG and the CryptoNote ring signature do not)? **Phantom:** are
prover-supplied challenge-like values absorbed (the multisig factor `b` in
`CLSAG_context_t` absorbs the ring, `C_offset`, message, nonces, `I`, `D`, fake
responses, real index and counts)? **Batched:** are weights drawn after
everything they weight (FastCrypto took them from the proof challenge, which
does not appear to have included the responses; Monero draws fresh
`rct::skGen()` weights)?

Attema, Fehr and Klooß (2022): Fiat-Shamir on a multi-round special-sound
protocol loses only a factor linear in hash queries, but parallel repetition
of small-challenge protocols can lose far more. Monero's challenges are full
scalars mod `l`.

**A PR is risky here if it** truncates challenges, repeats a small-challenge
protocol in parallel, reuses a domain tag across challenge schedules, or
derives batch weights from data that omits any response.

### 7.3 Zerocoin: canonical tags, bound messages, unpredictable tags

Ruffing, Thyagarajan, Ronge and Schröder (2018) reported one scheme flaw and
two libzerocoin coding issues they called critical:

- **Non-canonical serials (coding).** Checked only mod `N`, so one serial in
  two representations spent twice: the 2017 key-image bug in another group.
- **The signature of knowledge did not bind the transaction (coding)**, so
  spends could be re-targeted. Monero's ring signatures sign
  `get_pre_mlsag_hash`.
- **Denial of spending (scheme).** Serials were chosen, not derived from a
  secret, so a watcher could burn a pending coin; the original model (Miers et
  al. 2013) defined only anonymity and balance. The paper notes Monero is not
  vulnerable because the key image is `x*Hp(P)`.

**A PR is risky here if it** accepts non-canonical bytes, adds a tag without
a canonical-form check on the verification path, adds a validity-relevant
field outside the prefix hash and `get_pre_mlsag_hash`, lets the device path
(`mlsag_prehash`, `clsag_hash`) hash differently from software, or lets anyone
but the owner predict a valid key image.

### 7.4 Halo2 query collision

zkSecurity (Suneal Gong, 2025): Halo2's multipoint opening kept a
`(commitment, point) -> value` map, so two queries at one point collided and
one evaluation went unchecked. `multiexp` skips only zero scalars and identity
points. **A PR is risky here if it** adds deduplication, merging or caching in
a verifier where a colliding key overwrites or skips data instead of
rejecting it.

### 7.5 Other literature, and why proofs are not code

Not on master and with no Monero code to check: Zerocash, Zether, ZeroMT,
CRCT, aggregate and threshold ring signatures, post-quantum ring signatures
and stealth addresses, and a compressed Σ-protocol inner-product argument. A
PR citing one needs the bar in 3.6.

The CryptoNote linkability proof assumed a prime-order group the code did not
enforce; the Arcturus assumption was broken; CLSAG, BP+, BP++ and a DKG (8.2)
had proofs corrected. Treat neither "proven secure" as a guarantee for
deployed code nor a proof gap as a vulnerability without an attack.

---

## 8. Multisig, threshold signing and off-chain protocols

### 8.1 Monero multisig and MuSig

MuSig (Maxwell, Poelstra, Seurin, Wuille, 2018) defeats rogue keys with
aggregation coefficients hashed over the whole key list; the revised paper
retracts its 2-round variant. On master `compute_multisig_aggregation_coefficient`
(`multisig_account_kex_impl.cpp`) hashes the key, the sorted key list and
`HASH_KEY_MULTISIG_KEY_AGGREGATION`; its comment requires canonical,
prime-order keys and says it does not test them. `CLSAG_context_t` combines
`kAlphaComponents = 2` nonces per signer with the MuSig2-style factor `b`
(7.2). MRL-0009 (Goodell, Noether, 2018) builds threshold LSAG ("thring
signatures") the same way; not on master. Half-aggregation (Chalkias et al.,
2021) hashes every `(R_i, A_i, m_i)` into each weight and flags batch
verification that omits `S` as malleable.

**A PR is risky here if it** removes the sorted list or tag from the
aggregation coefficient, feeds it unchecked keys, drops to one nonce, removes
anything from `b_params`, or reuses a nonce across signing attempts.

### 8.2 FROST, DKG and threshold ECDSA

These bear on Monero through external protocols (Grease, Serai) and any
future FROST-based multisig.

- **FROST (RFC 9591, 2024)** binds each nonce to the message and full
  commitment list; it is not robust, and nonce reuse leaks the key. ROAST
  (2022) adds robustness, Arctic (2025) statelessness under an honest
  majority, Axolotl (2026 preview) asynchrony.
- **Adaptive security.** Rodríguez García and Tessaro (2026) forge
  adaptively against FROST-like schemes at large `n` with canonical
  identifiers (205-of-5020 on Curve25519); Goldberg, Komlo and Tessaro (2026)
  show security still reduces to AOMDL for `n <= 131` at 128 bits.
- **Serai audit (Cypher Stack, 2023):** 48 unrated recommendations, mostly
  fixed, including tag-and-input concatenation without the tag length,
  random group elements that could be the identity, and no guard against
  evaluating a Shamir polynomial at zero.
- **eVRF DKGs** (Boneh et al. 2024; Golden 2025): HashCloak's proofs for
  Serai's DKG record a proof error found by Kondi, since corrected, and note
  the one-round variant is biased.
- **Threshold ECDSA** (Gennaro et al. 2016; Trout 2025; Trout++ 2026) matters
  only on the Bitcoin side of swaps.

### 8.3 Atomic swaps and payment channels

- **BTC-XMR swaps** (Gugger 2020; Hoenisch, Soriano del Pino 2021) split the
  Monero spend key and sell one share with an ECDSA adaptor signature, bound
  across curves by MRL-0010-style DLEQ proofs. Gugger gives no proof of the
  composed protocol and warns of refund races if timelocks do not exceed
  confirmation depths. Binks (2022) does ETH-XMR with a two-timelock
  contract. Kopyciok et al. (2025) show non-disputed Haveno trades leave a
  linkable on-chain pattern (two locks and a spend within a day, elevated
  fee).
- **Channels.** PayMo (2022) uses verifiable timed linkable ring signatures,
  proven in the ROM against Monero's 2022 scheme; Sleepy Channels (2022)
  avoids watchtowers, but its Monero variant has no formal proof. Grease
  (2026) uses 2-of-2 FROST, adaptor offsets advanced by a SNARK-proven one-way
  function and a cross-group DLEQ; an escrow colluding with one party can
  drain a channel. CjS77's arbiter (2026) swaps escrow custody for
  threshold-BLS attestation. Both note cross-group equality proofs have a
  poor soundness record.

**A PR is risky here if it** adds or changes a cross-group DLEQ without a bit
length bound and a challenge over statement and tag, sets swap
timelocks that do not exceed confirmation depths, or changes multisig share
derivation without the rules in 8.1.

---

## 9. Checklist for a crypto diff (SPEC angle)

A "no" or "can't tell" is a question for the author or a candidate finding.

1. **Transcript.** Is every public value the verifier uses hashed before the
   challenge that depends on it, in the same order in prover and verifier,
   under a unique domain tag, with variable-length fields framed?
2. **Second copies.** Does the change reach `CLSAG_Gen`, `verRctCLSAGSimple`
   and `CLSAG_context_t`; `biased_hash_to_ec` and `rct::hash_to_p3`;
   `bulletproofs.cc` and `bulletproofs_plus.cc`; software and device paths;
   `crypto-ops.c` and `src/crypto/wallet/`?
3. **Scalars.** Every wire scalar `sc_check`ed or `is_reduced`, every
   `slide()` input reduced, zero challenges and weights rejected?
4. **Points.** Canonical decoding? A tag: identity and subgroup checked on
   every consuming path? A value: `scalarmult8` consistent with `INV_EIGHT`?
5. **Generators and constants.** Hashed, relation-free, not the identity?
   Did `rct::H`, `ge_p3_H` or a domain string change?
6. **Balance, range, paths.** Does the balance check still run before
   signatures for every accepted type, every output have a bounded range
   proof, and every route into pool and chain reach
   `ver_non_input_consensus` and `check_tx_semantic`? Does a new caller rely
   on a check that lives in another caller?
7. **Batches.** Can one bad proof hide in a batch, or an empty batch pass?
   Is anything skipped or merged that contributes something?
8. **Assumptions.** A new assumption, a paper version without proofs, or a
   proof whose challenge structure differs from the code?
9. **Release builds.** Does safety depend on an `assert` or `DEBUG_BP`?
10. **Secrets.** Fresh randomness per proof and per multisig nonce? Secret
    copies wiped? A `_vartime` function now seeing secret data?
11. **Multisig.** Aggregation coefficients over the sorted key list with a
    tag, keys canonical and prime-order, every nonce and response in `b`?
12. **Consensus bytes.** Does any hashed, signed or compared byte change
    (transcripts, generators, key images, block hashing blob, RandomX
    configuration or seed height)? Fork-gated, with a known-answer test?
13. **Tests.** A negative test for each check touched (identity, torsion,
    unreduced scalar, zero challenge, empty batch) that fails without it?
