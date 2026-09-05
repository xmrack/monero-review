# End-to-end flows

Six traces through the whole system. Each one names the functions in order, the
file each lives in, and — the part that matters for review — **where validation
happens and where it does not**. "No validation here" is often the most useful
line in a trace.

Read the flow that covers whatever a diff touches before forming a theory. A
change that looks local usually sits somewhere in one of these six, and its
blast radius is whatever comes after it in the list.

Traced against master `3d3920d7`. Symbols were confirmed by grep; line numbers
were not carried over except where the code is hard to find without one,
because they rot fastest. Find a symbol with `git grep -n`, not with a
remembered line.

---

## 1. Life of a block: peer socket to LMDB

The path a block at the chain tip actually takes. It is the single most
attacker-exposed sequence in the daemon.

1. **`connection<T>::handle_read`** — `contrib/epee/include/net/abstract_tcp_server2.inl`.
   ASIO delivers bytes into a fixed-size buffer. No validation; only throttle
   and timeout accounting.
2. **`async_protocol_handler::handle_recv`** — `contrib/epee/include/net/levin_protocol_handler_async.h`.
   Appends to a per-connection cache and runs a head/body state machine.
   Cumulative buffered bytes are bounded by `m_max_packet_size`, which is
   256 KiB before the handshake and `LEVIN_DEFAULT_MAX_PACKET_SIZE`
   (100 MB, `contrib/epee/include/net/levin_base.h:64`) after it.
   `LEVIN_SIGNATURE` is checked at 8 bytes and again on the full header.
3. **Header parsed → per-command cap.** `bucket_head2`
   (`levin_base.h:49`) carries `m_cb`, a `uint64_t` body length **read straight
   off the wire — the first attacker-controlled length in the daemon**. It is
   checked against `min(max_packet_size, get_max_bytes(command))`.
   `cryptonote_connection_context::get_max_bytes`
   (`src/cryptonote_basic/connection_context.cpp`) is the per-command table:
   handshake and timed_sync 64 KiB, ping and support_flags 4 KiB,
   `NEW_BLOCK` / `NEW_TRANSACTIONS` / `RESPONSE_GET_OBJECTS` 128 MB,
   `REQUEST_GET_OBJECTS` 2 MB, `REQUEST_CHAIN` 512 kB,
   `RESPONSE_CHAIN_ENTRY` 4 MB, `NEW_FLUFFY_BLOCK` 4 MB,
   `REQUEST_FLUFFY_MISSING_TX` 1 MB, `GET_TXPOOL_COMPLEMENT` 4 MB,
   **default `SIZE_MAX`**. A new command with no table entry is uncapped.
   Two notes. The comparison is `m_current_head.m_cb > min(max_packet_size,
   max_bytes)` — **the whole Levin body**, so for a fluffy block the bundled
   transaction blobs *do* count against the 4 MiB, despite the in-source
   comment on that case reading "4 MB, but it does not includes transaction
   data". And `m_max_packet_size` is raised to 100 MB on the initiating side
   the moment the handshake is *sent*, before any response arrives.
4. **Macro dispatch.** `CHAIN_LEVIN_NOTIFY_MAP2` in `node_server` chains to
   `HANDLE_NOTIFY_T2` in `t_cryptonote_protocol_handler`. There is no runtime
   table; see `macros.md`.
5. **`buff_to_t_adapter` → `portable_storage::load_from_binary`** —
   `contrib/epee/include/storages/levin_abstract_invoke2.h`. First allocation
   proportional to attacker input. On this path the count caps
   `default_levin_limits = {8192 objects, 16384 fields, 16384 strings}`
   (`levin_abstract_invoke2.h:47`) **are** passed. See §"Three limit regimes"
   below — they are not universal.
6. **`handle_notify_new_fluffy_block`** —
   `src/cryptonote_protocol/cryptonote_protocol_handler.inl`. Returns
   immediately unless `context.m_state == state_normal` and the node believes
   itself synchronized. Then the blob size is checked against
   `get_current_cumulative_block_weight_limit() + 100` **before the blob is
   parsed**. `handle_notify_new_block` (the legacy full-block command) does no
   validation of its own: it converts to a fluffy request and tail-calls this
   handler — but the two commands carry *different* per-command caps in
   step 3.
