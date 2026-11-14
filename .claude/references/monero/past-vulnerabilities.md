# Past vulnerabilities in Monero's node and wallet

> Nothing in this resource is intended to express any opinions for any audit firms. Please review their source documents for their own words. Summaries here may not fully cover the nuances of their opinions and observations.

Real bugs that shipped in `monero-project/monero`, and a few from adjacent
projects, written as incident history to match a pull request against. Each
entry gives the mechanism, where the guard lives today, and the diff shape
that would bring it back.

Written against master `3fd0f88c2` (2026-10-25). Every path and symbol was
confirmed on that commit. Files and symbols are named, never line numbers.
Where the tree disagrees with this file, the tree wins.

## How to use this file

Find the class the diff touches and read its "reintroduces this if it"
line. Three patterns recur:

- **The guard is on one path and not its sibling:** additional tx keys,
  Wallet API offline signing, the reserve-proof key-image check, the device
  path of `get_tx_key`. When a diff adds a path, confirm it has the old
  path's guard.
- **The guard runs after the work it guards:** the `grace_blocks` bound, the
  wallet storing an output before decoding it, mempool insertion before PoW.
- **The fix enumerated routes instead of stating the invariant:** the first
  tx-pubkey fix fell to a variant.

## Wallet accounting and `tx_extra` parsing

`tx_extra` and the encrypted amounts (`ecdhInfo`) are sender-authored.
Consensus does not require `tx_extra` fields to be unique or canonical and
never decodes `ecdhInfo`. The wallet decides what it received from both.

### Duplicate tx pubkey counts a deposit N times (2018, HackerOne #364904, #377592)

**Mechanism.** `wallet2::process_new_transaction` scans all outputs once per
tx pubkey in `tx_extra`, accumulating into `tx_money_got_in_outs` with no
"already counted" guard. Listing one pubkey N times credited N times in
`m_payments` (returned by `get_payments`, `get_bulk_payments`), which
exchanges credit from; `m_transfers` stayed correct. It was exploited
against a Monero fork's exchange after the public fix described the bug.

**Fix today.** See the next entry. The "received output ignored" branch in
`wallet2::process_new_transaction` (one-time key already in `m_pub_keys`)
subtracts the amount from `tx_money_got_in_outs`, so a duplicate reaching
it does not reach `m_payments`.

**A PR reintroduces this if it** adds a loop over a `tx_extra` field or key
source that credits an amount outside the per-output `output_found` guard;
moves `tx_money_got_in_outs` or the `m_payments` write so it no longer sees
the deduplicated result; or makes the "received output ignored" branch stop
subtracting.

### Bypass via additional (subaddress) tx pubkeys (2018, HackerOne #379049)

**Mechanism.** The first fix deduplicated primary pubkeys
(`public_keys_seen`); it does not appear to have included the
additional-pubkey array. A dummy primary key, additional keys equal to the
real key, then the real key matched outputs twice. Deduplicating additional
keys too broke honest sends of several outputs to one subaddress.

**Fix today.** Output-level deduplication: `wallet2::check_acc_out_precomp_once`
takes a flag from the `std::deque<bool> output_found` declared in
`wallet2::process_new_transaction` and refuses to recognise an output twice,
whichever key matched. Additional pubkeys are read only when `pk_index == 1`.
`wallet2::scan_output` also throws "Same output cannot be added twice" and
"Overflow in received amounts". Derivations are built inline when
`tx_cache_data.primary` is empty, otherwise by `wallet2::cache_tx_data`; both
feed the same `check_acc_out_precomp_once` calls.

**A PR reintroduces this if it** calls `check_acc_out_precomp` instead of
`check_acc_out_precomp_once` on a scanning path; re-declares `output_found`
inside the per-pubkey loop; reads additional pubkeys every iteration; adds a
key source (new `tx_extra` field, Carrot or FCMP++ ephemeral key, cached
derivation) that bypasses `output_found`; or lets `cache_tx_data` diverge
from the inline path.

### Wallet decoded amounts from RingCT data in coinbase transactions (2019)

**Mechanism.** Coinbase amounts are in the clear. For a coinbase output with
clear amount 0, `wallet2::scan_output` still called `tools::decodeRct` on the
miner-supplied `rct_signatures`, so a miner chose the amount the wallet
recorded. A third party described it publicly before release, so the patch
shipped at once (dev meeting 2019-03-03).

**Fix today.** `wallet2::scan_output` takes a `miner_tx` flag and skips
`tools::decodeRct` for coinbase; `wallet2::import_key_images` does the same.
From `HF_VERSION_REJECT_SIGS_IN_COINBASE`, `Blockchain::prevalidate_miner_transaction`
requires `rct_signatures.type == rct::RCTTypeNull` in v2 coinbase.

