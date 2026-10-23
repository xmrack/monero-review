# FCMP++ and Carrot: what the audits require of a pull request

> Nothing in this resource is intended to express any opinions for any audit firms. Please review their source documents for their own words. Summaries here may not fully cover the nuances of their opinions and observations.

What the proofs assume, what each audit found and where the code stands, and
which apparent bugs the record already answers. `subsystems-fcmp-carrot.md`
maps the integration. Each code claim carries the tag of the tree it was
checked in.

| tag | tree | commit |
|---|---|---|
| **(master)** | `monero-project/monero` master | `8340be5e9` (2026-10-19) |
| **(branch)** | `seraphis-migration/monero` `fcmp++-stage` | `62bb16299` (2026-10-05) |
| **(oxide)** | `monero-oxide` `fcmp++` | `31c26d96e` (2026-08-18), the revision the branch pins in `src/fcmp_pp/fcmp_pp_rust/Cargo.toml` |

(oxide) paths are relative to the monero-oxide root. Master has the leaf
pipeline and Rust FFI in `src/fcmp_pp` with no consensus caller, and no Carrot;
`src/carrot_core`, `src/carrot_impl` and the consensus call sites are
branch-only.

**Naming.** "Cypher Stack 2024" is the FCMP++ security proof. "Cypher Stack GBP
2024" is the Generalized Bulletproofs proof. "Carrot spec" is jeffro256's text
of 2026-09-21 unless stated.

**Severities.** Each finding carries its source's rating. Sources without
ratings (the Cypher Stack proofs, Function Analysis, Carrot follow-up and
`carrot_core` audit, the Veridise divisor notes) say "no rating".

**The code wins.** When a PR disagrees with this file, check the invariant,
not the location.

---

## 1. What each proof guarantees, and what it assumes

### 1.1 The composed statement

Per input, FCMP++ proves one statement (Cypher Stack 2024, §4, "main
relation"): there is `(O, I, C)` in the output set `S`, with `O = xG + yT`,
`L = x·I` and `C~ = C + r_c·G`. The spec (Parker 2025, §3) splits it in two.

- **Membership** shows that `(O~, I~, C~, R)` re-randomizes some leaf:
  `O~ = O + r_o·T`, `I~ = I + r_i·U`, `R = r_i·V + r_j·T`, `C~ = C + r_c·G`.
  It needs no spend key.
- **Spend authorization and linkability (SA/L)** shows knowledge of `x, y` for
  `O~`, and that `L = x·I~ − (x·r_i)·U`, which leaves `L = x·I`.

Cypher Stack (2024, §7) proved the composition perfectly complete, CWEE and
SHVZK. The informal properties follow if the protocol keeps these duties:

| Property | Comes from | Obligation on the code |
|---|---|---|
| Membership | extracted `(O, I, C) ∈ S` | the verifier uses the right root and layer count |
| Unspent | `x ↦ L` is deterministic | the verifier rejects any repeated `L` |
| Authorized | strong Fiat-Shamir binds the transaction | the challenge hashes the statement and the message |
| Balance | `C~` commits to the same value as `C` | the C++ balance check still runs |
| Range | BP+ range proofs on outputs | range proofs stay, since membership does not open `C` |

**The proofs assume:**

- Discrete log is hard and `G, H, T, U, V` have no known relation. Veridise
  (2025) adds the GBP generators and the hash-init points `B_curve`, and notes
  that nothing enforces this in code; it rests on public scrutiny of the
  selection. In (oxide) they come from hash-to-curve in
  `monero-oxide/ringct/fcmp++/generators/src/lib.rs` (`FCMP_PLUS_PLUS_U`,
  `FCMP_PLUS_PLUS_V`, `HELIOS_HASH_INIT`, `SELENE_HASH_INIT`), and `T` from
  `crypto::get_T` in `src/crypto/generators.cpp` (master, branch).
- Strong Fiat-Shamir: every statement and transcript element goes into the
  challenge (Cypher Stack 2024, §3, §8.1).
- **`L ≠ 0` stays a verifier check.** If every challenge-multiplied element were
  zero, the prover would never query the hash on the message. Cypher Stack
  (2024, §8.1) says Monero's check "should be retained". It lives in
  `core::check_tx_inputs_keyimages_domain` (master, branch), which also
  rejects key images outside the prime-order subgroup.
  `SpendAuthAndLinkability::verify` (oxide) does not test `L` for identity, so
  the C++ check is the only one.
- The range proofs open `C` uniquely. Cypher Stack (2024, §4) drops that
  opening from the relation for this reason.

**Not established by any proof in this corpus:**

- Simulation extractability of the composed protocol. Cypher Stack (2024,
  §6.3, §7) proves it for SA/L, not for membership.
- Non-slanderability for `O = xG + yT`: the denial of service in which an
  adversary's valid proof reuses an honest `L`. Prior proofs (Omniring,
  Cremers–Loss–Wagner) cover `y = 0`; Cypher Stack (2024, §8.2) calls the
  transfer "difficult to definitely claim".
- Forward secrecy against a discrete-log solver. The spec's argument (Parker
  2025, §5.5) covers SA/L; Cypher Stack (2024, §8.3) notes it also needs a
  membership proof that admits reconstruction for any output.
- Independence of commitment masks. The last re-randomized mask is chosen to
  balance, so the others fix it (Cypher Stack 2024, §4). An observation.

### 1.2 SA/L

SA/L joins the BP+ weighted inner-product argument (one round, `y = 1`) to a
generalized Schnorr proof through a shared nonce, `α = r_x`. Cypher Stack
(2024, Theorem 2) proves this non-standard conjunction CWEE, SHVZK and
simulation extractable (quasi-unique responses). It also corrects the technical
note: witnesses lie in `F`, not `Z`, and `A` uses `r_i`, not `y`.

(oxide) `SpendAuthAndLinkability` in `monero-oxide/ringct/fcmp++/src/sal/mod.rs`.
Its `challenge` hashes the signable transaction hash, the input tuple, `L`, `P`,
`A`, `B`, `R_O`, `R_P` and `R_L`.

### 1.3 Membership circuit

Two Generalized Bulletproofs run over the Selene/Helios cycle (Parker 2025, §4).

- The first layer opens `O~`, `I~`, `C~` to on-curve points plus discrete logs
  over their blinding generators, checks `R`, and checks with
  `TupleMemberOfList` that the leaf tuple is in the chunk.
- Each further layer opens the branch commitment and checks with
  `MemberOfList` that its x-coordinate is in the parent chunk.