7. **`parse_and_validate_block_from_blob`** —
   `src/cryptonote_basic/cryptonote_format_utils.cpp`. The binary archive
   refuses a container count greater than the remaining bytes and reserves only
   `min(cnt, remaining/ratio)`. `tx_hashes.size() <= CRYPTONOTE_MAX_TX_PER_BLOCK`
   is checked **after** the vector is deserialized — it is a consensus bound,
   not the memory bound.
8. **`make_pool_supplement_from_block_entry`** — rejects duplicate txids, and
   every bundled blob must parse and hash to a txid the block itself names.
   No stowaways.
9. **`core::handle_single_incoming_block` → `core::handle_incoming_block`** —
   `src/cryptonote_core/cryptonote_core.cpp`. Opens the LMDB write batch,
   records `m_writer` as this thread id, re-checks the blob size.
10. **`Blockchain::add_new_block`** — `src/cryptonote_core/blockchain.cpp`.
    Takes **the txpool lock first, then the blockchain lock** — that order,
    deliberately. `have_block(id)` consults the invalid-block cache;
    `prev_id == get_tail_id()` decides main chain versus alternative.
11. **`Blockchain::handle_block_to_main_chain`** — the validation body.
    Re-reads the tail under the lock (it can move between 10 and 11), consults
    `HardFork::check`, then: timestamp `<= now + 2h` and `>=` the median of the
    last 60; difficulty non-zero; `check_hash(proof_of_work, difficulty)`;
    `prevalidate_miner_transaction`; `ver_non_input_consensus` over the
    supplement; per-tx `check_tx_inputs`; `validate_miner_transaction`.
12. **`BlockchainLMDB::add_block`** — `src/blockchain_db/lmdb/db_lmdb.cpp`,
    inside the still-open batch. Throws `BLOCK_EXISTS`, `BLOCK_PARENT_DNE`,
    `KEY_IMAGE_EXISTS` on conflict.
13. **`cleanup_handle_incoming_blocks` → `batch_stop` or `batch_abort`.**
    Committed only if `m_batch_success` is still true, and only by the thread
    that opened the batch.

**Trust boundaries crossed:** peer → process (steps 1–8, twice: framing then
payload); the binary's own embedded hash list → process (step 11, see the
`fast_check` trap); LMDB → process (validation reads take stored state at face
value); process → ZMQ subscribers and `--block-notify` (step 11, fired
*before* the batch commits).

**Traps.**

- **`fast_check` disables three things at once.** When `PER_BLOCK_CHECKPOINT`
  is compiled in (`option(PER_BLOCK_CHECKPOINT ... ON)`) and the height falls
  inside the embedded hash list with a matching hash, the node skips the PoW
  hash, skips `ver_non_input_consensus`, and skips `check_tx_inputs`. A
  reviewer reading only the non-fast path is reading the branch most nodes do
  not take during sync.
- **`check_tx_inputs` can skip ring verification entirely** on an
  input-verification-id cache hit. The key is a hash of the txid *and the
  dereferenced mix ring* (`make_input_verification_id`,
  `src/cryptonote_core/tx_verification_utils.cpp`), which is what makes the
  cache sound; anything that widens the key's inputs without widening the hash
  breaks it.
- **`goto leave`.** `handle_block_to_main_chain` has eight `goto leave;` sites
  jumping to a `leave:` label that sits *inside* the first `if` block,
  immediately before `return false`. Adding cleanup between the label and the
  return changes every one of those eight paths.
- **Notifications fire before commit.** A ZMQ listener can observe a block that
  a later abort removes.
- Everything from the socket read to the LMDB commit runs on one of the
  **ten** epee ASIO worker threads (`int thrds_count = 10;`,
  `src/p2p/net_node.inl:1172`). RandomX hashing and ring verification happen
  inline on a network thread.

---

## 2. Life of a transaction: wallet to block

