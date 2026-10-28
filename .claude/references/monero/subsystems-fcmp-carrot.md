# FCMP++ and Carrot integration

What the FCMP++/Carrot integration changes, the rules it must keep, and the
questions to ask of a pull request that brings part of it to master.

**Where this comes from.** On master, `src/fcmp_pp` is staged with no callers
and Carrot is absent (`codebase-notes.md`, "FCMP++ work"). The integration is
built on the `fcmp++-stage` branch of `seraphis-migration/monero` and reaches
master in pieces. Claims marked **(branch)** were checked against that branch
at `f25388d` (2026-10-21); **(master)** against master `3fd0f88c2`. Design
claims come from the Carrot specification and the FCMP++
integration notes.

**A pull request will not match this snapshot.** Names move, rules split across
PRs, fork numbers change. Use this file for invariants and questions, not as a
map of where code must be. Where a PR disagrees with this file, the code you
are reviewing wins.

The consensus layer table and the severity ladder are in `trust-boundaries.md`
§9 and "Severity". This file does not repeat them.

---

## 1. What changes at the fork

**Fork constants (branch).** `src/cryptonote_config.h` sets
`HF_VERSION_FCMP_PLUS_PLUS` and `HF_VERSION_CARROT` to 17 and `MAX_HF_VERSION`
to 18. Other v17 rules ride the same fork (`HF_VERSION_REJECT_UNLOCK_TIME`,
`HF_VERSION_REJECT_LARGE_EXTRA`, `HF_VERSION_REJECT_MANY_MINER_OUTPUTS`,
`HF_VERSION_POW_COMMITMENT` and others). The mainnet v17 and v18 rows in
`src/hardforks/hardforks.cpp` are marked "Mock values for tests" and sit one
block after v16. Testnet and stagenet have no v17 row.

**Two forks (branch).** v17 is a transition. v18 is FCMP++ only.

| | v16 | v17 | v18 |
|---|---|---|---|
| RCT type | `RCTTypeBulletproofPlus` | BP+ with legacy outputs, or `RCTTypeFcmpPlusPlus` with Carrot outputs | `RCTTypeFcmpPlusPlus` |
| Non-coinbase outputs | `txout_to_tagged_key` | either | `txout_to_carrot_v1` |
| Coinbase outputs | `txout_to_tagged_key` | `txout_to_carrot_v1` | `txout_to_carrot_v1` |
| Ring size | 16 | 16, or 0 for FCMP++ | 0 |

