# Errors and concurrency

Two cross-cutting dimensions where a wrong assumption produces a confident,
wrong conclusion. Read the error half before judging any failure path; read the
concurrency half before calling anything a race.

---

# Part 1 — Error reporting

**There are at least seven live conventions and no winner.** Which one is right
depends entirely on which directory you are in.

| convention | where it rules |
|---|---|
| `bool` return + non-const reference out-param, reason **logged not returned** | `cryptonote_basic`, `cryptonote_core`, `cryptonote_protocol`, `p2p`, most of `rpc` |
| typed exceptions from `tools::error` | `src/wallet` (not `api/`) |
| `DB_EXCEPTION` via `throw0` / `throw1` | `src/blockchain_db` (all in `lmdb/db_lmdb.cpp`) |
| `std::runtime_error` via `CHECK_AND_ASSERT_THROW_MES` | `multisig`, `fcmp_pp`, `device_trezor`, and `ringct` *construction* |
| `bool` with a catch-all that converts any exception to `false` | `ringct` *verification* (`verRct`, `verRctSemanticsSimple`, `verRctNonSemanticsSimple`, … in `rctSigs.cpp`) |
| `expect<T>` + custom `std::error_code` categories | `src/common`, `src/net`, `src/lmdb`, `src/rpc/zmq_*`, address parsing in `src/p2p`; epee `wire` defines the categories but throws them (`WIRE_DLOG_THROW`) |
| `bool` + a sticky status object | `src/wallet/api` |
| `int` status code across the Rust FFI (`0` ok, negative error) | `src/fcmp_pp/fcmp_pp_rust/src/lib.rs`; `tower_cycle.cpp` turns non-zero into a throw (`CHECK_FFI_RES`) |
| process exit — no channel at all | `src/crypto` C files (`abort()`); `crypto.cpp`'s `local_abort` (`_exit(1)` under `NDEBUG`); a Rust panic (below) |

`src/crypto/crypto.cpp` is itself mixed: most functions return `bool`, but the
tx-proof generators throw `std::runtime_error` on an invalid point.

About two in five of the bool-returning declarations in `src/` headers also
take a non-const reference out-param.

**The Rust FFI fails by terminating the process.** `fcmp_pp_rust/Cargo.toml`
sets `panic = "abort"` and `overflow-checks = true` in both the `dev` and
`release` profiles. A panic or arithmetic overflow anywhere in the Rust crate
or the `monero-oxide` crates it pins is a **process abort, not an exception**
the C++ side can catch. Judge a reachable panic as a remote crash.

## Grep lies about error handling

- **`grep 'throw '` finds roughly a quarter of the raise sites in `src/`.**
  The rest are behind `CHECK_AND_ASSERT_THROW_MES` and
  `THROW_WALLET_EXCEPTION_IF` (several hundred each),
  `throw0`/`throw1` (several hundred, all in `db_lmdb.cpp`),
  `THROW_WALLET_EXCEPTION`, `THROW_ON_RPC_RESPONSE_ERROR` and `MONERO_THROW`.
  Count each with `grep -rhoP "(?<![A-Za-z_])NAME\(" src | wc -l`.
  **A hunk with no `throw` token can still throw.**
- **`grep 'catch'` under-reports by dozens of clauses in `src/`** and in
  `contrib/epee`, because `TRY_ENTRY()` / `CATCH_ENTRY*(...)` generate both —
  two hidden `catch` clauses per `CATCH_ENTRY*` use
  (`contrib/epee/include/misc_log_ex.h`). `src/p2p/net_peerlist.h` alone hides
  about twenty.
- **`grep 'return'` misses hundreds of early returns** inside the assert macros, plus
  `MONERO_PRECOND` / `MONERO_CHECK`, `RETURN_ON_RPC_RESPONSE_ERROR` (six
  hidden returns per use) and `CHECK_CORE_READY`.
- **Nothing in the tree is `[[nodiscard]]` or `warn_unused_result`** in `src/`
  or `contrib/epee`. Discarding a bool error return is always silent.