1. **`simple_wallet::transfer_main`** — `src/simplewallet/simplewallet.cpp`.
   Ring size must equal `wallet2::adjust_mixin` for the current fork; long
   payment ids are refused.
2. **`wallet2::create_transactions_2`** — takes
   `boost::unique_lock<hw::device>` plus `hw::reset_mode`, buckets unlocked
   outputs per subaddress, aims for 2-in/2-out.
3. **`wallet2::transfer_selected_rct`** — assembles `tx_source_entry` records,
   overwriting the ring entry that matches the real global output index.
4. **`wallet2::get_rct_distribution`** — asks the daemon for the RCT output
   distribution over `/get_output_distribution.bin`. **The wallet checks only
   that it is monotonic, long enough, and covers its own max output index.**
   There is no cross-source or cryptographic check. A hostile distribution
   biases decoy selection.
5. **`wallet2::get_outs` → `tools::gamma_picker::pick`** — decoys drawn from a
   gamma distribution over that distribution, then fetched via `/get_outs.bin`
   in chunks of 1000. Offsets are **sorted ascending per ring before the
   request** so the daemon cannot see which member is real.
   For the wallet's own real output the daemon must return the correct key,
   correct mask and `unlocked == true`, or construction fails. Decoys are taken
   as-is.
6. **`cryptonote::construct_tx_with_tx_key`** —
   `src/cryptonote_core/cryptonote_tx_utils.cpp`. Key images via the
   `hw::device` abstraction; **inputs sorted strictly descending by key image**
   (a consensus rule from HF 7); ring offsets converted to *relative* form;
   outputs shuffled; all `vin[i].amount` and `vout[i].amount` zeroed before
   hashing.
7. **`rct::genRctSimple` → `rct::proveRctCLSAGSimple`** — `src/ringct/rctSigs.cpp`.
   The last pseudo-out mask is derived as `sumout - sumpouts`, so commitment
   balance is a construction invariant on the sending side.
8. **`wallet2::commit_tx`** — POSTs to `/sendrawtransaction`. On a non-OK
   status it throws `error::tx_rejected` **before mutating any wallet state**,
   so the inputs stay unspent.
9. **`core_rpc_server::on_send_raw_tx`** — `src/rpc/core_rpc_server.cpp`.
   `CHECK_CORE_READY()`, hex decode, optional `tx_sanity_check`.
10. **`core::handle_incoming_tx`** — `src/cryptonote_core/cryptonote_core.cpp`.
    Note the name: **`handle_incoming_txs` (plural) does not exist on master.**
    Holds `CRITICAL_REGION_LOCAL(m_incoming_tx_lock)` for its whole duration,
    so no two transactions race into the pool with conflicting key images.
11. **`core::add_new_tx` → `tx_memory_pool::add_tx`** —
    `src/cryptonote_core/tx_pool.cpp`. Cheap "no-drop" checks first
    (`check_fee`, `tx.extra.size() <= MAX_TX_EXTRA_SIZE`, key-image conflicts),
    then `ver_non_input_consensus` and `Blockchain::check_tx_inputs`.
12. **`levin::notify::send_txs` → Dandelion++** —
    `src/cryptonote_protocol/levin_notify.cpp`. Stem or fluff by epoch.
13. **`tx_memory_pool::fill_block_template`** — walks
    `m_txs_by_fee_and_receive_time`. **A tx is skipped unless
    `meta.matches(relay_category::legacy)`**, i.e. it must already be
    broadcast; a stem-phase transaction is not mined unless the operator set
    `--mine-stem-txes`.
14. **`miner::worker_thread` → `core::handle_block_found`** → flow 1, step 11.

**Traps.**

- **`add_new_tx` returns `true` for a transaction already in the pool or
  already on chain.** The field that means "newly accepted" is
  `tvc.m_added_to_pool`.
- **`tvc.m_no_drop_offense` decides whether a peer is banned** for a rejected
  transaction. Any new rejection added before the expensive checks must set it,
  or a fee-policy disagreement becomes a ban.