- The last layer proves knowledge of the discrete log of
  `(blinded root − claimed root)` over the blind generator: `root_blind_pok`
  in `Fcmp` (oxide).
- The verifier checks that the root is on chain and the layer count matches
  (Parker 2025, §4.6).

The spec argues informally, not by reduction, that Wagner's algorithm does not
apply to `TupleMemberOfList` (Parker 2025, §4.4.1).

Veridise (2025) checked every non-interactive gadget for determinism with
Picus (Equality, Inverse, Inequality, MemberOfList, OnCurve,
IncompleteAddition with and without on-curve assumptions, list lengths 1–8 over
both fields). It proved `TupleMemberOfList` knowledge sound with error `T/q`.
Its tests found no blind reuse, and showed every prover-chosen value changes
the challenge. It assumed no side-channel attacker.

**The circuit does not give:**

- Replay protection. Verifiers must use `R`, which SA/L ties to `L` and `I~`
  (Veridise 2025, trust model; the review covered membership only).
- Constraints on unused chunk entries. The spec says none are needed
  (Parker 2025, §4.6). See §4.
- Prover privacy on its own. The prover needs a cryptographic RNG and fresh,
  unique blinds (Veridise 2025).

### 1.4 Generalized Bulletproofs

Kamp (2023) sets out the notation: an R1CS extended with pre-committed vector
terms, reduced to one inner product. Cypher Stack GBP (2024, §4) found the
original design does not admit a CWEE proof: the extractor yields openings
`C_k = c_L·G_bold + c_R·H_bold + c'·H` and the verifier cannot force `c_R = 0`.
It therefore proved the wider relation, with the scalar-commitment matrix `W_V`
of full rank. Circuit constraints see only `c_L`.

- `audits/generalized-bulletproofs/README.md` (oxide): Brandon Goodell later
  found a protocol flaw; a drafted fix followed, which zkSecurity reviewed with
  the implementation (zkSecurity 2026). zkSecurity also gives an improved
  protocol with a tighter relation, not implemented.
- Simulation extractability is proven for standard Bulletproofs only. For GBP
  it is "highly likely … though a formal proof has not been written"
  (zkSecurity 2026, divisor notes, §3).
- The zkSecurity GBP Lean formalization (2026) proves completeness, perfect
  HVZK and special soundness for the abstract, interactive protocol (no
  Fiat-Shamir, no concrete curve). The oxide README says those proofs are "not
  claimed to directly correspond to the version implemented here".
- Goodell's review (no rating) finds the proofs correct, asks for research into
  the tightness loss of the forking-lemma extraction and for explicit bounds,
  and notes GBP is not quantum-secure. It calls none of these a deployment
  blocker.

### 1.5 The divisor discrete-log gadget

The gadget proves `P = Σ s_i·(2^i·G)` with a committed divisor witness. The
verifier evaluates its logarithmic derivative at three collinear challenge
points derived from the transcript (Parker 2025, §4.4.2; Eagen 2022). The spec
presumes an independent challenge series per interactive gadget (§4.4).

The proof lineage: Eagen (2022) gave a Schwartz–Zippel sketch. Bassa
(Veridise 2024, sums of points) noted that sampling rational lines leaves that
step without a fixed domain, and proved soundness over `E×E` with error about
`18N/q`. Bassa (Veridise 2025, soundness) proved `13kq`-special soundness and
confirmed the gadget instantiates his Protocol II.

- **Coefficients are mod q, not bits.** The spec leaves `s_i` unconstrained on
  purpose and requires only that `s' = Σ 2^i·s_i mod q` cannot be malleated.
  zkSecurity (2026) splits the relation: `R^dlog` (knowledge sound, mod-q
  coefficients) and `R^dlog-honest` (completeness). FCMP++ needs `R^dlog`.
  Veridise (2024, log-derivatives §6) showed that a consumer reading the
  coefficients as integers, for range or balance, would be unsound.
- **The divisor must be non-zero.** The deployed admissible set fixes the
  x-coefficient to 1: (oxide) `Poly::normalize_x_coefficient` in
  `crypto/divisors/src/poly.rs`, called from `crypto/fcmps/src/prover/blinds.rs`.
  zkSecurity (2026, Observation 3) shows `D ≡ 0` would make the check vacuous.
  Some divisors cannot be normalized; `audits/divisors/README.md` (oxide) says
  sampled masks "MUST be followed by checking they have a divisor associated".
- **The verifier recomputes out-of-circuit values.** `α_i` and `β_j` define
  part of the relation and must be bound into the transcript (zkSecurity 2026,
  Observation 5). In the deployed design both derive from bound challenge
  points.
- **The `−P ∈ {B_i}` case.** zkSecurity (2026, Observation 2) notes Bassa's
  extractor does not appear to have included it, and shows a witness is then
  trivially computable, so the protocol needs no change.
- **The concrete error.** Knowledge error about `96(d+k)/q`, with straight-line
  extraction (zkSecurity 2026). zkSecurity notes that `13kq`-special soundness
  alone does not give a polynomial-time extractor after Fiat-Shamir.

The zkSecurity Lean formalization of Eagen's argument (2026) proves
straight-line soundness for the interactive protocol. It has no Fiat-Shamir and
no zero-knowledge; it states the relation over bounded integers rather than a
scalar field; its verifier omits the paper's residue-sum check (sound, but its
completeness theorem covers only that verifier); and it constructs honest
messages only for binary witnesses. No formal artifact covers the deployed
non-interactive gadget.

SLVer Bullet (Cypher Stack 2026) applies divisor techniques to straight-line
verification of Schnorr and Bulletproofs, with soundness error
`n/(2|K|(|K|−1))`. Veridise annotated its July 2025 draft (a `2y` factor in
denominators, rationality of sampled points, the Schwartz–Zippel application;
the Log Derivative notes check the `2y` term numerically). FCMP++ does not use
SLVer Bullet.

### 1.6 Curve trees

A curve tree is a Merkle tree of Pedersen hashes over a curve cycle
(Campanelli, Hall-Andersen, Kamp 2022). Node binding follows from discrete log.
FCMP++ hashes with Pedersen hashes, not an arithmetization-oriented hash such as
Poseidon (Parker 2025, §4.1). Hashing only x-coordinates needs a defence
against `±P`:

