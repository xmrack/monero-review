# Node subsystems

Directory-by-directory for everything `monerod` is made of. For each: what it
owns, the files that carry it, the invariants a change must preserve, and the
traps — the things that make a competent reader draw the wrong conclusion.

Wallet subsystems are in `subsystems-wallet.md`; crypto in
`subsystems-crypto.md`; the end-to-end paths through all of these are in
`flows.md`.

Verified against master `3d3920d7`. Symbols confirmed by grep; line numbers
only where the code is genuinely hard to find without one.

---

## `contrib/epee/include/storages/` — portable_storage, the wire DOM

Every P2P payload and every RPC request and response passes through here. It
is a `boost::variant` DOM with hand-written binary and JSON back ends, driven
by the `KV_SERIALIZE` macro family.

**Files.** `portable_storage_base.h` is the object model (`section` is just a
`std::map<std::string, storage_entry>`); `portable_storage_from_bin.h` is the
binary parser — header-only, ~369 lines, and the primary untrusted-input
surface; `portable_storage_from_json.h` is a hand-rolled JSON parser (**not**
rapidjson); `portable_storage_val_converters.h` range-checks every scalar
conversion; `portable_storage_template_helper.h` is the public façade
(`load_t_from_binary`, `load_t_from_json`, …).

**Where bounds live.** All of them are in `throwable_buffer_reader`, and all
throw rather than return:

- `read(void*, count)` — refuses to read past the remaining input.
- `read_ae<T>()` — `size <= m_count / ps_min_bytes<T>::strict` *before*
  `reserve()`. The bound is proportional to bytes that actually arrived.
- `RECURSION_LIMITATION()` — an RAII counter at the top of every method, limit
  100 (`EPEE_PORTABLE_STORAGE_RECURSION_LIMIT_INTERNAL`).
- `max_objects` / `max_fields` / `max_strings` — **only when a `limits_t` is
  passed.** See "Three limit regimes" in `flows.md`; the defaults are
  `SIZE_MAX`.

**Traps.**

- **The (de)serializers do not exist in the source.** `store`, `_load`, `load`
  and `serialize_map<is_store, t_storage>` are emitted by
  `BEGIN_KV_SERIALIZE_MAP()`. Grep for the field name, not the function.
- **`KV_SERIALIZE_N` discards its result.** The macro body is a bare
  expression statement — no `if`, no `return`. A missing or wrong-typed field
  leaves the member at its value-initialised default and parsing continues.
- **`load` and `_load` are different.** `load` wraps `serialize_map` in
  try/catch and logs "Exception on unserializing"; `_load` does not catch, and
  nested objects go through `_load`.
- **`store()` is declared `const` and is not** — it `const_cast`s `*this` and
  runs the same non-const `serialize_map` body.
- **`load_from_binary` does not check that the input was consumed.** The body
  ends `buf_reader.read(m_root); return true;//TODO:`. Trailing bytes after a
  valid message are ignored.
- **Duplicate keys are rejected on the binary path and accepted on the JSON
  path** (last one wins). The binary check is a `lower_bound` comparison in
  `read(section&)`.
- `ps_min_bytes<T>::strict` is 1 for `section` and `array_entry`, so for those
  the proportional bound permits a count equal to the whole remaining input.
- On a 32-bit build, `read_varint`'s `v` is a `size_t`, so the 64-bit marker
  branch truncates before the shift.
- epee's JSON parser is hand-written. Do **not** assume rapidjson semantics
  (number handling, duplicate keys, depth limits, UTF-8 validation).

---

## `contrib/epee/include/net/` — Levin, the TCP server, HTTP, TLS

The transport under both P2P and RPC.

**The Levin frame** (`levin_base.h`): `struct bucket_head2` carries
`m_signature` (`LEVIN_SIGNATURE` = `0x0101010101012101LL`), `m_cb` — a
`uint64_t` body length straight off the wire — plus command, flags and
protocol version. `LEVIN_DEFAULT_MAX_PACKET_SIZE` is 100 MB after the
handshake; 256 KiB before it. `m_max_packet_size` is a public
`std::atomic<uint64_t>` that flips at handshake.