Sources: `Blockchain::check_tx_outputs` ("from v17, allow FCMP++", "from v18,
allow only FCMP++"), `check_output_types` in `cryptonote_format_utils.cpp`, and
the mixin block in `Blockchain::check_tx_inputs`.

**New wire types (branch).**

- `rct::RCTTypeFcmpPlusPlus = 7` (`rctTypes.h`). It keeps BP+ and
  `p.pseudoOuts`, and adds prunable `reference_block` (varint), `n_tree_layers`
  (one byte) and `fcmp_pp`, a byte vector of length
  `fcmp_pp_proof_len(inputs, n_tree_layers)` with no length prefix.
- `txout_to_carrot_v1 {key, view_tag, encrypted_janus_anchor}`: 3-byte view
  tag, 16-byte encrypted anchor; amount and commitment stay in `rctSigBase`. It
  takes binary variant tag `0x1`, which master gives to `txout_to_scripthash`.
- `block` gains `fcmp_pp_n_tree_layers` and `fcmp_pp_tree_root`, serialized
  only when `major_version >= HF_VERSION_FCMP_PLUS_PLUS`.
- Inputs stay `txin_to_key`, with `amount == 0` and empty `key_offsets`.

**What replaces what (branch).**

- Rings and CLSAG go. One FCMP++ membership proof covers all inputs against the
  tree root at `reference_block`.
- Each input gets a spend-authorization-and-linkability (SA/L) proof over a
  re-randomized input tuple. It proves `O = xG + yT` and binds the key image
  `L = x·I`.
- The pseudo-out is the re-randomized commitment `C~`. The balance check still
  runs in C++ (`rct::verRctSemanticsSimple`).
- The signed message (`get_pre_mlsag_hash`) covers the prefix hash and
  `rctSigBase` only. Not the range proof, `reference_block` or `n_tree_layers`.

**Key image generator (branch).** `crypto::derive_key_image_generator(pub,
biased, I)` chooses the hash-to-point by **output type**:
`fcmp_pp::use_biased_hash_to_point` is true for `LegacyOutputPair` (the old
map, so old outputs keep their key image) and false for `CarrotOutputPairV1`.
`output_to_tuple` (`curve_trees.cpp`) derives `I` from the **original** output
key, not the torsion-cleared one. Its comment explains: otherwise a torsioned
legacy output would have different key images before and after the fork.

**Cross-fork double spend (branch).** A ring signature always uses the biased
map, so a ring that referenced a Carrot output would give it a second key
image. `Blockchain::check_tx_inputs` rejects, from v17, any ring transaction
whose newest ring member is at or above the first FCMP++ height.

Questions:

- Which `HF_VERSION_*` gates each rule, and is each `>=`, `>` or `==`
  deliberate? v17 must accept both paths.
- Is the rule gated in parsing as well as validation where it needs to be?
  `block` branches on the fork; the RCT type branches on its tag.
- Do the mainnet heights still hold test values?
- Can a ring transaction reach a post-fork output by any path: alt chain, pool
  re-validation, a reorg across the fork height?

---

## 2. The curve tree is consensus state

Every node keeps a tree of every spendable output. Leaves are
`{O.x, O.y, I.x, I.y, C.x, C.y}`; layers alternate Selene and Helios points
with chunk widths 38 and 18 (`curve_trees.h`); `FCMP_PLUS_PLUS_MAX_LAYERS` is
12. Two honest nodes must hold the same root at every block, or the chain
splits.

### When an output enters (branch)

- `cryptonote::handle_fcmp_tree` (`blockchain.cpp`) runs after each block.
  Outputs with the default lock go into the tree through
  `BlockchainDB::advance_tree`; later ones wait in `locked_outputs`.
- The default last locked block is block + 9
  (`get_default_last_locked_block_index`, from
  `CRYPTONOTE_DEFAULT_TX_SPENDABLE_AGE`). The tree runs ahead of the chain: per
  the comment in `handle_fcmp_tree`, header `n+1` carries the root that spends
  outputs whose last locked block is `n + 9`.
- Coinbase outputs follow their `unlock_time` (height + 60) and never count as
  custom-timelocked (`is_custom_timelocked`).
- `get_last_locked_block_index` turns old time-based `unlock_time` values into
  heights with fixed mainnet v15 constants (`hf_v15_time`, `hf_v15_height`).
  These are consensus constants now.
- An output that cannot become a leaf is **skipped, not rejected**.
  `CurveTrees::outputs_to_leaves` catches any throw from `output_to_tuple` (bad
  encoding, or `O` or `C` equal to identity after torsion clearing) and leaves
  it out. It is unspendable after the fork.
- Legacy outputs have torsion cleared (`get_valid_torsion_cleared_point_vartime`).
  Carrot outputs skip that (`output_checked_for_torsion` is true) because
  consensus rejects torsion in Carrot `K_o` and `C` through
  `rct::verPointsForTorsion`, called from `ver_non_input_consensus` and
  `Blockchain::validate_miner_transaction`.
- A coinbase needs at least one output from the fork, and already from the
  first coinbase whose `unlock_time` reaches the fork height. The comment in
  `validate_miner_transaction` says this keeps every usable tree root unique.

### Storage, migration, reorgs (branch)

- New LMDB tables (`db_lmdb.cpp`): `locked_outputs`, `leaves`, `layers`,
  `tree_edges`, `tree_meta`, `timelocked_outputs`. DB `VERSION` goes from 5
  (master) to 6.
- `migrate_5_6` builds the tree from all existing outputs in two resumable
  steps, ending in `advance_tree` per block, so it shares the code above.
- `BlockchainLMDB::remove_block` calls `BlockchainDB::trim_block`, which trims
  to the previous block's `n_leaf_tuples` and puts trimmed outputs back in
  `locked_outputs`.
- `Blockchain::create_block_template` refuses alt-chain templates after the
  fork: the daemon builds no tree for alt chains. An alt block's header root is
  checked only when a reorg applies it.

### What a transaction references (branch)

`get_fcmp_tx_tree_root` (`blockchain.cpp`) requires `reference_block < height`,
`reference_block + 1 >=` the first FCMP++ height, and `n_tree_layers` equal to
the stored layer count at that block (commented "IMPORTANT!"; the proof size
depends on it). There is no maximum age. Weight uses a fixed 7 layers
(`get_fcmp_pp_transaction_weight_v1`, reasons in its comment).
`handle_block_to_main_chain` checks the header root and layer count against the
DB.

Questions:

- Does every node classify every historical output the same way (valid,
  cleared, skipped), including invalid points and coinbase outputs that never
  had a torsion check?
- Is leaf order fixed by the chain alone (`unified_id`), not by threads,
  hash-map order or batch boundaries?
- Do `get_valid_torsion_cleared_point_vartime` (daemon) and
  `get_valid_torsion_cleared_point_fast_vartime` (wallet `TreeCache`) accept the
  same points and return the same bytes?
- After popping N blocks and re-adding them, is every table byte-identical?
  Cover a layer boundary, an empty-growth block, the fork height, and outputs
  moving between `locked_outputs` and the tree.
- Is the migration result equal to a fresh sync, at any kill point?
- Can a Carrot output enter the tree without `verPointsForTorsion` having run?
  `ver_non_input_consensus` is skipped below the fast-sync height
  (`trust-boundaries.md` §9); `refutations.md` explains why the skip in
  `output_to_tuple` depends on that check.
- `reference_block` is outside the signed hash. What keeps a relayer from
  changing it, and so the txid, without breaking the proof? Does the PR keep
  tree roots unique per block?

---

## 3. Proof verification and the Rust boundary

### Who checks what (branch)

| Check | Where |
|---|---|
| Proof length; 1–128 inputs (`FCMP_PLUS_PLUS_MAX_INPUTS`); 1–12 layers | `serialize_rctsig_prunable`, `is_canonical_fcmp_plus_plus_layout`, `verRctSemanticsSimple` (C++) |
| ≤ 16 outputs; outputs strictly ascending by key | `is_canonical_fcmp_plus_plus_layout`, `check_transaction_output_pubkeys_order` (C++) |
| Balance, BP+ | `rct::verRctSemanticsSimple` (C++) |
| Key image domain, uniqueness, descending order, not spent | `core::check_tx_semantic`, `Blockchain::check_tx_inputs` (C++) |
| `reference_block`, `n_tree_layers` | `get_fcmp_tx_tree_root` (C++) |
| Expanded key images equal `vin` | `check_fcmp_pp_expanded_tx` (C++) |
| Membership and all SA/L proofs | `fcmp_pp_verify` in `fcmp_pp_rust/src/lib.rs` (Rust) |

Rust decodes key images and input points with `Ed25519::read_G`, which through
`dalek-ff-group` rejects non-canonical and torsioned points. The C++ checks run
first and must reject the same set, or the key image stored in the DB could
differ from the one the proof binds.

### FFI contracts (branch)

- `fcmp_pp_verify_input_new` trusts `proof_len`; it only `debug_assert`s it.
  Every caller must check the length first.
- It dereferences the tree-root pointer unchecked;
  `collect_fcmp_pp_tx_verify_input` checks the root is not null.
- Both Cargo profiles set `panic = "abort"` and `overflow-checks = true`. A
  panic or overflow reachable from a relayed transaction aborts every node it
  reaches. Look for `unwrap`, `expect`, indexing and length arithmetic.
- Batch weights come from `OsRng`. Honest proofs must pass whatever the draw.

### Batching, caching, cost (branch)

- `batch_ver_fcmp_pp_consensus` verifies a block's unverified FCMP++
  transactions together; `rct::batchVerifyFcmpPpProofs` spreads them over the
  thread pool by input count. One bad proof fails its batch.
- `make_input_verification_id(txid, tree_root, n_tree_layers)` marks a verified
  transaction; a matching ID skips re-verification. `tx_pool`'s
  `expect_invalid_tx_inputs` uses it to stop relaying transactions a reorg has
  invalidated.
- Cost grows with inputs and layers. Caps: 128 inputs,
  `FCMP_PLUS_PLUS_MAX_TX_WEIGHT` (178063). Fee follows weight, which assumes 7
  layers.

Questions:

- Can any transaction field reach Rust without a C++ length or range check?
  Count bytes at the largest legal input and layer counts.
- Is anything cached by txid alone? The txid does not cover the tree root.
- When a block's batch fails, is the verdict the same as verifying each proof
  alone?
- Is worst-case verification bounded per byte of fee? Can a peer make a node
  verify one expensive proof twice, with another `reference_block` or across a
  reorg?
- Does a `Cargo.lock` or monero-oxide `rev` bump come with matching changes to
  `fcmp++.h` and `src/crypto/generators.cpp` (`subsystems-crypto.md`)?

---

## 4. Carrot addressing and scanning

Carrot is the output format for FCMP++: `src/carrot_core` (protocol) and
`src/carrot_impl` (transaction glue, devices, serialization) on the branch,
using the `external/mx25519` submodule (`tevador/mx25519`) for X25519.

### The enote (branch)

On chain: `K_o`, view tag, encrypted anchor, `C_a` in `outPk`, an 8-byte
encrypted amount in `ecdhInfo`. X25519 ephemeral keys `D_e` go in `tx_extra`:
one shared key (one output, or two outputs with the same `D_e`), else one per
output (`store_carrot_ephemeral_pubkeys_to_extra`). `store_carrot_to_transaction_v1`
always writes an 8-byte encrypted payment ID. A transaction counts as Carrot by
its first output's type (`carrot::is_carrot_transaction_v1`); consensus makes
all outputs share one type. Most derivations are keyed Blake2b over a fixed
transcript (`hash_functions.cpp`, `transcript_fixed.h`, separators in
`carrot_core/config.h`). The exception is the enote ephemeral private key
`d_e`: unkeyed `H_n` over `anchor_norm`, input context, `K^j_s`, `K^j_v` and
`pid`. `make_carrot_enote_ephemeral_privkey` (`enote_utils.cpp`) passes
`nullptr` as the key to `derive_scalar`, and `hash_base` (`hash_functions.cpp`)
then uses key length 0. It cannot be keyed: the recipient recomputes `d_e` from
the decrypted anchor in the normal Janus check, so anyone who can decrypt
`anchor_norm` knows `d_e`, and its secrecy rests on the 16-byte `anchor_norm`.
Find the other unkeyed calls with `git grep -n 'derive_.*nullptr' -- src/carrot_core`.

### X25519 (branch)

- mx25519 does **not** clamp; its header says it differs from RFC 7748. Carrot
  calls `mx25519_scmul_base_unclamped` and `mx25519_scmul_key_unclamped`.
  Adding clamping, or swapping the library, changes every shared secret.
- It picks portable, ARM64, AMD64 or AMD64-MULX code at run time. All must give
  identical bytes. No consensus check uses X25519; the daemon uses it only to
  build a Carrot coinbase (`construct_miner_tx`). A mismatch hides funds; it
  does not split the chain.
- The sender rejects an address view key outside the prime-order subgroup
  (`try_make_carrot_shared_key_sender`, `verify_point_is_in_main_subgroup`)
  and uses no cofactor.
- The receiver computes `k_v · D_e` with no check on `D_e`
  (`try_make_carrot_shared_key_receiver`). Only the normal Janus check rejects
  a crafted `D_e`; the amount-commitment check does not. For a low-order `D_e`
  with `u = 0`, `s_sr = k_v · D_e` is zero for every wallet, so the sender
  knows `s^ctx_sr` and can make the view tag, the decrypted amount and `C_a`
  all match (`try_get_carrot_amount` is keyed only by `s^ctx_sr`).
  `verify_carrot_normal_janus_protection` recomputes `D_e'` from `d_e` and
  compares its bytes with `D_e`, which rejects the enote.

### What the scan checks (branch)

`try_scan_carrot_enote_external_receiver` (`scan.cpp`, helpers in
`scan_unsafe.cpp`): view tag; recover `K_s^j' = K_o - k_g^o G - k_t^o T`;
decrypt the amount and match `C_a` as PAYMENT or CHANGE; Janus check by
recomputing `D_e` from the anchor (with the payment ID, then with a null one),
else the special anchor keyed by `k_v`. The wallet then requires `K_s^j'` in
its subaddress map (`wallet/scanning_tools.cpp`). Internal enotes use the
view-balance secret and have no Janus check. Coinbase enotes go only to main
addresses, have `k_a = 1`, and take only the normal Janus check.

- **Burning bug.** The input context (`'R' || first key image`, or
  `'C' || height` for coinbase) feeds the view tag and shared secret, so one
  `K_o` cannot scan as spendable in two transactions. Strictly ascending `K_o`
  rules out duplicates within one. wallet2 also keeps its old duplicate-key
  handling ("check for burning bug").
- **Janus attack.** Mixing keys from two of the victim's addresses should fail
  the Janus check (spec §9.1.5; `janus_protection_*` in
  `tests/unit_tests/carrot_core.cpp`).
- **Payment IDs** are bound into `d_e`, so the Janus check confirms them. At
  most one integrated destination per transaction
  (`get_output_enote_proposals`).

### Keys and tiers

Spec §5, `carrot_core/account_secrets.cpp`:

| Secret | Can do |
|---|---|
| `s_ga` | make addresses; sees nothing on chain |
| `k_v` | see external payments and special self-sends; no internal enotes, no key images |
| `s_vb` + public `K_ps` | all of the above, internal enotes and key images |
| `k_ps` with `k_gi` | spend (`y` in SA/L) |

**Branch status.** wallet2 runs only the legacy hierarchy under Carrot:
`get_view_balance_secret_device` and `get_carrot_address_device` return empty
(`@TODO: Carrot`) and `get_spend_device` passes `(k_s, null)`, so it makes no
internal enotes. FCMP++/Carrot multisig throws "unimplemented". Address
prefixes are unchanged; an address is still two Ed25519 keys.

Questions:

- Does a change to a transcript, separator, integer width or byte order update
  `tests/unit_tests/carrot_convergence.cpp`? An unchanged vector after a format
  change means the test does not cover it.
- Is every point from the chain or `tx_extra` decoded by a function that
  rejects bad encodings, with the result checked?
- Does an enote that passes the view tag but fails the commitment or both Janus
  checks still get rejected?
- Do two self-sends sharing `D_e` still have different enote types (spec
  §7.8.4)? Same type gives the same `K_o`.
- When wallet2 adopts the new hierarchy, does each tier get only its own
  secrets? A view-only wallet must not hold `k_ps`.
- Around the fork, does the wallet scan legacy and Carrot outputs, and both
  hierarchies for a hybrid wallet (`get_all_main_address_spend_pubkeys`)?

---

## 5. Wallet tree sync and transaction building

### What the wallet keeps (branch)

`fcmp_pp::TreeCache` (`tree_cache.{h,cpp}`) holds paths for the wallet's own
outputs and the tree's last chunks, grown from downloaded blocks. On restore
from a height, `/get_blocks.bin` returns `init_tree_sync_data` (start block,
`n_leaf_tuples`, last path, locked outputs) and `TreeCache::init` starts from
it. `scan_tx` fetches paths with `/get_path_by_unified_id.bin`
(`wallet2::handle_needed_path_data`) and checks each with
`CurveTrees::audit_path`: the output is in the leaf chunk and each hash is in
the layer above.

### Building a transaction (branch)

In `wallet/tx_builder.cpp`, `reference_block` is the wallet tree's tip
(`n_synced_blocks() - 1`) and the root comes from `TreeCache::get_tree_root`.
The wallet runs `ver_non_input_consensus` and checks each SA/L proof before
returning. Re-randomization (`rerandomize_output`) and SA/L proving use
`OsRng`; hot/cold signing derives re-randomization scalars from a seed
(`wallet/hot_cold.cpp`, "Carrot Hot-cold rerandomization scalar").

### What a malicious daemon can still do

Decoy selection is gone. These remain:

- **Wrong tree.** Bad `init_tree_sync_data` or bad blocks give a root no honest
  node holds, and the spend fails. Does the wallet compare its root with the
  header's `fcmp_pp_tree_root`?
- **Ownership by query.** A path request by `unified_id` names an owned output.
  So would any new per-output RPC.
- **Timing.** `reference_block` records how far the wallet had synced. It is
  on chain for good.
- **Fee.** Still from daemon fee data (`trust-boundaries.md` §4).
- **Crash.** Every daemon-sized vector in tree data is untrusted.

Questions:

- Is daemon tree data checked against something the daemon cannot choose?
- Does a reorg below the wallet's tree tip restore its cache exactly?
- Is every new RPC bounded on the restricted port, like
  `MAX_RESTRICTED_PATHS_COUNT` (50)?
- Does a change to the `reference_block` choice keep it the same for all
  wallets in the same state?
- Does the PR send the daemon a key image, path or output ID it did not send
  before?

---

## 6. Checklist for any FCMP++/Carrot PR

1. **Fork gating.** Each new rule names its `HF_VERSION_*`; v16, v17, v18
   behave as in §1; parsing and validation agree.
2. **One key image per output.** Legacy: biased generator from the original
   key. Carrot: unbiased. No ring references a post-fork output.
3. **Tree determinism.** Same chain, same root, on every node, thread count and
   platform, through migration, sync and reorg.
4. **Leaf validity.** Torsion clearing, identity checks and skip rules match in
   daemon, migration and wallet.
5. **Reference binding.** `n_tree_layers` matches the DB at `reference_block`;
   proof size follows from `(inputs, n_tree_layers)` before Rust sees a byte.
6. **No reachable abort.** No Rust panic or overflow from transaction bytes; no
   C++ `assert` guarding transaction data.
7. **Cost.** Worst-case verification bounded by weight and fee; caches key on
   the root as well as the txid.
8. **Canonical encodings.** C++ and Rust accept the same key images and points
   (`trust-boundaries.md` §9).
9. **Carrot binding.** Input context, commitment and Janus checks gate every
   scan; `K_o` unique and torsion-free.
10. **Wallet trust.** Daemon data checked before use; no new request reveals
    owned outputs or key images.
11. **Tests.** Format changes update `carrot_convergence.cpp`; tree changes add
    a pop-and-replay test. Branch tests: `tests/unit_tests/curve_trees.cpp`,
    `tree_cache.cpp`, `fcmp_pp.cpp`, `carrot_*.cpp`, `wallet_scanning.cpp`,
    `wallet_tx_builder.cpp`.

**Rating.** Use `trust-boundaries.md` "Severity" with modifier 5 (staged code
is rated as it will run):

- Two key images for one output, a forged proof accepted, a skipped balance
  check: CRITICAL.
- Nodes disagreeing on tree content, root or a fork gate: CRITICAL.
- A Rust panic or a crash on a relayed FCMP++ transaction: CRITICAL.
- Verification cost out of line with weight: HIGH.
- A wallet crediting an output it cannot spend: CRITICAL if any sender can do
  it.
- A malicious daemon hiding funds or corrupting the wallet's tree: HIGH or
  MEDIUM, by effect.
- A leak written on chain, such as a `reference_block` fingerprint: HIGH
  (permanence raises it).