- The paper restricts nodes to "permissible" points (§6.1).
- FCMP++ instead hashes `B_curve + H~`, so `−H~` cannot stand in for `H~`
  (Parker 2025, §4.7). (oxide) `crypto/fcmps/src/lib.rs` adds
  `curve_1_hash_init` / `curve_2_hash_init` on both sides. (branch) the C++
  tree uses `helios_hash_init_point` and `selene_hash_init_point`.
- Padding uses `Z = 0` (Parker 2025, §6.1.3), safe only because 0 is not a
  valid x on Helios or Selene and no prime-order Wei25519 leaf has x = 0. Leaves
  must be torsion-free and non-identity.

### 1.7 Helios and Selene

Prime-order short-Weierstrass curves forming a cycle that towers Ed25519, which
cannot join a cycle because of its cofactor (Parker 2025, §4.2).

- Veridise (2025, curve assessment, no formal ratings) found low twist
  security in the nominated pair (107 and 99 bits; "a rather serious security
  risk") and a rigidity gap: smaller discriminants were skipped through a
  search-script bug. It recommended repeating the search with explicit criteria.
- `audits/helioselene/README.md` (oxide): the curves were replaced by a pair
  with a secure twist. Decoding (oxide, `crypto/helioselene/src/point.rs`
  `from_bytes`) recovers `y` from `x` and rejects an off-curve `x`.
- Prime-order Weierstrass curves have no efficient complete formulas, so the
  identity, doubling and adding an inverse need explicit handling (Veridise
  2025).

Formal verification (2026, 64-bit limbs only). Veridise Dafny verifies field
routines; its five point targets (`add`, `double`, `mul`, `from_bytes`,
`to_bytes`) are marked not verified. Least Authority's Aeneas/Lean work (tool:
Ho & Protzenko 2022) proves the field is `ZMod p` and both group laws and
ladders correct on on-curve inputs. Its `invert` proof covers a hardened `step`
that replaces the top-limb OR with a carry chain, because the original could
not be proved; a 4-million-input search found no failing input. (oxide)
`invert.rs` still uses the OR, which Veridise's hand-translated Lean proof of
six field operations models. None covers point decoding, constant time or
zeroization, and Aeneas trusts its own translation.

---

## 2. Findings by component

### 2.1 Ed25519-to-leaf pipeline

Sources: Trail of Bits (2026, draft and final; phases 1a/1b, excluding the
proof system, tree and divisors) and the Cypher Stack Function Analysis (2026,
no ratings, fuzzed under sanitizers). Both found the reviewed functions fit for
deployment. Trail of Bits confirmed that torsion clearing
stops torsioned spendable outputs aliasing to one leaf, and that under the
team's spendability rules no spendable output becomes unspendable. It notes it
did not confirm that every validation path enforces those rules, and
recommended edge-case and sanitizer tests and an enumeration of historical
receive-detection implementations.

| Finding | Rating | Code now |
|---|---|---|
| TOB-MAGIC-FCMP-1: `point_to_wei_x_y` inverts zero for `(0, −1)`, yet the result is correct | Informational, Resolved | `fe_batch_invert` returns `-1` when the running product is zero; `ed_derivatives_to_wei_x_y` propagates it (master, branch) |
| TOB-MAGIC-FCMP-2: `ge_double_scalarmult_base_vartime_p3` and `ge_double_scalarmult_precomp_vartime2_p3` leave `r3` unset when both scalars are zero | Informational, Resolved | (master) both call `ge_p3_0(r3)` first. **(branch) neither does** |
| TOB-MAGIC-FCMP-3: `fe_equals` might not be constant time | Informational, Resolved | `crypto_verify_32` (master, branch) |
| TOB-MAGIC-FCMP-4: `fe_c` is the negated IETF root | Informational, Resolved | `fe_c` in `src/crypto/crypto-ops-data.c` is `0x70d9…81e7` (master, branch); monero-oxide changed with it |
| TOB-MAGIC-FCMP-5: `sc_check` left-shifts negative values | Informational, Resolved | `signed_lshift` (master, branch) |
| TOB-MAGIC-FCMP-6: the `SeleneScalar` FFI relies on layout | Informational, **Partially Resolved** | `static_assert_size_eq!` in `src/fcmp_pp/fcmp_pp_rust/src/lib.rs`, `static_assert(sizeof(SeleneScalar) == 32)` in `src/fcmp_pp/fcmp_pp_types.h` (master, branch); layout still depends on the `crypto-bigint` `c-repr` patch in `Cargo.toml` |

Function Analysis observations (no ratings):

- `edwardsYZ_to_x25519` turned the identity into `u = 0`, a 2-torsion point;
  `edwards_bytes_to_x25519_vartime` did no curve check. Now (master, branch)
  the former returns `-1` when `Z − Y = 0`, and the bytes path decodes with
  `ge_frombytes_vartime`.
- `fe_batch_invert`: a zero input poisoned the batch (now returns `-1`); `n` is
  now `unsigned int`. **The out/in overlap check is still an `assert`**,
  compiled out in release builds (master, branch).
- `fe_frombytes_vartime` masks bit 255, so two encodings decode alike.
  Unchanged. `fe_reduce_vartime` had no dedicated fuzz harness.
- Torsion helpers renamed with `_vartime` (branch): `mul8_is_identity_vartime`,
  `clear_torsion_vartime`, `get_valid_torsion_cleared_point_vartime`.
- `EC_INV_EIGHT` was typed as a point. (branch) `fcmp_pp_crypto.h` retypes it
  as `ec_scalar`; `crypto.h` keeps the point-typed one. (master)
  `ge_clear_torsion_vartime` uses `sc_inv_eight`.
- The identity check after torsion clearing looked redundant behind
  `mul8_is_identity`. **That pre-check is gone on master and the branch.**
  `get_valid_torsion_cleared_point_vartime` (master `src/crypto/crypto.cpp`,
  branch `src/fcmp_pp/fcmp_pp_crypto.cpp`) now rejects small-order points only
  through `torsion_cleared_out == EC_I`.
- `unbiased_hash_to_ec` had no domain tag; clearing the cofactor before the sum
  is equivalent to RFC 9380's order. (master, branch) It now uses
  `blake2b_monero`, which sets the "Monero" personalization.
- `output_to_tuple` / `output_tuple_to_pre_leaf_tuple` decompress legacy `O`
  and `C` twice. Performance only.