**The server** (`abstract_tcp_server2.inl`, 2102 lines — an implementation,
not a fragment): `boosted_tcp_server` with a boost::asio io_context, per
connection **two strands** — `m_strand` serializing socket reads and writes,
`connection_basic::strand_` serializing protocol-handler work. `handle_read`
posts to the second strand specifically so queued writes cannot deadlock
against it; the comment says so.

**The HTTP server** (`http_protocol_handler.inl`) is a hand-written state
machine. It is where total request size is bounded — `m_max_content_length`,
set to `MAX_RPC_CONTENT_LENGTH` (1048576) for the daemon — plus a 9000-byte
request line and a 100000-byte header block.

**Traps.** The connection filter (`is_remote_host_allowed`) and connection
limit (`is_host_limit`) are virtuals called from
`abstract_tcp_server2.inl` before any bytes are read; the daemon implements
them in `node_server`, the RPC server in `http_server_impl_base`. Any HTTP 500
sets `m_want_close`, so a handler that throws also kills the connection.

---

## `src/serialization/` — the consensus archive

The other serialization system, and the one whose output **is** the
transaction and block identity.

**The DSL.** A type writes `BEGIN_SERIALIZE_OBJECT() FIELD(x) VARINT_FIELD(y)
END_SERIALIZE()` and the macros generate a *pair* of function templates
parameterised on `Archive<W>` where `W` is `is_saving`. One body serves as
both reader and writer, which is how round-trip fidelity is maintained by
construction. Dispatch is through overloaded free `do_serialize` functions at
**global** scope, selected by SFINAE.

**Archives.** `binary_archive<false>` (read, over an `epee::span`),
`binary_archive<true>` (write, over a `std::ostream`), `json_archive<true>`,
`debug_archive`.

**Invariants that matter.**

- `serialization::serialize` on a reading archive succeeds only if
  `ar.eof()`. Callers that must tolerate trailing bytes say
  `serialize_noeof` explicitly — `parse_and_validate_tx_prefix_from_blob` is
  the notable one.
- Varints must be **canonical**: `tools::read_varint` returns
  `EVARINT_REPRESENT` (-2) for a `0x00` continuation byte at a non-zero shift
  and `EVARINT_OVERFLOW` (-1) above the target width.
- Every read-side allocation bound is keyed on
  `binary_archive<false>::remaining_bytes()`, and there are only a handful:
  `container.h` (element count ≤ bytes left, then
  `reserve(min(N, bytes/sizeof(T) * ratio))`), `string.h`, `crypto.h`.
- `PREPARE_CUSTOM_VECTOR_SERIALIZATION` **resizes with no bound of its own**.
  Its ~15 call sites (2 in `cryptonote_basic.h`, 13 in `rctTypes.h`) each
  supply a count derived from already-parsed data, not from the wire.

**Traps.**

- **Two directories are called `serialization` and both are on the include
  path.** `"serialization/serialization.h"` is `src/`;
  `"serialization/keyvalue_serialization.h"` is epee.
- `json_archive` is **write-only**: `json_archive<false>` is declared and never
  defined.
- `src/serialization/json_object.{h,cpp}` (1542 lines) shares *nothing* with
  the archive DSL — it is a hand-written rapidjson mapping for the ZMQ/JSON
  RPC types.
- `VARIANT_TAG` values legitimately collide across different variants: both
  `txin_to_script` and `txout_to_script` are `0x0`. Tags are scoped to their
  own variant's type list.
- `std::list` and `std::forward_list` are **not** serializable, despite
  `serialization.h` including `<list>` — `is_container` lists only deque, map,
  multimap, set, unordered_map, unordered_multimap, unordered_set, vector.
- `ar.begin_array()` and `ar.begin_array(cnt)` are different functions: the
  no-arg form emits no count.

---

## `src/cryptonote_basic/` — the consensus types

The bottom of the consensus stack, and three risk levels in one directory.