**A PR reintroduces this if it** decodes an amount for a coinbase output
from anything but `vout.amount`; drops the `miner_tx` argument on a scanning
path; or relaxes the `RCTTypeNull` rule (e.g. for a new coinbase format)
without a wallet-side equivalent.

### Malformed `ecdhInfo` makes the wallet unable to sweep (2019, HackerOne #506496)

**Mechanism.** A sender kept the commitment honest and put garbage in the
encrypted amount. `rct::decodeRct` threw; the `tools::decodeRct` wrapper in
`wallet2.cpp` caught it and returned 0, after `scan_output` had pushed the
output into `outs`. The stored 0-value coin made `sweep_all` fail in
`wallet2::get_outs` ("Daemon response did not include the requested real
output"). No funds lost; recoverable by rescan.

**Fix today.** `wallet2::scan_output` decodes first; if `money_transfered`
is 0 it logs "Invalid output amount, skipping", sets `tx_scan_info.error`
and returns before `outs.push_back(i)`. Honest 0-value outputs are dropped
too, on purpose.

**A PR reintroduces this if it** moves `outs.push_back(i)` or any write to
`tx_money_got_in_outs`, `m_transfers` or `m_pub_keys` above the decode;
weakens the zero return; or makes `tools::decodeRct` return a non-zero
fallback. Its `switch` has a `default:` that returns 0: a new `RCTType*` not
added there decodes every output as 0 and skips it. `wallet2::import_key_images`,
`wallet2::check_tx_key_helper_at` and `wallet2::check_reserve_proof` also call
`tools::decodeRct`; a contract change must cover every caller.

## Deserialization and allocation

### Exabyte allocation in `portable_storage` binary load (2019, HackerOne #506498)

**Mechanism.** epee's binary reader called `reserve()` with an array count
from a varint. A few bytes asked for about 4 EB, over Levin, so over P2P.

**Fix today.** `throwable_buffer_reader::read_ae` in
`contrib/epee/include/storages/portable_storage_from_bin.h` checks
`size <= m_count / ps_min_bytes<type_name>::strict` before `reserve`, then
`max_objects` and `max_strings` from a `portable_storage::limits_t`. Levin
passes `default_levin_limits` (`levin_abstract_invoke2.h`), the HTTP binary
client `default_http_bin_limits` (`http_abstract_invoke.h`); without a
`limits_t` those caps are unlimited. `EPEE_PORTABLE_STORAGE_RECURSION_LIMIT_INTERNAL`
caps nesting.

**A PR reintroduces this if it** adds a `reserve`, `resize` or `new[]` sized
by a decoded count without the bytes-remaining check; lowers a
`ps_min_bytes` value; or calls `load_from_binary` / `load_t_from_binary` on
untrusted bytes with no `limits_t`.

### Signed `char` as an array index in the JSON parser (2020, HackerOne #825091)

**Mechanism.** The epee JSON string parser looked up hex digits with
`isx[(int)*++it]`; a byte above 0x7F read before the table. Found by
fuzzing; reachable from any JSON RPC body.

**Fix today.** `match_string2` in `contrib/epee/src/parserse_base_utils.cpp`
indexes `isx[(unsigned char)*++it]`; other lookups in that file cast to
`uint8_t` or `unsigned char` first.

**A PR reintroduces this if it** indexes a table with a `char`, or an `int`
derived from one, in a parser. Grep the diff for `[*it]`, `[c]`, `[(int)`.

### Stack VLA sized by the block's transaction count (2019, HackerOne #519120)

**Mechanism.** `tree_hash` allocated `char ints[cnt][HASH_SIZE]` on the
stack with `cnt` from a block's `tx_hashes`; a large count overflowed it.

**Fix today.** `tree_hash` in `src/crypto/tree-hash.c` uses `calloc`.
`tree_hash_cnt` asserts `count <= 0x10000000`, but asserts vanish in
release. The `block` serializer (`BEGIN_SERIALIZE_OBJECT` in
`src/cryptonote_basic/cryptonote_basic.h`) fails only when
`tx_hashes.size() > CRYPTONOTE_MAX_TX_PER_BLOCK` (`0x10000000`), so it
admits 2^28 hashes; `get_tx_tree_hash(const block&)`
(`cryptonote_format_utils.cpp`) pushes the miner tx hash first, so
`tree_hash` can be handed 2^28 + 1 leaves, one past `tree_hash_cnt`'s
bound. What actually keeps such counts out is the transport limits:
Levin's `LEVIN_DEFAULT_MAX_PACKET_SIZE` and RPC's `MAX_RPC_CONTENT_LENGTH`.
Check the constant with `git grep -n 'define CRYPTONOTE_MAX_TX_PER_BLOCK' -- src`.

**A PR reintroduces this if it** adds a VLA or `alloca` sized by a decoded
count; raises `CRYPTONOTE_MAX_TX_PER_BLOCK` past what `tree_hash_cnt`
handles; or adds a hash-list type whose serializer lacks the count check
and feeds `tree_hash`.

### Crafted cold-wallet files (dev meeting 2017-07-23)

Boost-serialized wallet files could crash the loader, and cold-signing
files used that format. Today `wallet2::parse_unsigned_tx_from_str` refuses
versions `'\003'` and `'\004'` as deprecated; `'\005'` is decrypted, read
with `binary_archive` and checked by `wallet::sanity_check_unsigned_tx_set`.
**A PR reintroduces this if it** re-enables a boost-archive format for
files that cross a trust boundary, or skips the sanity check on a new
import path.

## RPC resource exhaustion

Public nodes expose RPC through `--restricted-rpc` or
`--rpc-restricted-bind-port`. For some entries the restricted gate is the
whole fix; where the method is public, only a bound helps.

### `get_random_rct_outs.bin` loop (2018, HackerOne #391611)

**Mechanism.** An unbounded `outs_count` drove a rejection-sampling loop
that ran until it had that many distinct outputs, holding the blockchain
lock. **Fix today.** The method is gone; decoy selection is in the wallet.

**A PR reintroduces this if it** adds a daemon method that samples until it
has N distinct items with N from the request. Ask whether N can be
unreachable and whether the loop holds `m_blockchain_lock`.

### `get_output_distribution` with many amounts (2021, HackerOne #1379707)

**Mechanism.** A long `amounts` list built one distribution per amount and
exhausted memory in about 90 seconds.

**Fix today.** On a restricted connection, `on_get_output_distribution` and
`on_get_output_distribution_bin` in `src/rpc/core_rpc_server.cpp` reject
`req.amounts != std::vector<uint64_t>(1, 0)`; the ZMQ handler
`DaemonHandler::handle(const GetOutputDistribution::Request&, ...)` in
`src/rpc/daemon_handler.cpp` repeats it. Unrestricted clients have no cap.

**A PR reintroduces this if it** adds a transport or handler for this call
without the restricted check; relaxes "rct only"; or adds a list field to a
restricted method without a cap like `RESTRICTED_TRANSACTIONS_COUNT`,
`RESTRICTED_SPENT_KEY_IMAGES_COUNT`, `RESTRICTED_BLOCK_COUNT` or
`MAX_RESTRICTED_GLOBAL_FAKE_OUTS_COUNT` (top of `core_rpc_server.cpp`).

### Zero TCP window queues responses until OOM: CVE-2025-26819 (2024, HackerOne #2912194)

**Mechanism.** A client that never reads leaves responses in the epee send
queue, which capped messages, not bytes: 1000 queued 17 MB responses came
to 17 GB, through restricted ports. It was exploited against public nodes
after the fix PR's title described the bug.

**Fix today.** `connection<T>::send` in
`contrib/epee/include/net/abstract_tcp_server2.inl` runs `check_send_queue`
before queueing and terminates the connection past
`ABSTRACT_SERVER_SEND_QUE_MAX_COUNT` messages or `response_soft_limit`
bytes. RPC sets that from `--rpc-response-soft-limit`
(`core_rpc_server::arg_rpc_response_soft_limit`, default
`DEFAULT_RPC_SOFT_LIMIT_SIZE`); P2P uses
`ABSTRACT_SERVER_SEND_QUE_MAX_BYTES_DEFAULT`. Per-IP caps come from
`--rpc-max-connections-per-public-ip` and its private-IP sibling.

**A PR reintroduces this if it** appends to the write queue without
`check_send_queue`; counts messages but not bytes; adds a per-request
buffer in a new transport or the HTTP handler; or raises defaults without
saying why.

### `get_fee_estimate` with a huge `grace_blocks` (2024, HackerOne #2338094)

**Mechanism.** `Blockchain::get_dynamic_base_fee_estimate_2021_scaling` ran
`for (i < grace_blocks) rm.insert(0)` before its `grace_blocks <= 100`
check, so `2^64-1` pinned an RPC thread, with an unsigned
`100 - grace_blocks` underflow behind it. Public on restricted RPC.

**Fix today.** The function's first check, before any loop, is
`CHECK_AND_ASSERT_THROW_MES(grace_blocks <= CRYPTONOTE_REWARD_BLOCKS_WINDOW, ...)`.
The handler is `core_rpc_server::on_get_base_fee_estimate`.

**A PR reintroduces this if it** moves that check below work that scales
with `grace_blocks`; uses a new request field as a loop bound or in
`size - field` without a bound at the top; or computes
`CRYPTONOTE_REWARD_BLOCKS_WINDOW - grace_blocks` where the check does not
dominate.

### Unbounded leading CRLFs spin the HTTP handler (2018, HackerOne #344499)

**Mechanism.** The epee HTTP handler erased leading CR/LF with no cap.
**Fix today.** `simple_http_connection_handler::handle_buff_in` in
`contrib/epee/include/net/http_protocol_handler.inl` counts them in
`m_newlines` and fails past `HTTP_MAX_STARTING_NEWLINES`;
`HTTP_MAX_URI_LEN` and `HTTP_MAX_HEADER_LEN` cap the other pre-parse loops.

**A PR reintroduces this if it** adds a "skip until X" loop over request
bytes without a count cap, or resets `m_newlines` other than at the start
of a new request.

### TCP RST stops the accept loop (2018, HackerOne #363714)

**Mechanism.** On error, `handle_accept` returned without calling
`async_accept` again; a reset right after the handshake stopped the node
accepting connections. **Fix today.** `boosted_tcp_server::handle_accept`
in `abstract_tcp_server2.inl` falls through to an error path that re-arms
`async_accept` after an error code or a caught exception.

**A PR reintroduces this if it** adds an early `return` to an accept, read
or write completion handler without re-registering it.

## P2P and consensus

Every node is exposed on P2P. A P2P bug needs no misconfiguration.

### `GET_OBJECTS` fills the send queue and sleeps a worker (2020, HackerOne #876530)

**Mechanism.** A peer requested many 500-block batches. On a full send
queue the worker slept about six seconds; filling every worker stalled the
node. Requests were served before the handshake.

**Fix today.** `handle_request_get_objects` in
`src/cryptonote_protocol/cryptonote_protocol_handler.inl` drops a connection
in `state_before_handshake` and rejects requests above
`CURRENCY_PROTOCOL_MAX_OBJECT_REQUEST_COUNT` (100). `connection<T>::send`
terminates the connection on a full queue instead of parking a worker.

**A PR reintroduces this if it** serves a new request type without the
`state_before_handshake` check; raises
`CURRENCY_PROTOCOL_MAX_OBJECT_REQUEST_COUNT`; or adds a `sleep` or blocking
wait on an `io_context` worker that depends on peer behaviour.

### Pending block queue filled past its limit (2024, HackerOne #2693786)

**Mechanism.** Sync skipped the block-queue size cap when the next block was
near the tip, and queued blocks without checking they chained to what it
asked for, so orphans whose parent was "still downloading" never left. A
cross-connection record of requested hashes let one peer corrupt another's
view. The reporter reached about 54 GB and noted a bad batch could also
stop sync, enabling a chain split. Interim fixes fell to multi-connection
variants.

**Fix today.** Per-connection state: `cryptonote_connection_context`
(`src/cryptonote_basic/connection_context.h`) keeps `m_expected_heights`
and answers `get_expected_hash`. `handle_response_get_objects` drops the
peer unless each block's hash matches the expected hash for its height, the
first `prev_id` matches the expected hash below it, and each later
`prev_id` equals the previous block's hash. In `request_missing_objects`,
`queue_proceed_init` applies `BLOCK_QUEUE_SIZE_THRESHOLD` (or
`--block-download-max-size`); the `stripe_proceed_main` override applies
only when `next_needed_height == bc_height`.

**A PR reintroduces this if it** downloads while ignoring
`queue_proceed_init`; widens the `stripe_proceed_main` override; stores
blocks before the `get_expected_hash` and `prev_id` checks; or moves
per-peer sync state into a structure shared across connections.

### Transactions from invalid blocks stay in the mempool (2024, HackerOne #2315026)

**Mechanism.** Block transactions entered the pool as `relay_method::block`,
for which `tx_memory_pool::add_tx` skips the fee, `MAX_TX_EXTRA_SIZE` and
unlock-time rules and keeps a transaction whose input check fails, and
`tx_memory_pool::prune` never evicts it; only `remove_stale` does, after
`CRYPTONOTE_MEMPOOL_TX_FROM_ALT_BLOCK_LIVETIME` (a week). PoW was checked
after insertion, so a block without valid PoW could plant a week of junk.

**Fix today.** Block transactions travel in a `pool_supplement`
(`src/cryptonote_core/tx_verification_utils.h`).
`Blockchain::handle_block_to_main_chain` takes them after
`ver_non_input_consensus`. `Blockchain::handle_alternative_block` adds them
to the pool with `relay_method::block` only after the PoW check and
`ver_non_input_consensus` ("Now that we have the PoW verification out of the
way"). The other `relay_method::block` callers put back transactions the
node already held: `Blockchain::pop_block_from_blockchain` (popped blocks)
and the `return_txs_to_pool` lambda in `Blockchain::handle_block_to_main_chain`
(only transactions it took from the pool).

**A PR reintroduces this if it** calls `add_tx` with `relay_method::block`
(or sets `kept_by_block`) before PoW; moves the supplement-to-pool loop
above the PoW check; or lets `prune` keep a new category forever.

### Inverted ternary in `peerlist_manager::filter` (2026, HackerOne #3547349)

**Mechanism.** `filter(white, f)` selected the gray list when asked for the
white list and the reverse. Host-level deduplication in
`make_new_connection_from_peerlist` limited the impact.

**Fix today.** `peerlist_manager::filter` in `src/p2p/net_peerlist.h` reads
`white ? m_peers_white : m_peers_gray`, matching `foreach`. Its caller
`node_server::block_subnet` (`src/p2p/net_node.inl`) runs it on both lists.

**A PR reintroduces this if it** adds a white-or-gray selector without a
test of both branches, or removes the host deduplication in
`make_new_connection_from_peerlist`.

### RandomX seed for alternative chains (dev meeting 2019-09-08)

Found on testnet before activation: an alt chain across a seed epoch
boundary needs its own seed hash, and an attacker can build one. Today `Blockchain::handle_alternative_block`
takes the seed from the alt chain when `alt_chain.front().height <= seedheight`
(the `prev_id` of the block at `seedheight+1`) and calls
`get_altblock_longhash`; a reorg resets it with `rx_set_main_seedhash`.
**A PR reintroduces this if it** verifies alt-block PoW with the main
chain's seed, or changes seed-height logic on one path only.

### Selfish mining by Qubic (2025)

Lee and Kim measured Qubic's campaign: about 22% of blocks, 28% in ten
detected periods, with more orphans and longer forks. At the inferred
tie-break parameter (`gamma` about 0) it earned less than honest mining.
`Blockchain::handle_alternative_block` reorganizes only when
`main_chain_cumulative_difficulty < bei.cumulative_difficulty`, so ties keep
the first-seen chain. **Review question:** a change to fork choice, relay
speed or tie-breaking moves `gamma` and the selfish-mining threshold, and
needs a consensus-level argument.

## Key-image domain

Ed25519 has cofactor 8. A valid key image `I` is in the prime-order
subgroup; `I + T`, for a torsion point `T`, is different bytes.

### Torsioned key images allowed up to 8 spends per output (2017)

**Mechanism.** Verifiers did not check the subgroup, so adding a torsion
point gave a fresh key image: up to eight spends per output. Patched
quietly; no exploitation seen.

**Fix today.** `core::check_tx_inputs_keyimages_domain` in
`src/cryptonote_core/cryptonote_core.cpp` rejects the identity and any key
image with `l * I != identity`; `core::check_tx_semantic` calls it, and
`ver_non_input_consensus` reaches it on the pool and block paths.
`verRctCLSAGSimple` (`src/ringct/rctSigs.cpp`) rejects only
`sig.I == rct::identity()`, so CLSAG depends on the caller.
`crypto_ops::check_ring_signature` (`src/crypto/crypto.cpp`) rejects the
identity and torsioned key images itself; it also verifies v1 consensus
ring signatures (`tx_verification_utils.cpp`).

**A PR reintroduces this if it** adds an input type, verifier or block path
that accepts a key image without reaching `check_tx_inputs_keyimages_domain`
or an equivalent check. A change to `crypto_ops::check_ring_signature`
changes consensus for historical v1 transactions.

### Reserve proof accepted a torsion-shifted key image (2026, zkao)

**Mechanism.** `wallet2::check_reserve_proof` verified a one-member ring
signature per key image, then asked `/is_key_image_spent` about those bytes.
A prover submitted `I + T` for a spent output with an even challenge; the
signature verified, the daemon answered "unspent", and the output counted
in `total`. Reachable through `wallet_rpc_server::on_check_reserve_proof`,
`simple_wallet::check_reserve_proof` and `WalletImpl::checkReserveProof`.

**Fix today.** `wallet2::check_reserve_proof` rejects a key image that is
the identity or fails `rct::isInMainSubgroup`, alongside its duplicate
key-image and duplicate-output checks. The `check_ring_signature` change
also covers `wallet2::check_spend_proof`. `wallet2::import_key_images` and
the multisig partial key-image import already checked.

MProve (2019), a private reserve-proof design, also looks up published key
images; an implementation needs the same check first. It notes that
revealed key images make later spends from those outputs traceable.

**A PR reintroduces this if it** accepts a caller-supplied key image (new
proof type, import format, watch-only sync path) and uses its bytes as a
lookup key without the subgroup check. The tree spells the check both
`rct::isInMainSubgroup` and `rct::scalarmultKey(x, rct::curveOrder()) == rct::identity()`.

## Daemon trust and privacy

A remote daemon is untrusted unless the user says otherwise
(`wallet2::is_trusted_daemon`). Anything keyed by the wallet's own
transactions or outputs is a leak.

### `find_and_save_rings` sent outgoing txids to the daemon (2025)

**Mechanism.** `wallet2::find_and_save_rings` back-filled the ring database
by fetching the wallet's outgoing transactions with `/gettransactions`,
with no trusted-daemon check. `wallet2::load` called it whenever the cached
`m_ring_history_saved` was false, e.g. after a restore refreshed and closed
without saving. Affected v0.12.0.0 through v0.18.4.1.

**Fix today.** `wallet2::find_and_save_rings` is `[[deprecated]]` and makes
no request: with `force` it warns and returns false, otherwise it sets
`m_ring_history_saved`. Nothing in `src` calls it.

**A PR reintroduces this if it** sends the wallet's own txids, key images or
output indices to the daemon on load, refresh or any unprompted path
without gating on `is_trusted_daemon()`, or revives the back-fill. Cached
flags that default to "not done yet" decide what runs on the next load.

### Daemon that hides the real output (context for #506496)

`wallet2::get_outs` throws "Daemon response did not include the requested
real output" unless the answer carries the real output's key, mask and
`unlocked` flag; `wallet2::tx_add_fake_output` drops decoys whose key or
mask fails `rct::isInMainSubgroup`. **A PR reintroduces the weakness if it**
loosens either check or builds a ring from daemon data without comparing
the real member to the wallet's record.

## Decoy selection

### Decoys could never be exactly 10 blocks old (2023)

**Mechanism.** The gamma picker excluded the last 10 blocks, so the newest
decoy was 11 blocks old while the wallet spent its own 10-block-old outputs:
a 10-block-old ring member was the real spend. Affected v0.13.0.2 through
v0.18.2.1. Found while fixing an infinite loop in decoy selection.

**Fix today.** `gamma_picker::gamma_picker` in `wallet2.cpp` sets
`end = rct_offsets.data() + rct_offsets.size() - (std::max(1, CRYPTONOTE_DEFAULT_TX_SPENDABLE_AGE) - 1)`.
Spendability is `wallet2::is_transfer_unlocked`, also driven by
`CRYPTONOTE_DEFAULT_TX_SPENDABLE_AGE` (10). `TEST(select_outputs, exact_unlock_block)`
and `exact_unlock_block_tiny` (`tests/unit_tests/output_selection.cpp`)
pin the boundary.

**A PR reintroduces this if it** changes `end`, `DEFAULT_UNLOCK_TIME`,
`RECENT_SPEND_WINDOW` or the spendable age on one side only, or changes the
picker without those tests. Invariant: the ages the wallet can spend equal
the ages the picker can pick.

## Wallet host and local security

The attacker is another user or process on the same machine.

### Server impersonation of `monero-wallet-rpc` (2018, HackerOne #462442)

**Mechanism.** HTTP digest authentication proves the client, not the server.
A local user who bound the port first received the victim's client traffic
and could answer it. **Fix today.** Optional TLS with pinned certificates:
`--rpc-ssl` and `--rpc-ssl-allowed-fingerprints` (`src/rpc/rpc_args.cpp`),
`--daemon-ssl-allowed-fingerprints` (`wallet2.cpp`) on the client.

**A PR reintroduces this if it** weakens fingerprint pinning, or treats
"localhost" as proof of the server's identity in a new client.

### Credentials file created without `O_EXCL` (2024, HackerOne #2425873)

**Mechanism.** `tools::private_file::create` opened
`monero-wallet-rpc.<port>.login` with `O_RDONLY|O_CREAT` and no `O_EXCL`; a
local user who pre-created the name kept ownership and read the password.
An interim remove-then-open fix only narrowed the race.

**Fix today.** `wallet_rpc_server` uses `tools::private_file::drop_and_recreate`
(`src/common/util.cpp`), which removes any existing file and calls
`private_file::create` with `O_EXCL` on POSIX (`CREATE_NEW` on Windows).

**A PR reintroduces this if it** creates a secret-holding file without
`O_EXCL`, or with `open`/`fopen` and a predictable name in a shared
directory, or with check-then-create.

### Password change accepted a mismatched confirmation (2020, HackerOne #803028)

In monero-gui, a blank confirmation still changed the password, risking
self-lockout. The CLI's `simple_wallet::change_password` prompts through
`default_password_prompter(true)`, which verifies. **A PR reintroduces
this if it** adds a password-setting path that does not compare the
confirmation before the irreversible change.

### Multisig behind an experimental gate (dev meetings 2022)

Multisig signature and key-exchange weaknesses were fixed in 2022 (PRs
#8149, #8220). With review incomplete, maintainers chose an opt-in setting.
Today `CHECK_MULTISIG_ENABLED()` in `simplewallet.cpp` and
`wallet_rpc_server.cpp` refuses multisig operations unless
`wallet2::is_multisig_enabled()` (`set enable-multisig-experimental 1`).
The Wallet API (`src/wallet/api/`) does not reference `is_multisig_enabled`.
**A PR reintroduces the exposure if it** adds a multisig entry point without
`CHECK_MULTISIG_ENABLED()`, or defaults the setting on.

## Hardware wallets

Monero's model: the host is hostile; the device holds the spend key and
shows what is signed. Host code is under `src/device/` and
`src/device_trezor/`.

### Device signed an `unlock_time` it never showed (2020, HackerOne #817245)

**Mechanism.** Devices did not verify the transaction's `unlock_time`; host
malware could lock approved funds for good. The fixes were device-side. A
first Ledger patch had an integer overflow on large values (Ledger LSB-009).

**A PR reintroduces this if it** adds a prefix field, or changes how the
prefix is streamed to the device (Ledger: `device_ledger::mlsag_prehash`),
without a device change that displays or checks it.

### Ledger app returned its Keccak state, which contained both secret keys (2026, Ledger LSB-022)

**Mechanism.** The app's `INS_GET_CHACHA8_PREKEY` handler permuted
`a || b || 0x8c` and returned the 200-byte Keccak-f state, not a digest.
The permutation is public and the input fit one block, so inverting it gave
both keys, with no confirmation. Found in Ledger's internal review; app
2.1.4 squeezes SHAKE256 over a domain-separated view key only.

**Host side today.** `device_ledger::generate_chacha_key`
(`src/device/device_ledger.cpp`) sends `INS_GET_CHACHA8_PREKEY`, copies 200
bytes and passes them to `crypto::generate_chacha_key_prehashed`
(`src/crypto/chacha.h`), which treats them as a Keccak state for
`cn_slow_hash_prehashed`. The host protocol asks for a sponge-shaped value.

**A PR reintroduces this if it** adds a device command that returns an
intermediate hash state or spend-key-derived value without on-device
confirmation, or needs the device to export more than a final digest.

### Wallet API offline signing accepted hardware wallets (2026, zkao)

**Mechanism.** `device_ledger::generate_output_ephemeral_keys` accepts the
device's output key and amount key with length checks only; the comparisons
are under `#ifdef DEBUG_HWDEVICE`. The key reaches `tx.vout` through
`construct_tx_with_tx_key`. `simple_wallet::sign_transfer` and
`wallet_rpc_server::on_sign_transfer` refused hardware wallets for offline
signing; the Wallet API path (`WalletImpl::loadUnsignedTx`,
`UnsignedTransactionImpl::sign`, `wallet2::sign_tx`) did not, so a
compromised device could redirect funds there.

**Fix today.** `UnsignedTransactionImpl::sign`
(`src/wallet/api/unsigned_transaction.cpp`) returns "Command not supported
by hardware wallet" when `key_on_device()`; the GUI disabled the button. The
release-build device-response acceptance is unchanged.

**A PR reintroduces this if it** adds an entry point that signs an unsigned
set without a `key_on_device()` refusal. Grep both strings ("command not
supported by HW wallet", "Command not supported by hardware wallet") and
`key_on_device()` to list entry points.

### Trezor host trusts device responses (2026, zkao)

Both reports assume a compromised Trezor, which in Monero's model already
holds the spend key; they show where the host does not cross-check.

- **Signing intent.** `Signer::step_set_input_ack`, `step_set_output_ack`,
  `step_all_outs_set_ack` and `step_final_ack` in
  `src/device_trezor/trezor/protocol.cpp` install device-returned inputs,
  outputs, fee, `extra` and CLSAGs after deserialization; the prefix and
  pre-MLSAG hash checks recompute over those same values.
  `device_trezor::transaction_check` does not compare outputs to the
  requested destinations.
- **Tx-key recovery.** `protocol::tx::get_tx_key_ack` accepts any
  32-byte-aligned decrypted plaintext as keys; `wallet2::get_tx_key` rejects
  only an empty list or a null first key, unlike `wallet2::set_tx_key`, which
  checks a user key against the chain's tx pubkey. Separately, and without
  any device, `wallet_rpc_server::on_get_tx_key` uses
  `CHECK_IF_BACKGROUND_SYNCING()`, not `CHECK_IF_RESTRICTED_BACKGROUND_SYNCING()`,
  so it answers under `--restricted-rpc`, documented as view-only.

**A PR reintroduces or widens this if it** adds a wallet RPC that returns
secret material without the restricted check; accepts device-returned
secrets or outputs on a new path without the consistency check the
user-supplied path has; or treats device-made HMACs or hashes as proof of
host intent.

## Adjacent: P2Pool (separate repository)

P2Pool's maintainer reference (v4.18, HARDFORKS chapter) lists its
disclosed bugs. The shapes apply to any consensus or P2P code:

- Reused coinbase tx keys burned outputs (now deterministic, verifiable keys).
- Shares sorted by spend key only: a copied spend key with another view key
  made the order undefined, splitting the chain (now both keys).
- "Seen" keyed on template id, which ignores the nonce: an attacker raced a
  share and got honest relayers banned (now a full id).
- Varints and output amounts that did not round-trip: a valid block
  re-encoded invalid and its relayer was banned.
- An all-zero merkle root with an empty proof let one PoW back thousands of
  shares (now a real proof check and an uncle cap).
- Miner timestamps overflowed difficulty or inflated a slow-mined chain
  (now 64-bit math and checks against referenced Monero blocks).
- Crypto ran before a cheap low-difficulty reject; unkeyed hashing of peer
  data let colliding keys crash tables (now keyed SipHash); an early
  `return` halted chain-wide depth updates.

**Ask of a monerod diff:** does it key a set on a non-unique id, sort by part
of an identity, accept a non-canonical encoding, do arithmetic on a miner
timestamp, or do expensive work before a cheap reject?

## The fuzzing audit's scope (2025, Ada Logics)

Ada Logics built an in-process libFuzzer RPC harness (on master in
`tests/fuzz/fuzz_rpc/`) and an end-to-end HTTP harness against an ASan
`monerod`. It reached about 89% of functions in `core_rpc_server.cpp` and
found two issues, reported privately. Areas it does not appear to have
included:

- The HTTP transport (`http_protocol_handler.inl`, `abstract_tcp_server2.inl`),
  where #344499, #363714 and CVE-2025-26819 lived; only the end-to-end
  harness reaches it, and that is not on OSS-Fuzz.
- `on_get_peer_list`, `on_set_bans` (no peers) and handlers that hung
  (moved to a build with `SAFE` undefined). Bootstrap forwarding and RPC
  payments were also unreached; both are gone from master.
- Wallet scanning and P2P sync. `tests/fuzz/` covers parsers (`tx-extra.cpp`,
  `levin.cpp`, `load_from_binary.cpp`, `load_from_json.cpp`), not the logic
  where #379049, #506496 and #2693786 lived.

For a transport, P2P-sync or wallet-scanning change, ask for a targeted test.

## A note on disclosure

The 2018 tx-pubkey fix, the 2019 coinbase fix and CVE-2025-26819 were each
exploited or published early after a public commit, PR title or post
described the bug. A review comment on a public PR is public. Report
anything exploitable privately, not in the PR thread.

## Summary table

| Class | Guard | Regression shape |
|---|---|---|
| Duplicate keys | `check_acc_out_precomp_once`, `output_found` | key source or scan path skipping `output_found` |
| Coinbase amounts | `miner_tx` in `scan_output`; `RCTTypeNull` rule | coinbase amount from RingCT data |
| Bad `ecdhInfo` | zero check in `scan_output`; `tools::decodeRct` | state written before decode; new `RCTType*` |
| Binary storage | `read_ae`, `ps_min_bytes`, `limits_t` | `reserve` from a count; load without limits |
| Parsers | `match_string2`; `CRYPTONOTE_MAX_TX_PER_BLOCK`; `sanity_check_unsigned_tx_set` | signed `char` index; VLA by input; boost archive |
| RPC lists and loops | `RESTRICTED_*` caps; top-of-function bounds | new handler without cap; bound after work |
| Send queue | `check_send_queue`, `response_soft_limit` | counts messages, not bytes |
| HTTP / accept | `HTTP_MAX_*`; `handle_accept` error path | uncapped skip loop; return without re-arm |
| P2P requests | `state_before_handshake`, request count cap | pre-handshake service; worker sleep |
| Block download | `get_expected_hash`, `prev_id`, `queue_proceed_init` | cap bypass; shared per-peer state |
| Mempool from blocks | `pool_supplement`; PoW before insert | `relay_method::block` before PoW |
| Peer lists | `filter` vs `foreach` | untested selector |
| Alt chains, fork choice | alt seed in `handle_alternative_block`; strict `<` | main seed for alt blocks; tie-break change |
| Key images | `check_tx_inputs_keyimages_domain`; `check_reserve_proof` | key image used without subgroup check |
| Daemon | `is_trusted_daemon`; `get_outs` real-output check | request keyed by own txids; unchecked ring |
| Decoys | `gamma_picker` `end`; spendable age | windows changed separately |
| Local host | `drop_and_recreate`; SSL fingerprints; confirmation prompt | no `O_EXCL`; localhost as identity |
| Multisig | `CHECK_MULTISIG_ENABLED()` | entry point without gate |
| Hardware wallets | `key_on_device()` refusals; `INS_GET_CHACHA8_PREKEY` | signing path without refusal; trusting device data |
| Restricted wallet RPC | `CHECK_IF_RESTRICTED_BACKGROUND_SYNCING()` | secret returned under `--restricted-rpc` |