- **Two `Blockchain::check_tx_inputs` overloads** — the six-argument one takes
  the blockchain lock and handles the per-block-checkpoint fast path; the
  four-argument one does the rule work. Likewise two `create_block_template`
  overloads and two `core::get_block_template` overloads.
- **`rct_config.bp_version` is remapped inside `genRctSimple`**: 0 and 4 both
  mean Bulletproofs+, 3 means CLSAG with BP2, 2 means BP2, 1 means BP.
- **`relay_method` and `relay_category` are different enums** in different
  headers (`src/cryptonote_protocol/enums.h` and
  `src/blockchain_db/blockchain_db.h`). They are easy to confuse and mean
  different things.
- **Dandelion++ state is strand-confined, not mutex-protected.** Touching
  `zone_->map` or a context's `fluff_txs` from outside `zone_->strand` is a
  race no lock will catch.
- `genRctSimple` has a `hw::device::TRANSACTION_CREATE_FAKE` branch emitting
  `make_dummy_clsag` placeholders — that is the fee-estimation path.

---

## 3. Wallet refresh against an untrusted node

The governing case: the user runs a wallet against a remote node they do not
control. The daemon is untrusted and the keys are in the process.

1. **`wallet2::refresh`** → `get_short_chain_history` builds an exponentially
   spaced locator over the wallet's own hashchain.
2. **`wallet2::pull_blocks`** → `/getblocks.bin`. Held under
   `m_daemon_rpc_mutex`. The response is parsed with the wallet-side caps
   `default_http_bin_limits = 65536*3` each
   (`contrib/epee/include/storages/http_abstract_invoke.h:98`).
3. **`wallet2::parse_block_round`** → `parse_and_validate_block_from_blob`.
   The wallet **recomputes each block id from the blob** and chains `prev_id`.
   **There is no proof-of-work check anywhere in the wallet.** `prev_id`
   chaining proves internal consistency of whatever the node made up, not chain
   validity.
4. **`check_block_hard_fork_version`** — the block's major version must fall in
   the height range this wallet's compiled tables expect. A coarse local
   consistency check, not a chain check.
5. **Pre-scan, on the compute threadpool**: `cache_tx_data` collects tx public
   keys from `tx_extra`; then `8*a*R` derivations via `hw::device`; then view
   tag filtering and `is_out_to_acc_precomp`.
6. **`wallet2::process_new_transaction` → `wallet2::scan_output`** — the part
   that makes a malicious node unable to forge a receive:
   `generate_key_image_helper_precomp` requires the regenerated ephemeral
   public key to equal the on-chain output key, and `rct::decodeRct` requires
   the ECDH-decrypted `(amount, mask)` to reopen the Pedersen commitment.