## The specific traps

- **`CHECK_AND_ASSERT_MES`'s second argument is a *return value*, not a
  boolean.** It is `false` in most `src/` uses, but also `0`,
  `boost::none`, `T()`, `numeric_limits<uint64_t>::max()`, `res.status` and
  `1`. Reading it as "assert this is false" inverts the logic. When a
  function's return type changes, every `fail_ret_val` in its body silently
  converts.
- **Exception hierarchies do not share a base you would guess.**
  `DB_EXCEPTION : public std::exception` — **not** `std::runtime_error`, so
  `catch (const std::runtime_error&)` around a DB call catches nothing.
  `tools::error::wallet_logic_error` derives from `std::logic_error`, so a
  `catch (const std::runtime_error&)` misses half the wallet hierarchy.
  And `CHECK_AND_ASSERT_THROW_MES` throws a plain `std::runtime_error`, so
  exceptions raised in ringct or multisig **are not in `tools::error`** even
  when they happen inside wallet code (over a hundred such sites in
  `src/wallet` itself).
- **Return polarity is not uniform.** `src/wallet/node_rpc_proxy.cpp` returns
  `boost::optional<std::string>` where an **engaged** optional is the *error*:
  `if (proxy.get_x(...)) { /* this is the failure branch */ }`. And
  `WalletImpl::checkBackgroundSync` returns **true when the operation must be
  refused**. `boost::optional` is also used hundreds of times as an ordinary "maybe",
  so polarity has to be read per function.
- **In an RPC handler, `return true` does not mean success.**
  `CHECK_CORE_READY` sets `res.status = CORE_RPC_STATUS_BUSY` and returns
  true. The transport bool and the semantic status are separate channels.
- **`invoke_http_json` returns true for any HTTP 200 whose body parses**,
  regardless of the RPC-level outcome. `invoke_http_json_rpc` additionally
  fails when the response's `error.code` is non-zero **or** `error.message` is
  non-empty, but neither looks at `res.status`. Checking only the bool and not
  `res.status` is a real bug that reads as correct — which is why the wallet
  routes everything through `THROW_ON_RPC_RESPONSE_ERROR`
  (`tools::error::throw_on_rpc_response_error`, which also treats an empty
  `status` as "no connection").
- **A daemon JSON-RPC handler that throws instead of filling `error_resp`
  ships `{"error":{"code":0,"message":""}}`** — `MAP_JON_RPC_WE_IF` catches
  `std::exception`, logs it, and serialises an unfilled error object. That
  object passes `invoke_http_json_rpc`'s error check, so the client sees a
  default-initialised result; only a `status` check catches it. The plain
  `MAP_JON_RPC` variant returns `-32603 "Internal error"` instead.
  `core_rpc_server.cpp` has far fewer catch clauses than handlers.
- **The epee KV map never reports failure.** `KV_SERIALIZE_N` discards the
  bool and `END_KV_SERIALIZE_MAP()` is literally `return true;}`. A missing
  field, or a `KV_SERIALIZE_VAL_POD_AS_BLOB` field of the wrong size
  (`unserialize_t_val_as_blob` returns false), leaves the member at its
  default. What does throw: a scalar whose type or range does not fit the
  member (`portable_storage_val_converters.h`), and malformed binary framing
  (`throwable_buffer_reader` in `portable_storage_from_bin.h`).
  **Adding a field to an RPC request adds zero validation.**
  The `src/serialization` DSL is the opposite — it fails closed.
- **`expect<T>::operator*` and `operator->` are `noexcept` and only
  `assert()`.** Dereferencing an errored `expect` in a release build is
  undefined, not a throw. `.value()` is the throwing form
  (`std::system_error`).
- **Levin return codes mean different things for notifications and invokes**
  (`levin_protocol_handler_async.h`). For a *notification*, a negative return
  from the handler closes the connection and anything else is ignored — so the
  `src/cryptonote_protocol` handlers, which are all notifications, `return 1;`
  for success even though `LEVIN_OK` is 0. For an *invoke* (handshake, timed
  sync, ping in `node_server`), the return code is sent back to the peer as the
  response's return code and does not by itself close the connection.