**Tree maintenance** (j-berman 2026, integration design doc). Block `n` adds
every output whose last locked block is `n+9`, so the tree runs ahead of the
chain. Timestamp unlocks map to a block through `get_last_locked_block_index`,
a new consensus rule for FCMP++ spends. `BlockchainDB::trim_block` reverts one
block at a time from stored tree edges. Outputs off Ed25519, or identity after
clearing, are skipped. Proof length is fixed by `(inputs, n_tree_layers)`
(`fcmp_pp::fcmp_pp_proof_len`, branch).

**A PR here is risky if it:**

- deletes the `EC_I` comparison in `get_valid_torsion_cleared_point_vartime` as
  "redundant". It is the only rejection of small-order points;
- feeds `fe_batch_invert` attacker-chosen data while ignoring its return value,
  or lets `out` and `in` overlap;
- derives `I` from the torsion-cleared `O`. `I` must come from the original
  key, because clearing maps distinct keys to one point (Function Analysis
  §10.2; `output_to_tuple`, master and branch);
- changes which outputs `outputs_to_leaves` skips. A wider skip strands
  spendable funds; a narrower one admits `x = 0` or torsioned leaves;
- makes grow and trim asymmetric, or changes the last-locked-block mapping,
  which changes every later root;
- moves `fe_c`, `fe_a_inv_3` or the Weierstrass formulas without a known-answer
  test. Trail of Bits found the `fe_c` sign by comparing with the IETF draft;
- adds a caller of `ge_double_scalarmult_*_p3` with possibly-zero scalars on a
  tree without `ge_p3_0(r3)` (the branch at `62bb16299`).

### 2.2 Key image generator and transparent commitments

- **Hash-to-point.** Trail of Bits (2026) confirmed the generator is Elligator 2
  and the unbiased variant is "hash-twice-and-add". The Function Analysis (§9)
  gave an informal unbiasedness proof, not formally verified. With the
  "Monero" personalization, `unbiased_hash_to_ec` matches the Carrot spec's
  `H_p^2` (§3.3.2).
- **`zeroCommitVartime` and `H_TABLE`** were found correct (Function Analysis
  §3). Fuzz seeds included `2^32`, the boundary of an earlier `1UL` bug (master,
  branch, `src/ringct/rctOps.cpp`).

**A PR here is risky if it:**

- changes the preimage or personalization of `unbiased_hash_to_ec`. Every
  Carrot key image changes, and so does `T`: the 2026 spec corrected `T` to the
  personalized value `src/crypto/generators.cpp` already uses;
- uses `blake2b_monero` for a second hash-to-curve without its own domain tag
  (Function Analysis §9.3.3, cross-protocol collisions).

### 2.3 FCMP circuit (oxide `crypto/fcmps`)

Veridise (2025) found nothing rated Low or above. Both findings were fixed and
confirmed.

- V-FCMP-VUL-001, Warning: duplicated logic (the two challenge points in
  `discrete_log_challenge`, the repeated `to_xy().unwrap()` in `FcmpParams::new`).
- V-FCMP-VUL-002, Info: the `divisor_challenge_eval` comment, the
  `OutputBlinds::new` docs, leftover `dbg!`.

Veridise recommended automated tape serialization because indexing is manual;
the developers kept the existing read/write tape.

**A PR here is risky if it:**

- adds a prover-chosen value that is not in a vector commitment hashed before
  its challenge;
- reorders tape reads or writes (manual indexing, which Veridise called
  error-prone);