7. **Spend detection** is a purely local key-image lookup in `m_key_images`.
   The node is never consulted. (`rescan_spent` is a *different* operation that
   does consult it — and sends the wallet's key images to the node.)
8. **Balance** is never stored. `balance_per_subaddress` recomputes it from
   `m_transfers` on demand.
9. **`wallet2::store`** — not part of refresh. The cache is chacha20-encrypted
   with **no MAC**: confidential, not authenticated.

**What the wallet takes on trust from the daemon, and cannot check:**

- `m_global_output_index`, copied verbatim from `res.output_indices`. Unused
  during scanning; used later to build ring offsets when spending.
- The RCT output distribution (flow 2, step 4).
- Block timestamps, used by `should_skip_block`.
- **The pairing of a served tx blob with the block's `tx_hashes` entry.** The
  txid recorded on a `transfer_details` comes from the block header; the
  contents come from a separately supplied blob, and nothing checks the two
  match.

**Traps.**

- `wallet2` is **not internally thread-safe** for refresh state. Serialization
  is the front end's job — `LOCK_IDLE_SCOPE()` in simplewallet, the handler
  structure in wallet-rpc. The only lock inside `wallet2` on this path is
  `m_daemon_rpc_mutex`.
- `threadpool::submit` runs the job **inline on the caller's thread** when the
  pool is saturated, and `waiter::wait()` drains the queue on the waiting
  thread. "This runs on a worker thread" is not guaranteed.
- `process_parsed_blocks` calls `hwdev.generate_key_derivation` from several
  pool threads **without** holding the `hw::device` lock, unlike
  `scan_output`, which does.
- **`exit(1)`** at `src/wallet/wallet2.cpp:2916` on the received-amount
  consistency check — the process dies mid-scan rather than throwing. A defect
  reachable there is a denial of service.
- The view tag is an optimisation whose failure mode is a **false negative**
  (a missed output), never a false positive. A bug that over-rejects loses
  funds from the wallet's view silently.
- `m_max_reorg_depth` (`src/wallet/wallet2.h`) is a **wallet** bound. The
  daemon has no maximum reorg depth at all.

---

## 4. Life of an RPC request

Three body encodings on one server, plus an unrelated ZMQ surface.

1. **`daemonize::t_rpc::run`** — `src/daemon/rpc.h`. `m_server.run(2, false)`:
   **exactly two io_context worker threads per RPC server.** A handler that
   blocks removes half the capacity.
2. **`boosted_tcp_server::handle_accept`** → per-IP and total connection caps
   (`is_host_limit`). No content validation.
3. **`simple_http_connection_handler::handle_recv`** —
   `contrib/epee/include/net/http_protocol_handler.inl`. The one place total
   request size is bounded: `MAX_RPC_CONTENT_LENGTH = 1048576`
   (`src/cryptonote_config.h:136`). Request line ≤ 9000 bytes, header block
   ≤ 100000 bytes.
4. **`http_custom_handler::handle_request`** → optional HTTP digest auth.
   **If `--rpc-login` is not set — the default — this boundary does not
   exist.**
5. **`core_rpc_server::handle_http_request_map`** — generated by
   `BEGIN_URI_MAP2`. A compile-time `else if` chain of **exact string equality
   against the raw request target**. `/get_height?x=1` and `/get_height/` both
   404.
6. **Body parse**, by macro:
   - `MAP_URI_AUTO_JON2` → `load_t_from_json`, recursion limit 100.
   - `MAP_URI_AUTO_BIN2` → `load_t_from_binary` **with no limits argument**.
   - `BEGIN_JSON_RPC_MAP` → one parse into a `portable_storage`, then a second
     `else if` chain on `method`.
7. **Handler** → `core` → `Blockchain`, each call taking `m_blockchain_lock`
   independently. Some hot accessors (`get_current_blockchain_height`,
   `get_block_id_by_height`) deliberately take **no** lock and say so in
   comments, so a handler that combines them is not atomic against a reorg.
8. **Response** serialized by the same macro. **No size limit** — the only
   backstop is a 25 MiB queued-byte soft limit applied *after* the whole
   response is built in memory.
9. **ZMQ**, in parallel: one `boost::thread` running `ZmqServer::serve` on a
   `ZMQ_REP` socket, dispatching through `DaemonHandler`. 10 MiB frame cap, no
   auth, no TLS, no per-IP limit — only the bind address separates trust
   domains.

**Restricted mode is enforced in two independent places with different
semantics:**

- **At dispatch**, as an `else if` condition (`MAP_URI_AUTO_JON2_IF(...,
  !m_restricted)`). The whole method is hidden, and a refused method is
  **indistinguishable from a nonexistent one — 404, never 403.**
- **Inside handlers**, as `const bool restricted = m_restricted && ctx;`,
  gating caps and redaction. `ctx` is NULL for in-process callers, so
  restrictions are skipped for them by design.

A new endpoint needs both considered. The restricted and unrestricted servers
are two *different* `core_rpc_server` objects on two different ports.

**Traps.**

- `/get_transaction_pool_hashes.bin` is mapped with `MAP_URI_AUTO_JON2` — it is
  a **JSON** endpoint despite the `.bin` suffix.
- The HTTP restricted set and the ZMQ restricted set are unrelated. ZMQ blocks
  exactly ten method names (`src/rpc/zmq_restricted_methods.cpp`).
- Any HTTP 500 closes the connection, and a handler that throws or returns
  false produces a 500.
- The ZMQ `handlers[]` table and the restricted blocklist must stay
  lexicographically sorted; `DaemonHandler`'s constructor throws
  `std::logic_error` otherwise.

---

## 5. Daemon startup and shutdown

The ordering *is* the contract, and it is expressed as member declaration
order.

**Up:** `main()` (`src/daemon/main.cpp`) → `tools::on_startup()` → option
parsing → config file parsed into the *same* `variables_map` (command line
wins, `po::store` is first-wins) → network type and data dir →
`mlog_configure` (**everything logged before this goes to console only**) →
`daemonizer::daemonize` → `t_daemon` → `t_internals`.

`struct t_internals` (`src/daemon/daemon.cpp`) declares
`protocol, core, p2p, rpcs, zmq` — and **member declaration order is the real
construction order**, not the order in the mem-initializer list, which reads
`core, protocol, p2p, zmq`. Then two lines wire the cycle:
`protocol.set_p2p_endpoint(p2p.get())` and `core.set_protocol(protocol.get())`.
Before those, the protocol handler points at `m_p2p_stub` and core at
`m_protocol_stub`.

Inside `t_core`: `new_db()` always returns a `BlockchainLMDB` (there is no
runtime DB choice) → `BlockchainLMDB::open` → `Blockchain::init` →
`load_compiled_in_block_hashes` → `tx_memory_pool::init` (re-parses and
re-validates every stored pool tx against the current fork) →
`core::update_checkpoints` → `miner::init` (parses flags; **does not start
mining**).

`t_daemon::run` then starts a watchdog thread, `core.run()`, each `rpc->run()`,
the ZMQ server, and finally `p2p.run()`, **which blocks until the node stops**.

**Down:** every path funnels into `node_server::send_stop_signal`, which stops
the payload handler (and thence `core::stop()` → miner stopped,
`Blockchain::cancel()`), closes all zone connections, then stops the io
contexts. `~t_internals` destroys in exact reverse: zmq, rpcs, p2p, core,
protocol. **The durable writes happen in the destructors** — the peer list
reaches disk only through `store_config`, and `Blockchain::deinit` joins
`m_async_pool` before `m_db->close()` because that pool is what runs
`store_blockchain`.

**Traps.**

- **`t_core::run()` returns true and does nothing.** All of core's real work
  happened in the constructor. A reviewer looking for "when does core start"
  finds the wrong function. `tx_memory_pool::deinit()` and
  `core::load_state_data()` are stubs too.
- **RPC and ZMQ ports are bound during construction but only served in
  `run`.** The kernel queues connections in between.
  `check_core_ready()` gates *responses*, not connections.
- **Durability is off by default for the whole initial sync.** `MDB_NOSYNC`
  stays set until `on_connection_synchronized` calls `safesyncmode(true)` — and
  that is a no-op if the user pinned `--db-sync-mode`.
- `mlog_configure` sets `DisableApplicationAbortOnFatalLog`, so **`MFATAL` does
  not terminate**. Several init failures rely on an explicit `return false`
  right after the `MFATAL`; dropping that return turns a fatal into a warning.
- `Blockchain::init` has an empty `else { }` with a TODO to verify a loaded
  chain against checkpoints. An existing DB is adopted with no genesis or
  nettype cross-check.
- `node_server::init_config` swallows peerlist load failures, so a corrupt
  `p2pstate.bin` degrades to an empty peerlist rather than an error.
- `BlockchainLMDB::close` carries `FIXME: not yet thread safe!!!`; its
  correctness depends entirely on the join ordering established several layers
  up.
- `core::graceful_exit()` is just `raise(SIGTERM)`.

---

## 6. Initial sync, chain selection and reorganisation

1. **Peer selection** — `node_server::connections_maker` on the 1-second idle
   handler. Chooses *who* to talk to; validates nothing about honesty.
2. **`process_payload_sync_data`** — the peer's claimed height and cumulative
   difficulty are **taken at face value as the sync target**. Only the hard-fork
   version, the pruning seed shape and a downward height revision are checked.
3. **`NOTIFY_REQUEST_CHAIN` / `handle_response_chain_entry`** — the densest
   validation point in the flow. Unsolicited response, response past the
   expected height, empty id list, more than 25000 ids, duplicates, a first
   hash we do not know, a known main-chain hash at the wrong height: each drops
   the peer. **The size cap is checked before `reserve()`.**
4. **`Blockchain::prevalidate_block_hashes`** — checks against the compiled-in
   hash-of-hashes (one per `HASH_OF_HASHES_STEP` = 512 blocks). **Beyond the
   compiled table it returns "all fine" unconditionally.** It is not a general
   defence.
5. **`request_missing_objects` → `block_queue::reserve_span`** — spans reserved
   in a queue shared across connections, guarded by one recursive mutex.
6. **`handle_response_get_objects`** — bodies are validated against **the same
   peer's earlier hash claims**. A peer cannot contradict itself; that is not
   consensus. No PoW and no difficulty check happen here.
7. **`try_add_next_blocks`** — `m_sync_lock` is taken with `try_to_lock`.
   Whoever wins becomes the single block-adding thread; it is **whichever
   connection strand won the race**, not a dedicated thread.
8. **`prepare_handle_incoming_blocks`** — opens an LMDB write batch **sized by
   the peer-supplied span**, parses in parallel, precomputes RandomX hashes.
9. **`Blockchain::handle_alternative_block`** — full PoW is verified for every
   alt block, which is what makes a deep reorg expensive. The main-chain
   `fast_check` path does not apply here.
10. **`switch_to_alternative_blockchain`** — pops main-chain blocks one at a
    time, replaying their transactions into the mempool with
    `relay_method::block`, then reapplies the alt chain through
    `handle_block_to_main_chain`.

**Facts that correct a common mental model:**

- **There is no in-memory alternative chain map.** `m_alternative_chains` does
  not exist; alt blocks live in the LMDB `alt_blocks` table
  (`add_alt_block` / `get_alt_block` / `remove_alt_block`).
- **There is no maximum reorg depth.** No constant in `cryptonote_config.h`
  bounds it. `checkpoints::is_alternative_block_allowed` is the only depth
  bound, and only up to the last checkpoint at or below the current tip.
  (`m_max_reorg_depth` is a *wallet* setting.)
- **The cumulative-difficulty comparison is strict less-than**, so an alt chain
  with exactly equal difficulty does not win — first seen keeps the chain.
- `rollback_blockchain_switching` is misnamed and the code says so: the pops
  have already happened; it only re-applies.
- `handle_alternative_block` inserts the alt block's transactions into the
  **real mempool** before deciding whether a reorg happens.
- Sync is refused entirely on non-public zones: `process_payload_sync_data`
  returns early for Tor and I2P peers.

---

## Three limit regimes on one parser

The same `portable_storage` binary reader is reached with three different
count-limit configurations. Getting this wrong in either direction is a common
review error.

| path | object / field / string caps | where |
|------|------------------------------|-------|
| P2P Levin | 8192 / 16384 / 16384 | `default_levin_limits`, `levin_abstract_invoke2.h:47` |
| wallet parsing a daemon `.bin` response | 196608 each (`65536*3`) | `default_http_bin_limits`, `http_abstract_invoke.h:98` |
| **daemon parsing a `.bin` request** | **none** | `MAP_URI_AUTO_BIN2` calls the two-argument `load_t_from_binary`, so `limits` defaults to `NULL` |

`portable_storage::load_from_binary(span, const limits_t *limits = nullptr)`,
and `throwable_buffer_reader`'s constructor sets all three maxima to
`numeric_limits<size_t>::max()` — `set_limits()` is only reached when a
`limits_t` is actually passed.

What still bounds the uncapped path: `read(void*, count)` refuses to read past
the buffer; `read_ae<T>()` refuses an element count greater than
`m_count / ps_min_bytes<T>::strict`, i.e. **proportional to the bytes that
actually arrived**, before `reserve()`; and `RECURSION_LIMITATION()` caps
nesting at 100. So memory stays proportional to input size on every path. It
is the *counts* that differ — do not state the 8192/16384/16384 numbers as a
property of "epee parsing".