- **`END_INVOKE_MAP2`'s generated catch turns any escaping `std::exception`
  into `LEVIN_ERROR_CONNECTION_TIMEDOUT`** (-4), i.e. a disconnect for a
  notification. Separately, `connection<T>::handle_read`
  (`abstract_tcp_server2.inl`) wraps `handle_recv` in
  `CATCH_ENTRY_SWALLOW_EX` and shuts the connection down on failure. So a new
  throw path in a P2P handler is **a remotely triggerable disconnect rather
  than a crash**. Evaluate it as a DoS and eclipse surface, not as an
  exception-safety question — unless it can reach a Rust panic or an
  `abort()`, which no catch stops.

## Empty catches — mostly deliberate

Of the ~600 catch clauses in `src/` (`grep -rhoP "(?<![A-Za-z_])catch\s*\(" src
| wc -l`), **a few dozen are empty or comment-only**, and dozens more contain
only a log call. The three recognisable shapes:

1. **Best-effort side effect** — I/O, unlocking, host counting, destructors.
2. **Try / parse / fallback with a sentinel flag** set inside the `try` and
   tested after it. This is an established idiom
   (`wallet2.cpp`, `tx_pool.cpp`).
3. **A genuine swallow** — execution falls into code that assumes the `try`
   succeeded.

**Read the lines *after* the block, not just inside it.** And note the
inverse: an empty `catch (const BLOCK_DNE&)` immediately followed by
`catch (const std::exception&) { MERROR(...); throw; }`
(`Blockchain::get_block_id_by_height`) is not a swallow at all — it suppresses exactly one
type and rethrows everything else.

`LockedTXN` (`src/blockchain_db/locked_txn.h`) is a swallow by design:
`commit()` and `abort()` catch `std::exception` from `batch_stop` /
`batch_abort` and only log, and the destructor aborts an uncommitted batch. It
also does nothing when a batch is already active (`batch_start` returns false).

Some discarded returns are documented policy: `parse_tx_extra` returns false
on a malformed field but leaves every successfully parsed field in the output,
and several of the call sites that discard it carry the comment
`// ok if partially parsed` (`grep -rn "parse_tx_extra(" src`).

## What this means for a review

- **Identify the directory's dialect before judging the error handling.**
  Asking for `expect<T>` in `cryptonote_core` or `src/wallet` is against the
  grain — the `fcmp_pp` module did not use it.
- On a new KV-serialized RPC field, **state where the field is validated**.
- On a new `THROW_WALLET_EXCEPTION_IF`, check it is not the sole body of an
  `if` (bare `if`, dangling `else`), and that its type is in `tools::error` so
  the wallet-rpc and simplewallet catch chains can map it.
- On new Rust code, or a new input path into it, ask what panics: indexing,
  `unwrap`/`expect`, and overflow all abort the process.
- Search context flags by their misspelling — **`m_verifivation_failed`**
  (`git grep -c m_verifivation_failed`); the correct spelling matches nothing.

---

# Part 2 — Concurrency

## The threads that exist

In a running daemon (each verified by its creation site):