- reuses a blind across branches or inputs (Veridise's privacy test);
- changes `Fcmp::proof_size` or `ipa_rows`. Their doc comment says they may
  panic on overflow and return a wrong value for zero inputs or layers; the
  branch caps `FCMP_PLUS_PLUS_MAX_INPUTS` and `FCMP_PLUS_PLUS_MAX_LAYERS` must
  keep both away from those values (FFI: `subsystems-fcmp-carrot.md` §3).

### 2.4 Generalized Bulletproofs (oxide `crypto/generalized-bulletproofs`)

zkSecurity (2026) found no High or Medium issues and gave a fresh
knowledge-soundness proof. Status comes from the commit that incorporated the
audit, `31c26d96e` itself.

| # | Finding | Rating | Status at (oxide) |
|---|---|---|---|
| 00 | `LinComb::add` concatenates rather than coalescing, so it can grow exponentially | Low | behaviour documented |
| 01 | Pippenger `multiexp` makes secret-dependent memory accesses in the prover | Low | commit message: resolved in the dependency |
| 02 | `PedersenVectorCommitment::commit` reallocates without zeroizing | Low | deferred (best effort); `vec![(self.mask, h)]` unchanged |
| 03 | a rank-deficient `W_V` binds only an aggregate, not individual openings | Low | `ArithmeticCircuitStatement::new` now requires a constraint per Pedersen commitment, stricter than full rank |
| 04 | `Generators::new` checks `g` only in `debug_assert!` | Informational | `assert!` |
| 05 | `IpStatement::prove` accepts generator vectors of the wrong length | Informational | `IpWitness::new` and `IpStatement::new` require power-of-two lengths |
| 06 | the padded tail of a vector commitment is unconstrained unless the caller constrains it | Informational | documented on `ArithmeticCircuitStatement::new` |

**A PR here is risky if it:**

- builds a GBP statement from external scalar commitments without one
  constraint each, or relaxes that check;
- treats a vector commitment as "exactly these `n` values". The `G_bold` tail
  and every `H_bold` coordinate are free unless constrained (#06; Cypher Stack
  GBP 2024, §4);
- forces `c_R = 0` in the verifier as a "fix". That is a different relation,
  which the existing proof does not address (§4).

### 2.5 Divisors

| Source | Finding | Rating | Status |
|---|---|---|---|
| Veridise gadget note (2024) | sign errors in the `λ` terms of the spec's `DiscreteLog` | no rating | spec corrected later; Veridise soundness paper (2025) lists three remaining typos |
| Veridise gadget note (2024) | `s_i` not constrained to bits, while the analysis assumed positive coefficients | no rating ("merits additional caution") | resolved at relation level by working mod q (§1.5) |
| Veridise gadget note (2024) | Fiat-Shamir should bind context (curve, generators) | no rating | — |
| Cypher Stack Further Review (2025) | no stated protocol type or soundness definition; calculus at higher multiplicities; an "implication problem" (one proof covers a family of statements); developer "watermarking" (divisor witnesses are not unique); only asymptotic error bounds | no ratings; conditional recommendation against deployment pending more research | Veridise's response (2025) answered each point with explicit bounds. zkSecurity (2026) formalized the two relations and proved simulation extractability of the composition for standard Bulletproofs |
| Cypher Stack Further Review (2025) | Parker's Rust divisor implementation | — | "not problematic" |
| zkSecurity notes (2026) | Observations 2, 3, 5 (§1.5) | no rating | proof-level; no protocol change |
| zkSecurity, via the oxide README | x-coefficient normalization is incomplete; malleated congruent discrete logs may have usable divisors | no rating | the inner-product alternative was declined "due to how late in the process it was suggested"; upstream calls the gap negligible, "only possibly preventing certain rerandomizations from use (never certain outputs)" |

(oxide) `ec-divisors`, which builds the witness, is prover-only and unaudited
(`audits/divisors/README.md`). `Poly::normalize_x_coefficient` calls
`invert().unwrap()` with no fallback.

**A PR here is risky if it:**

- reuses the gadget where coefficients act as integers (range, balance);
- lets the verifier read `α`, `β` or any challenge-derived hint from the proof
  instead of recomputing it;
- changes how challenge points are sampled, derived or assigned to gadgets. The
  bounds assume the sampling the proofs analyse and an independent series per
  gadget (Parker 2025, §4.4);
- adds a path where a non-normalizable blind panics the prover instead of
  resampling.

### 2.6 Helios/Selene (oxide `crypto/helioselene`)

| Source | Finding | Rating | Status at (oxide) |
|---|---|---|---|
| Least Authority (2026), Issue A | `from_bytes` decoded zero bytes to `{x:0, y:1, z:1}`, not the identity, which reached FCMP verifier equations through `read_G` | **High** | Resolved. "Fix `helioselene`'s `from_bytes` and `to_bytes` functions" is in `31c26d96e`; `from_bytes` now selects `Point::identity()` and rejects negative identity |
| Least Authority (2026), Issue B | zeroization leaves copies, because the types are `Copy` | Undetermined | Partially Resolved; caller responsible |
| Least Authority (2026), Suggestion 1 | thin tests; no 32-bit CI; no release-assembly constant-time checks | Informational | Unresolved |
| Veridise Dafny (2026) and Lean (2026) | the partial-width divstep schedule in `invert` returned a non-inverse while reporting success, e.g. for `3·2^66` | no rating | fixed: "Fix `HelioseleneField::invert`" is in `31c26d96e`; regression test `invert_3_66` in `crypto/helioselene/src/field/verified/invert.rs` |
| Veridise curve assessment (2025) | low twist security; rigidity gap; tight search criteria | no formal rating | curves replaced (§1.7) |

**A PR here is risky if it:**

- changes `from_bytes`, `to_bytes` or `read_G`, especially around the identity,
  `-0` or the sign bit;
- changes `invert`, `red256`, `red512` or `sqrt` without the full-width schedule
  and Least Authority's edge tests;
- cites the Lean or Dafny proofs for decoding, 32-bit builds, constant time, or
  for `invert` exactly as shipped (only Veridise's Lean models the shipped
  `step`; §1.7);
- bumps the pinned `rev` in `src/fcmp_pp/fcmp_pp_rust/Cargo.toml` (branch) to a
  revision without either fix.

---

## 3. Carrot

### 3.1 Key hierarchy and tiers

The spec (§5) defines the new hierarchy: `s_m` derives `k_ps` and `s_vb`;
`s_vb` derives `s_gp`, `k_v` and `s_ga`; `k_gi = ScalarDerive(s_gp ‖ k_ps·T)`;
`K_s = k_gi·G + k_ps·T`; `K_v = k_v·K_s`. (branch)
`make_carrot_generateimage_key` in `src/carrot_core/account_secrets.cpp` binds
the partial spend pubkey. The dependency diagram (Cypher Stack 2025) shows the
older `k_gi`.

| Tier | Holds | Must not be able to |
|---|---|---|
| Generate-Address | `s_ga` | see anything on chain |
| View-Received | `k_v` | see internal enotes or spends |
| View-All | `s_vb` | spend |
| Master | `s_m` | — |

Cypher Stack (2024) found every stated property holds under standard
assumptions and made eight non-mandatory recommendations. Open ones: how `s_m`
is sampled and how long it is (rec. 8; the spec still fixes neither), stating
security parameters, and analysing clamping (left as future work). It also
suggested a two-generator formulation of output indistinguishability (spec
§9.4.1 models `K_o = r_1·G`). Legacy wallets keep `k_v = ScalarDeriveLegacy(k_s)`.

**A PR here is risky if it** gives a tier a secret from above it, or derives a
secret from anything other than the spec's parent. Internal forward secrecy
rests on `s_vb` staying out of the lower tiers (Cypher Stack 2024, §3.3.2).

### 3.2 Enotes, input context, burning bug

- `input_context` is `"R" ‖ first key image`, or `"C" ‖ height` for coinbase.
  It feeds `s_sr^ctx` and every component. Uniqueness comes from consensus
  (spec §7.2).
- Burning-bug resistance (one `K_o` cannot pass the scan under two input
  contexts) reduces to collision resistance and the binding of `C_a` (Cypher
  Stack 2024, §3.1.4). (branch) `make_carrot_input_context` and
  `make_carrot_input_context_coinbase` in `src/carrot_core/enote_utils.cpp`.
- Adding `a ‖ K_s^j` to `k_a` has no security effect (follow-up §2.2). (branch)
  `make_carrot_amount_blinding_factor` matches.

### 3.3 Janus protection

The scan recovers `K_s^j'` and requires one of two checks (spec §8.1):

- **normal**: re-derive `d_e'` from the anchor, input context, `K_s^j'`,
  `K_v^j'` and `pid'`, and compare `D_e'` with `D_e`, once with the decrypted
  payment ID and once with the null one;
- **special**: compare the anchor with
  `anchor_sp = SecretDerive(D_e ‖ input_context ‖ K_o ‖ k_v)[:16]`.

Coinbase uses only the normal check. Internal enotes need none, since
`s_sr = s_vb` proves self-origin.

- **`d_e` binds `K_v^j` again.** The follow-up (§2.3) accepted removing it but
  called hash-input removal "risk-prone" and noted the Enote Scan Binding proof
  no longer held as written. The 2026 spec restored it. (branch)
  `make_carrot_enote_ephemeral_privkey` hashes `K^j_s, K^j_v`;
  `verify_carrot_normal_janus_protection` recomputes it.
- **`anchor_sp` dropped `K_s`**, reviewed as having no effect (follow-up §2.4).
  (branch) `make_carrot_janus_anchor_special` hashes `D_e, input_context, K_o`
  under the key `k_v`.
- **An informal concern stays open.** The anchor check has the shape
  `SecretDerive(x) ⊕ SecretDerive(y) = anchor_enc`, a structure open to
  generalized-birthday attacks in other settings; Cypher Stack (2024, §3.1.5)
  says "this argument needs better formalizing" and shows no attack.
- (branch) Tests: `tests/unit_tests/carrot_core.cpp` (`janus_protection_*`).

**A PR here is risky if it:**

- adds a scan path (external, coinbase, sender-side or batched) that returns
  success without the normal or special check;
- drops a field from any Carrot transcript; both removals in the follow-up
  needed their own argument;
- treats `D_e' == D_e` as optional when the payment ID is null.

### 3.4 View tags

Three bytes of `SecretDerive(s_sr ‖ input_context ‖ K_o)`, for speed only. The
follow-up (§3.1) withdrew the v1.0 audit's two security uses of `vt`. **A PR is
risky if** a view-tag match stands in for, or skips, the commitment or Janus
check.

### 3.5 Subgroup and cofactor checks

X25519 here is **unclamped** (spec §3.3.1), so small-subgroup defence must be
explicit. The follow-up (§0.1) asks for an order-ℓ check on `D_e` and "all
pertinent public values", and stresses testing membership in order ℓ, not
"not order 8", because orders `2ℓ`, `4ℓ` and `8ℓ` exist.

| Check | Required by | Where (branch) | Status |
|---|---|---|---|
| `D_e` in order ℓ before scanning | follow-up §0.1 | none; `try_make_carrot_shared_key_receiver` computes `k_v·D_e` unchecked | **not implemented** |
| `K_o` in the prime-order subgroup | follow-up §0.1; `carrot_core` audit §4.6 | sender: `get_output_enote_proposals`, `get_coinbase_output_enotes` (`output_set_finalization.cpp`). Consensus: `rct::verPointsForTorsion` (from `ver_non_input_consensus` and `Blockchain::validate_miner_transaction`) rejects torsion and identity for Carrot `K_o` and `C_a` | present |
| `K_s^j'` in the prime-order subgroup (step 18) | spec §8.1 | omitted; `carrot_core` audit §5.2 calls it redundant given a torsion-free `K_o` | omitted, argued redundant |
| key images in the prime-order subgroup | spec §4.2 | `core::check_tx_inputs_keyimages_domain` | present |

**About `D_e`.** The follow-up argues an order-8 `D_e` gives `s_sr = O` about
12.5% of the time, that the normal check then fails, and that the step-34
special check passes "by construction". On the branch the special anchor is
keyed by `k_v`, which the sender lacks; the sources do not settle how that
interacts with the step-34 argument. Treat the explicit check as requested
defence in depth that the branch omits. **A PR that removes or weakens either
Janus check loses the protection that check would back up.** The follow-up also
asks the spec to stop presenting `anchor_sp` as small-subgroup protection
(§2.1, §0.2); spec §7.3.5 still does.

**A PR here is risky if it:**

- adds clamping or a clamping X25519 in place of `mx25519`; every shared secret
  for existing `k_v` changes (spec §3.3.1);
- replaces an order-ℓ test with "not small order";
- lets a Carrot output into the tree without `verPointsForTorsion`;
  `output_to_tuple` skips torsion clearing when `output_checked_for_torsion`
  returns true;
- relies on step 18's redundancy while accepting `K_o` from a source consensus
  did not check;
- consumes a new externally supplied point in ECDH or scanning without an
  order-ℓ check.

### 3.6 `carrot_core` audit observations

Cypher Stack (2026), no ratings, no remediation status. It found the specified
properties present and every `config.h` separator matching the spec byte for
byte.

- §5.1: Blake2b keyed mode where the spec writes concatenation; equivalence not
  proven. (branch) `hash_base` in `src/carrot_core/hash_functions.cpp` sets the
  "Monero" personalization, with the key as the first block.
- §5.2: step 18 omitted, as above.
- §5.3: C++ uses dedicated coinbase separators over `a ‖ K_s^j`; `carrot-rs`
  uses the standard ones with `C_a = G + aH`. The 2026 spec (§7.4.1) defines
  "Carrot coinbase extension G/T" over `s_sr^ctx ‖ a ‖ K_s^j`, and (branch)
  `src/carrot_core/config.h` matches. Other implementations must match, or
  coinbase scanning diverges.
- §5.4: the `derive_bytes_3` comment said two bytes; (branch) it now says three.

### 3.7 Background and successor designs

None of these is deployed code; they explain Carrot's choices and constrain
later changes.

- **Seraphis** (koe 2023; koe and jeffro256 2024) separates membership from
  ownership proofs, with a three-tier view hierarchy and Jamtis addressing.
  FCMP++ reaches full-set membership without its new linking tags and the
  migration they force (Parker 2025, §1). Both papers are drafts without full
  security proofs.
- **Post-quantum.** Carrot gives address-conditional and internal forward
  secrecy only (spec §9.3); no source here gives post-quantum soundness.
  tevador's Jamtis PQ draft (2026) adds CSIDH-1024 address encryption
  (rationale: research-lab #151) and is designed to stay on-chain
  indistinguishable from Carrot. Jamtis-RCT is marked obsolete. Monero-PSK
  (draft) replaces scanning with pre-shared keys. Parker's PQ sketch (2024)
  outlines a STARK-based fallback. All are drafts.

**A PR is risky if it** changes Carrot's enote layout or distributions in a way
that would make Carrot outputs distinguishable from a planned successor's, or
claims post-quantum protection beyond spec §9.3.

---

## 4. Looks like a bug, is not

Candidate findings that the audits and the construction already answer. Check a
new report against them before rating it. In most, the mechanism is real and
the security impact is not.

**Torsion in range-proof commitments.** zkao reported this against
monero-oxide (June 2026, High). The verifiers transcript `C·INV_EIGHT` and then
multiply by 8, so a proof for `C₀` verifies against `C₀ + T`. zkao's own impact
section states no end-to-end Monero exploit was shown and that consensus
compatibility may constrain any fix. The construction explains why:

- torsion carries no `H` coefficient, so the in-range claim stays true;
- balance is on `H` coefficients;
- double-spend protection is the key image's job, and key images are
  subgroup-checked;
- `monerod` accepts the same proofs, so rejecting them would split the chain.

zkao's July 2026 follow-up (High) extends the mechanism to the Borromean
verifier through challenge parity. It states that inflation is not established
and that its rating applies to integrations needing exact-point semantics.

**Limit under FCMP++:** this concerns range-proof semantics only. For Carrot
outputs, torsion-freeness of `K_o` and `C_a` matters: `output_to_tuple` does not
clear their torsion, and the tree needs prime-order leaves. Consensus enforces
it through `verPointsForTorsion` (branch). Relaxing that check is a real bug.

**Vector commitments that open over `H_bold`.** zkao (August 2026) rated this
Medium, soundness.

- The wider opening is the proven relation (Cypher Stack GBP 2024, §4), and
  zkSecurity #06 (Informational) covers the same behaviour.
- zkao's report itself finds no membership forgery: the root-blind proof and the
  cross-curve links bind whole points, so using the slack needs a discrete-log
  relation.
- Unused chunk entries need no constraint (Parker 2025, §4.6).

The integration hazard is the circuit-reachable `G_bold` tail of a
non-power-of-two vector (#06). Forcing `c_R = 0` would invalidate the proof
(§2.4); a narrower relation needs zkSecurity's improved protocol and its proof.

Shorter answers:

| Looks like | Why it is not | Source |
|---|---|---|
| unconstrained `s_i` in the discrete-log gadget | by design; the proven relation is mod q. A bug only in a consumer needing integer semantics (§1.5) | Parker 2025 §4.4.2; zkSecurity 2026 |
| a divisor proof malleated onto a related statement | the Further Review costs its own attack at a hash collision; the simulation-extractable composition closes the class for standard Bulletproofs (GBP formally open, §1.4) | Cypher Stack 2025; Veridise 2025 response; zkSecurity 2026 |
| the "2y factor" and other points raised about SLVer Bullet | a separate protocol FCMP++ does not use | Veridise 2025 annotations; Cypher Stack 2026 |
| divisors with a zero x-coefficient | completeness only: the prover resamples; never a false statement, never a blocked output (§2.5) | oxide `audits/divisors/README.md` |
| membership does not extract an opening of `C` | intended; the range proof opens `C` | Cypher Stack 2024 §4 |
| `r_j` is not extractable from SA/L | the composition extracts what the main relation needs | Cypher Stack 2024 §6–§7 |
| variable-time torsion clearing | inputs are public chain data | Function Analysis §6.5 |
| cofactor cleared before the sum in `unbiased_hash_to_ec` | equivalent to RFC 9380's order | Function Analysis §9.3.3 |
| `point_to_wei_x_y` on `(0, −1)`; the sign of `fe_c` | both gave correct results before the fixes | TOB-MAGIC-FCMP-1, -4 |
| zero scalars in `ge_double_scalarmult_*_p3` | current callers use random scalars; real only for a new caller on a tree without `ge_p3_0(r3)` | TOB-MAGIC-FCMP-2 |
| step 18 (`K_s^j'` subgroup check) missing | redundant given a torsion-free `K_o` | `carrot_core` audit §5.2 |
| C++ and Rust coinbase extensions differ | the 2026 spec matches the C++ (§3.6) | `carrot_core` audit §5.3 |
| a 3-byte view tag | convenience, not security | follow-up §3.1 |
| `anchor_sp` "is not an HMAC" | naming only; describe it as checked through a one-way function | Cypher Stack 2024 rec. 1; follow-up §0.2, §3.3 |
| cofactor removed from `s_sr` | accepted, provided the §3.5 checks hold | follow-up §2.1 |
| `reference_block` outside the signed hash | deliberate, for transaction chaining. (branch) `Blockchain::validate_miner_transaction` requires a coinbase output from the fork "so that we guarantee every usable tree root is unique", so a relayer cannot re-point the proof at a block with the same root | Parker 2025 §5.6, §6.6 |
| twist attacks on Helios/Selene | the deployed pair has a secure twist and decoding rejects off-curve `x`; a report needs a path that skips `from_bytes` | Veridise 2025; oxide `audits/helioselene/README.md` |

---

## 5. SPEC-angle checklist for FCMP++ and Carrot diffs

Use when a diff touches `src/fcmp_pp`, `src/carrot_core`, `src/carrot_impl`,
the FCMP++ or Carrot consensus checks, or the pinned monero-oxide `rev`.

1. **Spec section.** Name the FCMP++ (Parker 2025) or Carrot (2026-09-21)
   section implemented. The 2026 Carrot text changed `T` and binds `K_v^j` in `d_e`.
2. **Generators.** `T`, `U`, `V`, `H`, `B_curve` and GBP vectors match their
   derivations byte for byte; `T` is `dc42e1d3…` (spec §3.3.2, `src/crypto/generators.cpp`).
3. **Relation.** Write it before and after; compare with the main relation
   (Cypher Stack 2024), the GBP relation with `H_bold` (Cypher Stack GBP 2024)
   and `R^dlog` (zkSecurity 2026). A wider relation needs a new proof.
4. **Fiat-Shamir.** Everything a challenge depends on is hashed first
   (`transcript` in `crypto/fcmps/src/lib.rs`; `SpendAuthAndLinkability::challenge`, oxide).
5. **`L ≠ 0`, prime-order `L`.** `core::check_tx_inputs_keyimages_domain` runs for every input.
6. **Root and layer count** come from the verifier's own DB (Parker 2025, §4.6).
7. **Proof length** derives from `(inputs, layers)` within the C++ caps, never
   zero, before Rust reads a byte.
8. **x-only hashing.** `B_curve` on both sides at every layer; padding `Z = 0`;
   no leaf with `x = 0` (spec §4.7, §6.1.3).
9. **Leaves.** Legacy: torsion-cleared, non-identity, `I` from the original key.
   Carrot: only consensus-checked `K_o`, `C_a`. Daemon and wallet agree on every
   torsion coset; grow and trim stay symmetric (§2.1).
10. **Encoding.** Canonical, on-curve decoding; identity handled as in Least
    Authority Issue A's fix; Ed25519 conversions reject `Z = Y` and `x = 0`.
11. **Divisors.** Mod-q coefficients; verifier recomputes `α`, `β`; `(0,0)` not
    admissible, prover resamples; challenge derivation as analysed (§1.5).
12. **GBP use.** One constraint per external scalar commitment; unused `G_bold`
    coordinates omitted or constrained (zkSecurity #03, #06).
13. **Carrot transcripts.** Separators, order, widths and byte order match spec
    §7.4 and `config.h`; format changes update `tests/unit_tests/carrot_convergence.cpp`;
    no hash input dropped silently (follow-up §2.3).
14. **Keyed hashing.** Blake2b, "Monero" personalization, keyed by the secret
    the spec puts first (`hash_base`; `carrot_core` audit §5.1).
15. **X25519.** Unclamped; receiver-side point checks test order ℓ (spec §3.3.1; follow-up §0.1).
16. **Scan.** Every success path checks the commitment (coinbase:
    `K_s^j' = K_s`), then normal or special Janus; internal scans use `s_vb`;
    view tags decide nothing (spec §8.1).
17. **Coinbase.** Main addresses, `"payment"`, coinbase extension separators,
    `"C" ‖ height` (spec §7.9, §7.4.1).
18. **2-out rules.** One payment and one change; shared `D_e` per spec §7.5,
    §7.8.4; duplicate `K_o` rejected.
19. **Key tiers.** Each tier holds only its own secrets; `k_gi` binds `k_ps·T` (spec §5).
20. **Constant time and zeroization** of prover secrets do not regress
    (zkSecurity #01, #02; Least Authority Issue B).
21. **Dependency bump.** A new oxide `rev` keeps the helioselene and GBP fixes;
    diff `audits/*/README.md` for newly declined recommendations.
22. **Master versus branch.** Ported crypto-ops fixes land in both; the branch
    lacks TOB-MAGIC-FCMP-2's fix.

---

## Sources

- Campanelli, Hall-Andersen, Kamp. *Curve Trees: Practical and Transparent Zero-Knowledge Accumulators.* 2022.
- Eagen, Liam. *Zero Knowledge Proofs of Elliptic Curve Inner Products from Principal Divisors and Weil Reciprocity.* 2022.
- Ho, Protzenko. *Aeneas: Rust Verification by Functional Translation.* 2022.
- koe. *Seraphis: A Privacy-Preserving Transaction Protocol Abstraction* (WIP). 2023.
- Kamp, Simon. *Generalized Bulletproofs — Notation.* 2023.
- Goodell, Brandon (Cypher Stack). *Security Review — Generalized Bulletproofs.* 2024 (approx.).
- Cypher Stack (Aaron Feickert). *Generalized Bulletproofs* (security proof). 2024.
- Cypher Stack. *FCMP++ Review* (security proof). 2024.
- Veridise (Alp Bassa). *Soundness Proof for Eagen's Proof of Sums of Points.* 2024.
- koe, jeffro256. *Implementing Seraphis* (WIP). 2024.
- Veridise (Alp Bassa). *Notes on the R1CS Gadget for Providing Discrete Logarithm Proofs.* 2024.
- Veridise (Alp Bassa). *On the Use of Logarithmic Derivatives in Eagen's Proof of Sums of Points.* 2024.
- Cypher Stack. *An Audit of the FCMP++ Addressing Protocol: CARROT.* 2024.
- Parker, Luke. *Post-quantum Monero* (design sketch). 2024.
- Veridise (Alp Bassa). *Soundness Proof for an Interactive Protocol for the Discrete Logarithm Relation.* 2025.
- Parker, Luke. *FCMP++* (specification). 2025.
- Cypher Stack (Goodell, Salazar, Slaughter, Szramowski). *A Further Review of the DL Gadget Of Interest.* 2025.
- Veridise. *FCMP++ Security Review.* 2025.
- Veridise (Bassa, Şepanski). *Response to "A Further Review of the DL Gadget Of Interest".* 2025.
- Veridise. *Log Derivative Notes* and verification notebook. 2025.
- Veridise (Bassa, Şepanski). *SLVer Bullet — annotated first-look review.* 2025.
- Cypher Stack (Goodell, Salazar, Slaughter, Szramowski). *CARROT Audit Follow-Up.* 2025.
- Cypher Stack. *CARROT Dependency Diagram.* 2025.
- Veridise. *Security Assessment for the Helios–Selene Curve Cycle.* 2025.
- tevador. *Post-quantum encryption* (research-lab #151). 2025.
- Cypher Stack (Goodell, Salazar, Slaughter, Szramowski). *SLVer Bullet: Straight-Line Verification for Bulletproofs.* 2026.
- Cypher Stack (Joshua Babb). *CARROT `carrot_core` Implementation Audit.* 2026.
- j-berman. *FCMP++ Integration* (design documentation, WIP). 2026.
- tevador. *JAMTIS-RCT* (obsolete). 2026.
- Veridise. *Dafny proofs of helioselene field and point routines.* 2026.
- zkSecurity (Hall-Andersen, Aranha). *Notes and Proofs for Divisor Techniques.* 2026.
- Trail of Bits (Joe Doyle). *MAGIC Grants Monero FCMP++ Crypto Security Assessment* (draft). 2026.
- tevador. *Monero-PSK* (draft). 2026.
- Cypher Stack (Babb, Goodell, Salazar, Slaughter, Szramowski). *FCMP++ Function Analysis.* 2026.
- zkSecurity. *Generalized Bulletproofs* (technical report on the monero-oxide crate). 2026.
- tevador. *Jamtis: A Post-Quantum Addressing Protocol for Monero* (draft). 2026.
- zkao. *Range proofs can be accepted for a different commitment than the one supplied* (monero-oxide). 2026.
- Least Authority. *Aeneas/Lean formal verification of helioselene.* 2026.
- Trail of Bits (Joe Doyle). *MAGIC Grants Monero FCMP++ Crypto Security Assessment* (final, with fix review). 2026.
- zkSecurity (Hall-Andersen). *Formal Verification of Generalized Bulletproofs* (Lean 4). 2026.
- zkao. *Torsion-bearing commitments let attackers forge accepted range and Borromean proofs* (monero-oxide). 2026.
- zkao. *Attackers can prove vector-commitment openings outside the advertised commitment language* (generalized-bulletproofs). 2026.
- Bhati, Tariq, Ashur. *From Round Skipping to S-Box Skipping: Attacking Poseidon's Partial Layer via Subspace Restriction.* 2026. (Context only: FCMP++ uses Pedersen hashes, not Poseidon.)
- zkSecurity (Hall-Andersen). *Formalization of Eagen's ECIP Proof* (Lean 4). 2026.
- Veridise. *Lean 4 formal verification of helioselene `invert`.* 2026.
- jeffro256. *Carrot — Specification* (version of 2026-09-21; supersedes the earlier undated copy). 2026.
- Least Authority. *Helios and Selene Curve Cycle — Security Audit Report* (final). 2026.
- monero-oxide maintainers. `audits/*/README.md` at `31c26d96e`. 2026.