**Consensus surface:** the `BEGIN_SERIALIZE` bodies in `cryptonote_basic.h`
(which *are* the wire format), the `VARIANT_TAG` byte assignments, tx and
block hashing, `get_block_longhash`, `get_block_reward`, `check_hash` and
`next_difficulty` in `difficulty.cpp`, the `HardFork` state machine.

**Wallet/scanner surface:** `account_keys` encryption,
`generate_key_image_helper`, `is_out_to_acc_precomp`, view-tag matching,
address encode/decode.

**Node-local, not consensus:** `miner.cpp` (1153 lines — a third of the
directory's `.cpp` lines; mining is not verification), `print_money`,
`connection_context.cpp` (the per-command P2P byte caps).

**Key functions.** `parse_and_validate_tx_from_blob` is the main untrusted
entry: size check → `serialize` → `n_key_offsets_exceeds_max` → hash.
`calculate_transaction_hash` is v1 = hash of the whole blob, v2 =
`cn_fast_hash` over three sub-hashes (prefix, base-rct slice, prunable hash).
`get_block_hashing_blob` is the **PoW preimage** and is distinct from what
`calculate_block_hash` hashes.

**Traps.**

- **`max_size_check` defaults to `false`** on every
  `parse_and_validate_tx_*` function. Only a handful of call sites pass
  `true`.
- **`parse_and_validate_block_from_blob` has no size parameter at all.** The
  only structural bound is `CRYPTONOTE_MAX_TX_PER_BLOCK` inside the
  serializer, checked *after* the vector is deserialized.
- **`get_transaction_unprunable_summary` is a second, hand-rolled byte
  parser** built from local `READ_VARINT`/`READ_BYTE`/`SKIP` macros that are
  `#undef`'d at the end of the function. It must accept exactly the same
  layout as the DSL serializer; a change to one needs a change to both.
- **`outPk[n].dest` and the bulletproof `V[i]` are not on the wire.**
  `expand_transaction_1` synthesises them after parsing, so they are not
  covered by the transaction hash.
- **Two separate hardcoded exceptions for block 202612**, in two functions,
  with different constants: one substitutes the block id in
  `calculate_block_hash`, the other short-circuits `get_block_longhash`.
- `blobdata_ref` is a `boost::string_ref` — a **non-owning view**. Several
  functions take it by value and accept a temporary `std::string` implicitly.
- `parse_hash256` is in the **global** namespace, declared at the bottom of
  `cryptonote_basic_impl.h` outside `namespace cryptonote`.
- **`HardFork` acceptance is an exact version match, not a floor:**
  `block_version == heights[current_fork_index].version`.
- `check_hash_128`'s fast-check branch is dead code — `#define
  FORCE_FULL_128_BITS` sits immediately above the `#ifndef`.
- `verification_context`'s fields are misspelled **`m_verifivation_failed`**
  and `m_verifivation_impossible`, consistently across the whole tree.
  `m_verification_failed` matches nothing.

---

## `src/cryptonote_core/` — the core facade and the pool

`cryptonote::core` is what the protocol handler, the RPC servers and the miner
all talk to. It owns a `BlockchainAndPool` and the outermost lock, and
forwards nearly everything.

**`BlockchainAndPool`** (`blockchain_and_pool.h`) exists because `Blockchain`
and `tx_memory_pool` take references to each other. Both constructors are
private with `friend struct BlockchainAndPool`; neither can be constructed
alone.

**The lock order is documented**, in `Blockchain::prepare_handle_incoming_blocks`
(`blockchain.cpp`, search `Order of locking`):

```
m_incoming_tx_lock (optional)  ->  m_tx_pool lock  ->  blockchain lock
```

with the note that "Something which takes the blockchain lock may never take
the txpool lock if it has not provably taken the txpool lock earlier".

**The pool is not an in-RAM map.** Transactions live in LMDB txpool tables;
`m_spent_key_images`, `m_txs_by_fee_and_receive_time` and `m_txpool_weight`
are RAM indexes over that table, rebuilt by `tx_memory_pool::init`.

**Traps.**

- **`handle_incoming_txs` (plural) does not exist.** The batching API was
  folded into `core::handle_incoming_tx`. Anything referring to the plural is
  describing an older tree.
- **`core::handle_incoming_block` has two overloads with different locking
  contracts.** The 5-arg one takes no lock and opens no DB batch — it assumes
  the caller bracketed it. `handle_single_incoming_block` is the self-contained
  one used for fluffy blocks.
- **`prepare_handle_incoming_blocks` locks and `cleanup_handle_incoming_blocks`
  unlocks, in different functions.** Every path between them must reach the
  cleanup.
- **`add_new_tx` returns `true` for a transaction already in the pool or on
  chain.** `tvc.m_added_to_pool` is the field that means "newly accepted", and
  it is also `false` when an existing entry merely has its relay method
  upgraded.
- **`tvc.m_relay` is only set when `meta.fee > 0`**, so a zero-fee transaction
  leaves it `relay_method::none` and is silently not relayed.
- **`relay_category::legacy` includes `relay_method::none`.**
- **Two unrelated `check_tx_inputs`:** `tx_memory_pool::check_tx_inputs` is a
  memoising wrapper; `Blockchain::check_tx_inputs` does the work.
- **`core::check_tx_semantic` is never called from `cryptonote_core.cpp`.** Its
  only caller is in `tx_verification_utils.cpp`.
- `tx_sanity_check` is **not** a consensus rule — it is opt-in per RPC request
  and is also linked into `wallet2`.
- `construct_tx` (`cryptonote_tx_utils.cpp`) hard-codes `rct=false`; it builds
  only pre-RingCT v1 transactions. Real wallets call
  `construct_tx_and_get_tx_key`.
- `m_input_cache` is `mutable`, consulted from a `const` method, cleared only
  when the tip moves, and **has no size cap**.

---

## `src/cryptonote_core/blockchain.cpp` — validation and reorganisation

5595 lines, and the only place that decides whether a block extends the main
chain, becomes an alternative, or triggers a reorg.

**Entry points.** `add_new_block` (takes txpool then blockchain lock),
`handle_block_to_main_chain`, `handle_alternative_block`,
`switch_to_alternative_blockchain`, `check_tx_inputs`,
`get_output_distribution` / `get_outs` (the decoy-availability surface the RPC
consumes).

**Invariants.**

- `hf_version` means different things on the two paths:
  `handle_block_to_main_chain` uses `get_current_hard_fork_version()` (state at
  the tip); `handle_alternative_block` uses `get_ideal_version(block_height)`.
  Mixing them up changes verdicts.
- `update_next_cumulative_weight_limit()` must run after every height change
  and every fork transition — `m_current_block_cumul_weight_median` is what
  `validate_miner_transaction` bounds the reward against.
- The difficulty window cache is only valid for a single-block advance.
- An alt block's cumulative difficulty is 128-bit but `alt_block_data_t` stores
  it as two `uint64_t`s; the split and the reassembly must stay inverse.
- `build_alt_chain` must leave `alt_chain` ordered front = oldest.
- `pop_block_from_blockchain` must never pop genesis and must call
  `m_hardfork->on_block_popped(1)`.

**Traps.**

- **There is no in-memory alternative chain map.** `m_alternative_chains` does
  not exist; alt blocks are in the LMDB `alt_blocks` table.
- **There is no maximum reorg depth.** Checkpoints
  (`checkpoints::is_alternative_block_allowed`) are the only bound.
- **The cumulative-difficulty comparison is strict `<`** — equal difficulty
  does not reorg, first seen keeps the chain.
- **`handle_alternative_block` returns `true` for an orphan** (setting
  `bvc.m_marked_as_orphaned`). Read `bvc`, not the return value.
- **`handle_alternative_block` does not run `check_tx_inputs`.** Only
  `ver_non_input_consensus`. Input validity is checked when the alt chain is
  reapplied through the main-chain path.
- **`fast_check`** (under `PER_BLOCK_CHECKPOINT`, on by default) skips the PoW
  hash, `ver_non_input_consensus` and per-tx `check_tx_inputs`. Any new
  consensus check placed in the non-fast branch is skipped during sync.
- **`goto leave`** — eight jump sites, one label sitting inside the first `if`
  block immediately before `return false`. One of them (the pruned-block
  branch) jumps backwards past declarations.
- `check_for_double_spend` exists but its only call site is commented out; the
  DB's duplicate-key-image error catches it instead.
- `add_block_as_invalid` inserts into `m_invalid_blocks`, which is **unbounded**
  and only cleared by the `flush_cache` RPC.
- `get_long_term_block_weight_median` is `const` but mutates two `mutable`
  cache members.
- `DIFFICULTY_BLOCKS_COUNT` is an unparenthesised macro
  (`DIFFICULTY_WINDOW + DIFFICULTY_LAG`).

---

## `src/blockchain_db/` — BlockchainDB, LMDB, pruning

`new_db()` unconditionally returns a `BlockchainLMDB`. There is no runtime
backend choice, so LMDB's behaviour is effectively consensus-relevant: an
output index returned wrong is a chain split.

**Schema.** `#define VERSION 5` in `db_lmdb.cpp`, with a `migrate_0_1` …
`migrate_4_5` ladder run from `open()`. 19 sub-databases are opened
(`maxdbs` 32). The DUPFIXED tables use a dummy 8-byte all-zero key
(`zerokval`), so the logical key is the first field of the *data*.

**Transactions.** `m_writer` records the thread that opened a write batch, and
`batch_commit` / `batch_stop` / `batch_abort` all re-check it. `do_resize`
throws if a write txn is open, and its barrier is
`prevent_new_txns()` → `wait_no_active_txns()` → `mdb_env_set_mapsize` →
`allow_new_txns()`, implemented as **lock-free spins** on a `std::atomic_flag`
and an atomic counter.

**Pruning** (`src/common/pruning.{h,cpp}`): stripe arithmetic over a seed.
`prune_worker` only ever deletes from `m_txs_prunable` and
`m_txs_prunable_tip`; v1 transactions are never pruned and tip blocks
(`CRYPTONOTE_PRUNING_TIP_BLOCKS` = 5500) are never pruned.

**Traps.**

- **`src/lmdb/` is not this.** It is a separate C++ LMDB wrapper (`lmdb_lib`)
  used by the ZMQ/`expect<T>` code, not by the block store.
- **The cursor names do not exist as identifiers.** `m_cur_blocks` is a macro
  for `m_cursors->m_txc_blocks`; `CURSOR(x)` / `RCURSOR(x)` paste the name.
- `TXN_POSTFIX_RDONLY()` is an **empty macro** — a missing call changes
  nothing.
- **`block_rtxn_start()` silently returns the *write* transaction** when
  called on the writer thread with a batch open, so reads on that thread see
  uncommitted data.
- `batch_start()` **returns false** rather than throwing when a batch is
  already active; callers spin on that with the locks released.
- **`LockedTXN`'s destructor calls `abort()`**, not commit. An early `return`
  between the writes and `lock.commit()` silently discards them, and both
  `commit()` and `abort()` swallow exceptions into `MWARNING`.
  But note it only owns a batch it started: the constructor stores
  `m_batch = m_db.batch_start()`, which **returns false when a batch is
  already active**, and both `commit()` and `abort()` are gated on `m_batch`.
  Nested inside an existing batch, a `LockedTXN` is a no-op — so "the DB batch
  is rolled back" only holds when that `LockedTXN` opened it.
- **`txpool_tx_meta_t` is written raw** and pinned by
  `static_assert(sizeof(...) == 192)` plus an `offsetof` assert. Adding a field
  is a DB migration.
- The table schema is **duplicated** in
  `src/blockchain_utilities/blockchain_prune.cpp`; `open()`'s comment says to
  change both.
- `BlockchainDB::fixup()` will pop blocks back to height 202612 on a mainnet
  chain missing a specific key image.
- `external/db_drivers/liblmdb` is vendored third-party code with its own
  licence and style; do not hold `mdb.c` to Monero conventions.
- Two different `tools::get_pruning_stripe` overloads mean different things.

---

## `src/cryptonote_protocol/` — the NOTIFY layer

Everything between "a Levin notify arrived" and "core is asked to add a block
or a transaction", plus the reverse.

**Commands** (`cryptonote_protocol_defs.h`), base `BC_COMMANDS_POOL_BASE` =
2000: `NEW_BLOCK` 2001, `NEW_TRANSACTIONS` 2002, `REQUEST_GET_OBJECTS` 2003,
`RESPONSE_GET_OBJECTS` 2004, `REQUEST_CHAIN` 2006, `RESPONSE_CHAIN_ENTRY`
2007, `NEW_FLUFFY_BLOCK` 2008, `REQUEST_FLUFFY_MISSING_TX` 2009,
`GET_TXPOOL_COMPLEMENT` 2010. **2005 is unallocated** — counting structs gives
the wrong id.

**The handler** is `cryptonote_protocol_handler.inl`, 2917 lines, the real
implementation. `cryptonote_protocol_handler-base.cpp` — the only `.cpp` —
contains just a vestigial network-throttle base class.

**Invariants.** Every `NOTIFY_` id needs an entry in **three** places: the
struct's `ID`, `cryptonote_connection_context::get_max_bytes`, and the
`BEGIN_INVOKE_MAP2` table. A missing map entry logs "Unknown command" and
returns `LEVIN_OK` for notifies — a silent no-op. `m_sync_lock` is **always**
taken with `try_to_lock`, at all four sites. Nothing under
`m_check_span_queue_mutex` may call a core path that takes the txpool lock;
the comment says so.

**Traps.**

- **The nine handlers have no callers grep will find** — they are reached
  through `HANDLE_NOTIFY_T2`.
- **`NOTIFY_NEW_BLOCK` has no independent implementation**: it converts to a
  fluffy request and tail-calls the fluffy handler. The two commands carry
  different size caps.
- `MLOG_P2P_MESSAGE` already prepends `context`; one call site passes it
  again and prints it twice. `MLOGIF_P2P_MESSAGE`'s first argument is *code*,
  skipped when the log level is off.
- `context.get_expected_hash(h)` returns `boost::optional` compared directly
  against a `crypto::hash`; `boost::none` compares unequal, so an out-of-range
  height silently fails closed.
- **`m_expected_heights` is a vector of hashes, not heights.**
- `relay_method::forward` exists in `enums.h` but the switch in
  `handle_notify_new_transactions` treats it as "not supposed to happen here".
- In the noise (I2P/Tor) mode, `relay_method::stem` is silently downgraded to
  `local` with an `MWARNING`.
- **Dandelion++ state is strand-confined, not mutex-protected.** Every mutator
  asserts `running_in_this_thread()`.
- `block_queue` stores spans in a `std::set` ordered by start height;
  `has_next_span` and `get_next_span` look only at `begin()`, they do not
  search.
- One `node_server` shares **one** protocol handler across all zones, but each
  zone has its own `levin::notify`.

---

## `src/p2p/` and `src/net/` — the node and the address layer

`node_server` implements four interfaces at once: `levin_commands_handler`,
`i_p2p_endpoint`, `i_connection_filter` and `i_connection_limit`. It is a
template on the payload handler; `net_node.inl` is 3188 lines and is emitted
from `src/rpc/instantiations.cpp`.

**Zones.** Public / Tor / I2P, each with its own `boosted_tcp_server`,
peerlist, peer id and connect function. **All non-public zones borrow the
public zone's `io_context`.** On non-public zones only `COMMAND_HANDSHAKE`,
`COMMAND_TIMED_SYNC` and `NOTIFY_NEW_TRANSACTIONS` are allowed
(`is_filtered_command`).

**Peer lists.** White (verified), gray (heard about), anchor (eclipse
resistance). An address enters the white list only after a successful outbound
handshake or a successful **back-ping** proving the advertised port accepts
connections and returns the same peer id. `last_seen` from a remote peer is
never trusted — `sanitize_peerlist` zeroes it.

**Lock order inside the node:** `m_host_fails_score_lock` →
`m_blocked_hosts_lock` → `m_peerlist_lock`.

**Traps.**

- `node_server::handle_invoke_map`, `invoke` and `notify` **do not exist in
  any source file** — `BEGIN_INVOKE_MAP2` / `CHAIN_LEVIN_INVOKE_MAP2` generate
  them.
- `block_host` is declared with **different default arguments** in the
  interface (`seconds = 0`) and the implementation (`P2P_IP_BLOCKTIME`).
- **Most of `peerlist_manager` lives in the header**, not the `.cpp`.
- `get_peerlist` exists three times with three different meanings, one of
  which *appends*.
- `m_network_zones.at(zone)` throws; `m_network_zones[zone]` **inserts**, and
  inserting after configuration invalidates held references.
- **Ping connections are real connections** that must not be counted;
  `is_ping` marks them.
- `get_random_index_with_fixed_probability` is deliberately **not uniform** —
  a cubic bias toward the most recently seen white peer.
- `block_subnet` and `unblock_subnet` are asymmetric: unblock recursively
  splits stored subnets around the removed range.
- `--igd` / `--no-igd` are accepted and do nothing; UPnP was removed.
- `i2p_address::store` writes port **1**, not 0, for compatibility.
- In `src/net/parse.cpp`, `get_network_address` returns
  `net::error::unsupported_address` for anything hostname-shaped, and callers
  treat that specific error as "try DNS".

---

## `src/rpc/` — the daemon's RPC surfaces

Two independent surfaces with unrelated restriction sets.

**HTTP** (`core_rpc_server.{h,cpp}`): a compile-time `else if` chain generated
by `BEGIN_URI_MAP2`, matching **exact byte equality against the raw request
target**. Three codecs chosen by macro: `MAP_URI_AUTO_JON2` (epee JSON),
`MAP_URI_AUTO_BIN2` (binary portable_storage), `BEGIN_JSON_RPC_MAP`
(JSON-RPC 2.0 over `/json_rpc`). Each RPC server runs **exactly two** io
threads (`m_server.run(2, false)`, `src/daemon/rpc.h`).

**ZMQ** (`daemon_handler.cpp`, `zmq_server.cpp`, `daemon_messages.cpp`): one
thread on a `ZMQ_REP` socket, rapidjson-based, 10 MiB frame cap, no auth, no
TLS, no per-IP limit. Its `handlers[]` table and its restricted blocklist must
both stay lexicographically sorted — the constructor throws
`std::logic_error` otherwise.

**Restricted mode has two forms**, and a new endpoint needs both considered:
the dispatch-level `MAP_..._IF(..., !m_restricted)` (whole method hidden, and
a refusal is a **404, never a 403**), and the in-handler
`const bool restricted = m_restricted && ctx;` (caps and redaction; `ctx` is
NULL for in-process callers). The restricted and unrestricted HTTP servers are
two *different* `core_rpc_server` objects on two different ports.

**ZMQ restriction is a different flag entirely.** The HTTP servers read
`cryptonote::core_rpc_server::arg_restricted_rpc` (`--restricted-rpc`); the
ZMQ server reads `daemon_args::arg_restricted_zmq_rpc`
(`--restricted-zmq-rpc`, `src/daemon/daemon.cpp:139`). One flag does not feed
both. `--public-node` enables neither — it only advertises the port, and
throws "restricted RPC mode is required" unless restriction is already on.

**Traps.** `/get_transaction_pool_hashes.bin` is mapped with
`MAP_URI_AUTO_JON2` — a JSON endpoint despite the suffix. The `.bin` request
bodies are parsed with **no** portable_storage count limits. Response
serialization has no size limit; the only backstop is a 25 MiB queued-byte
soft limit applied after the response is already built in memory.
`rpc_handler.cpp`'s `get_output_distribution` keeps a process-wide
function-local static cache behind a mutex, shared by the HTTP and ZMQ paths.

---

## `src/daemon/`, `src/daemonizer/`, `src/blockchain_utilities/`

The executable and the offline tools. The startup and shutdown ordering is in
`flows.md` §5 — it is a contract expressed as member declaration order, and
the destructors are where durable state is written.

Worth knowing: **`t_core::run()` returns true and does nothing** — all of
core's work happens in the constructor. `tx_memory_pool::deinit()` and
`core::load_state_data()` are stubs too. The `monerod <command>` positional
form is a completely separate program flow that never constructs a node.

`src/blockchain_utilities/` holds `blockchain_import`, `_export`, `_prune`,
`_stats`, `_usage`, `_ancestry`, `_depth`, `_prune_known_spent_data`.
`src/debug_utilities/` holds `cn_deserialize` and `object_sizes`, both useful
as reading aids.

---

## `src/common/` and the logging system

`src/common` builds the `common` library nearly everything links: filesystem
and process helpers (`util.cpp`, 1142 lines), the global thread pool, an HTTP
downloader, a libunbound DNSSEC wrapper, the MoneroPulse update check, base58,
varints, `expect<T>`, a password prompt, and `boost::program_options` wrappers.

**`tools::threadpool`** has two process-wide singletons —
`getInstanceForCompute()` (hardware concurrency) and `getInstanceForIO()` (8
threads). Two things to internalise: `submit` **runs the task inline on the
caller** when depth > 0 or every thread is busy, and `waiter::wait()` **drains
the queue on the calling thread** before blocking. "This runs on a worker
thread" is never guaranteed. `create` spawns `max - 1` threads because the
submitter is expected to contribute.

**`expect<T>`** (`src/common/expect.h`, 449 lines) is the modern alternative to
exceptions, used in `src/net`, `src/lmdb` and `src/rpc/zmq_*` — with
`MONERO_PRECOND`, `MONERO_CHECK`, `MONERO_UNWRAP` and `MONERO_THROW`. Nothing
in the older tree uses it.

**Logging.** `MERROR` / `MWARNING` / `MINFO` / `MDEBUG` / `MTRACE` expand
through `MCERROR` → `MCLOG` → `MCLOG_TYPE`, gated by a category string that is
a **per-translation-unit macro**: every `.cpp` does
`#undef MONERO_DEFAULT_LOG_CATEGORY` then `#define` its own. Consequences:

- **Arguments are only evaluated if the category and level pass.** A logging
  statement must never carry a needed side effect.
- **Grepping for a category string finds the single `#define`, never the call
  sites.** To find what writes to `net.dns`, find the file that defines it.
- **`LOG_PRINT_L0` does not mean level 0.** `L0 → MWARNING`, `L1 → MINFO`,
  `L2 → MDEBUG`, `L3 → MTRACE`.
- **`MGINFO` and friends hardcode the category `"global"`**, ignoring the
  file's own, and `global:INFO` is in every preset — so they always print.
- **Category matching is last-match-wins, not most-specific-wins** — the
  registry iterates `m_categories` with a `const_reverse_iterator`.
- `external/easylogging++` is vendored **and locally patched**: the whole
  category system Monero depends on is a Monero addition.
- The M\* macros are not variadic, so a top-level comma in the logged
  expression is a compile error.

**Other facts worth having.** `src/common/i18n.h` is a stub —
`i18n_translate(str, context)` returns `str` and there is no `i18n.cpp`
anywhere in the tree, so every `tr("...")` is a no-op today.
`src/common/dns_utils.h` declares `DNS_TYPE_AAAA = 8` (the IANA value for AAAA
is 28). `src/common/timings.cc` and `src/common/aligned.c` are not `.cpp`, so a
`*.cpp` glob misses them. `stack_trace.cpp` compiles only under the
`STACK_TRACE` option and interposes on `__cxa_throw` process-wide.
`memwipe` and `wipeable_string` live in `contrib/epee`, not here.