| thread(s) | created at |
|---|---|
| **10** P2P/epee ASIO workers, shared by **every** network zone (public, Tor, I2P zones are constructed on the public zone's `io_context`) | `node_server::run` (`src/p2p/net_node.inl`) — `int thrds_count = 10;` |
| the peers-logger thread | `node_server::run` (`mPeersLoggerThread`) |
| one transient thread **per DNS seed lookup** | `node_server::get_dns_seed_nodes` (`dns_threads`) |
| **2** io threads **per RPC server** (a second, restricted server exists when `--rpc-restricted-bind-port` is set) | `src/daemon/rpc.h` — `m_server.run(2, false)`; servers built in `src/daemon/daemon.cpp` |
| one ZMQ thread | `ZmqServer::run` (`src/rpc/zmq_server.cpp`) |
| one Blockchain async thread, running `io_context::run` | `Blockchain::init` (`m_async_pool.create_thread`) |
| the shared compute pool | `threadpool::create` (`src/common/threadpool.cpp`) |
| one thread per mining thread, plus the background-mining thread | `miner::start` / `miner::update_autodetection` (`src/cryptonote_basic/miner.cpp`) |
| one thread per download | `download_async` (`src/common/download.cpp`) |
| a stop watchdog | `t_daemon::run` (`src/daemon/daemon.cpp`) |
| in interactive mode, the console thread plus the stdin reader | `t_command_server::start_handling` → `console_handlers_binder::start_handling`, `async_stdin_reader` (`contrib/epee/include/console_handler.h`) |

The console thread calls `core_rpc_server` handlers **in-process** on the first
(unrestricted) RPC server object (`t_rpc_command_executor::m_rpc_server`),
concurrently with that server's own io threads.

In a wallet: the `wallet_api` background refresh thread
(`WalletImpl::WalletImpl`, `src/wallet/api/wallet.cpp`), the simplewallet idle
thread (`m_idle_thread`), the Trezor live-refresh thread
(`device_trezor::init`), and the same shared compute pool.
**`monero-wallet-rpc` runs exactly one network thread** (`run(1, true)` in
`wallet_rpc_server::run`), under the comment `DO NOT START THIS SERVER IN MORE
THEN 1 THREADS WITHOUT REFACTORING`.

`boost::thread` is the idiom — **`std::thread` appears on exactly one line of
`src/`** (the `arg_prep_blocks_threads` default in `cryptonote_core.cpp`,
calling only `hardware_concurrency()`). Over `src/` + `contrib/epee`,
`CRITICAL_REGION_LOCAL` and `boost::mutex` are the most common locking
tokens; `boost::recursive_mutex`, `boost::unique_lock`, `std::mutex` and
`std::lock_guard` each appear well under a hundred times (`grep -rhoF "NAME"
src contrib/epee | wc -l`).

## The lock order is documented — search for "Order of locking"

In `Blockchain::prepare_handle_incoming_blocks`
(`src/cryptonote_core/blockchain.cpp`):

```
// Order of locking must be:
//  m_incoming_tx_lock (optional)
//  m_tx_pool lock
//  blockchain lock
//
//  Something which takes the blockchain lock may never take the txpool lock
//  if it has not provably taken the txpool lock earlier
```

(A grep for "lock order" misses it — the comment says "Order of locking".)

**These locks are held across function boundaries.** `core::prepare_handle_incoming_blocks`
takes `m_incoming_tx_lock` with a bare `.lock()`, and `Blockchain::prepare_handle_incoming_blocks`
takes `m_tx_pool.lock()`; both are released only in the matching
`cleanup_handle_incoming_blocks`. Every caller (the protocol handler's
`try_add_next_blocks`, `core::handle_block_found`, `blockchain_import`)
must pair them on every exit path; `core::prepare_handle_incoming_blocks`
calls cleanup itself on failure. A new early return between the two leaks
both locks.

Other stated or structural rules:

- `Blockchain::add_new_block` takes **txpool then blockchain**, in that order,
  deliberately, to avoid deadlocking against a reorg.
- `m_sync_lock` in the protocol handler is **always** taken with
  `boost::try_to_lock`, at every site; it means "only one thread adds blocks
  at a time", and a thread that fails to get it goes back to downloading.
  One site is inside the `m_check_span_queue_mutex` region while the block
  adder takes `m_check_span_queue_mutex` in its `cleanup_on_exit` guard, so a
  blocking acquire there would deadlock.
- **Nothing held under `m_check_span_queue_mutex` may call a core path that
  takes the txpool lock or `m_incoming_tx_lock`** — the comment in
  `try_add_next_blocks` says so.
- Inside the node: `m_host_fails_score_lock` → `m_blocked_hosts_lock` →
  `m_peerlist_lock` (`add_host_fail` → `block_host` → peerlist eviction).
- In the pool: `m_transactions_lock` → `m_blockchain` → the LMDB `LockedTXN`.
- `handle_alternative_block` takes the txpool lock **while already holding the
  blockchain lock** — the reverse of the documented order. It is safe only
  because both its callers (`add_new_block`, `switch_to_alternative_blockchain`)
  are reached with the txpool lock already held; a new caller can break that.

## `epee::critical_section` is a *recursive* mutex

`CRITICAL_REGION_LOCAL(x)` → `boost::unique_lock critical_region_var(x)`
(`contrib/epee/include/syncobj.h`), and `epee::critical_section` is
`boost::recursive_mutex`. **Re-locking a `critical_section` on the same thread
is normal and intended here**, so "this takes the lock twice" is not by itself
a finding. But the macro deduces the lock type, so it is also used on plain
`boost::mutex` members (e.g. `m_used_stripe_peers_mutex` in `net_node.h`), where
re-locking deadlocks — check the member's declared type. The generated
variable name is fixed, so two in one scope is a redefinition error.

## Strands, not mutexes, in two places

- **epee networking**: each connection has **two** strands — `m_strand`
  serialising socket reads and writes, and `connection_basic::strand_`
  serialising protocol-handler work. `handle_read` posts `handle_recv` to the
  second specifically so queued writes cannot deadlock against it, and the
  next read is started only after `handle_recv` returns. Per connection at
  most one handler runs at a time; across connections they run in parallel on
  the shared worker threads, and a handler on one connection can act on others
  (relay, `drop_connection`, `for_each_connection`).
- **Dandelion++** (`src/cryptonote_protocol/levin_notify.cpp`): per-zone
  state (`zone::map`, `fluffing`, `flush_callbacks`, and the per-connection
  `fluff_txs` and `flush_time` in `zone::contexts`) is **strand-confined and
  not mutex-protected**; each noise channel has its own strand. The mutators
  check `running_in_this_thread()` with `assert`, which is compiled out under
  `NDEBUG`. Touching that state from outside the strand is a race no lock
  will catch and no release build will report.

## The threadpool does not guarantee a worker thread

`tools::threadpool` has two process-wide singletons —
`getInstanceForCompute()` and `getInstanceForIO()` (8 threads). Behaviours
that break the obvious mental model (all in `src/common/threadpool.cpp`):

- **`submit` runs a non-leaf task inline on the caller** when depth > 0 or
  every thread is busy with work already queued. An exception from an inline
  task propagates to the submitter, not to the waiter. A leaf task
  (`leaf == true`) is always queued, at the front (`queue.push_front`).
- **`submit` throws when called from inside a leaf job**
  (`CHECK_AND_ASSERT_THROW_MES(!is_leaf, ...)`). So code that itself submits
  (e.g. `hash_children_chunks` and `CurveTrees::outputs_to_leaves` in
  `src/fcmp_pp/curve_trees.cpp`) throws if run as a leaf job.
- **`waiter::wait()` drains the queue on the calling thread** (`run(true)`)
  before blocking — including jobs other submitters queued.
- **A queued job's exception never reaches the waiter.** `threadpool::run`
  catches everything, calls `e.wo->set_error()` when there is a waiter, and
  drops the exception; `waiter::wait()` only returns false.

So "this runs on a worker thread" is never guaranteed, which matters for any
reasoning about reentrancy or thread-local state. `create` spawns `max - 1`
threads because the submitting thread is expected to contribute.

## Thread affinity that is enforced

`BlockchainLMDB` records `m_writer = boost::this_thread::get_id()` in
`batch_start` and `block_wtxn_start`, and re-checks it (throwing
`DB_ERROR_TXN_START` or `DB_ERROR`) in `batch_commit`, `batch_stop`,
`batch_abort`, `block_wtxn_start` (when a batch is active), `block_wtxn_stop`
and `block_wtxn_abort`. The resize barrier is **lock-free spins** on
`mdb_txn_safe` statics — `while (creation_gate.test_and_set());` and
`while (num_active_txns > 0);` — sequenced `prevent_new_txns()` →
`wait_no_active_txns()` → `mdb_env_set_mapsize` → `allow_new_txns()`. An early
return or throw between prevent and allow leaves the gate set, and every later
non-nested transaction spins forever. Both existing resize paths
(`BlockchainLMDB::do_resize` and `lmdb_resized`) contain `throw0` calls in that
window.

**`block_rtxn_start()` silently returns the write transaction** when called on
the writer thread with a write transaction open (batch or `block_wtxn`), so
reads on that thread see uncommitted data.

## The wallet side

**`wallet2` is not internally thread-safe.** Its only per-instance mutex,
`m_daemon_rpc_mutex` (recursive), serialises the HTTP client — it protects
none of `m_transfers`, `m_blockchain` or the subaddress table. Nor does it
serialise `NodeRPCProxy`'s cache: in each proxy method the `lock_guard` on
`m_daemon_rpc_mutex` sits in an inner block that covers only the HTTP invoke
and ends right after `RETURN_ON_RPC_RESPONSE_ERROR`, and the cached members
(`m_rpc_version`, `m_daemon_hard_forks`, `m_height`, `m_target_height` and the
rest) are written after that scope closes (`src/wallet/node_rpc_proxy.cpp`,
`NodeRPCProxy::get_rpc_version`, `NodeRPCProxy::get_info`). (`m_run` and `m_stopped` are atomics so `stop()` can be called
from another thread.) Serialization is the front end's job:

- **simplewallet**: `m_idle_mutex` held by the idle refresh
  (`wallet_idle_thread`) and taken by many commands via `LOCK_IDLE_SCOPE()`
  (directly or through `SCOPED_WALLET_UNLOCK()`) — **not every one**.
  `on_command` takes no lock, so handlers without it (e.g. `show_transfer`,
  `freeze_thaw`, `address_book`) run concurrently with the
  idle refresh. Check the handler.
- **wallet-rpc**: one network thread, which also runs the auto-refresh idle
  handler, and five `std::atomic` members (`m_stop`, `m_teardown`,
  `m_stop_refresh_active`, `m_wallet_swap_active`, `m_auto_refresh_period`)
  for the only cross-thread interaction.
- **`wallet_api`**: `m_refreshMutex2` in `doRefresh` and the `LOCK_REFRESH()`
  macro — **and this is the one consumer with genuine concurrency.**
  `pauseRefresh()` does not wait for an in-flight refresh (`// TODO
  synchronize access`); `AddressBookImpl`, `SubaddressImpl` and
  `SubaddressAccountImpl` rebuild their row vectors with no mutex at all;
  `TransactionHistoryImpl`'s `shared_mutex` protects the vector but not the
  `TransactionInfo*` objects it hands out and then deletes in `refresh`.

One cross-cutting inconsistency worth knowing:
`wallet2::process_parsed_blocks` calls `hwdev.generate_key_derivation` (and
`is_out_to_acc_precomp` with `hwdev`) from threadpool jobs **without** holding
the `hw::device` lock, while `check_acc_out_precomp` and
`process_new_transaction` take `boost::unique_lock<hw::device>`.

## Before calling something a race

Two questions, in order:

1. **Is the state genuinely reachable from two threads at once**, or is it
   serialized by an existing lock, by a strand, or by the refresh cycle? A
   great many apparent races here turn out to be sequenced by something
   already present — and if an operation *is* serialized, an
   attacker-influenced write to it is deterministic rather than racy, which
   changes both the analysis and the severity.
2. **If it is genuinely concurrent, what does the attacker control about the
   timing?** A race requiring a window the attacker cannot influence is
   weaker than one they can drive.

Both directions are errors. Calling a serialized operation a race overstates
it; missing that a refresh writer runs alongside an API reader understates it.
