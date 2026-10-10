# Errors and concurrency

Two cross-cutting dimensions where a wrong assumption produces a confident,
wrong conclusion. Read the error half before judging any failure path; read the
concurrency half before calling anything a race.

---

# Part 1 — Error reporting

**There are at least six live conventions and no winner.** Which one is right
depends entirely on which directory you are in.

| convention | where it rules |
|---|---|
| `bool` return + non-const reference out-param, reason **logged not returned** | `cryptonote_basic`, `cryptonote_core`, `cryptonote_protocol`, `p2p`, most of `rpc` |
| typed exceptions from `tools::error` | `src/wallet` (not `api/`) |
| `DB_EXCEPTION` via `throw0` / `throw1` | `src/blockchain_db` |
| `std::runtime_error` via `CHECK_AND_ASSERT_THROW_MES` | `ringct`, `multisig`, `fcmp_pp`, `device_trezor` |
| `expect<T>` + custom `std::error_code` categories | `src/common`, `src/net`, `src/lmdb`, `src/rpc/zmq_*`, address parsing in `src/p2p` |
| `bool` + a sticky status object | `src/wallet/api` |
| `abort()` — no channel at all | `src/crypto` (C) |

`src/` headers declare well over a thousand bool-returning functions, roughly
half of them with a non-const reference out-param.

## Grep lies about error handling

- **`grep 'throw '` finds roughly a quarter of the raise sites in `src/`.**
  The rest are behind `CHECK_AND_ASSERT_THROW_MES` and
  `THROW_WALLET_EXCEPTION_IF` (several hundred each),
  `throw0`/`throw1` (several hundred, all in `db_lmdb.cpp`),
  `THROW_WALLET_EXCEPTION`, `THROW_ON_RPC_RESPONSE_ERROR` and `MONERO_THROW`.
  Count each with `grep -rhoP "(?<![A-Za-z_])NAME\(" src | wc -l`.
  **A hunk with no `throw` token can still throw.**
- **`grep 'catch'` under-reports by dozens of clauses in `src/`** and in
  `contrib/epee`, because `TRY_ENTRY()` / `CATCH_ENTRY(...)` generate both —
  two hidden `catch` clauses per `CATCH_ENTRY*` use.
  `src/p2p/net_peerlist.h` alone hides about twenty.
- **`grep 'return'` misses hundreds of early returns** inside the assert macros, plus
  `MONERO_PRECOND` / `MONERO_CHECK`, `RETURN_ON_RPC_RESPONSE_ERROR` (six
  hidden returns per use) and `CHECK_CORE_READY`.
- **Nothing in the tree is `[[nodiscard]]`** — zero occurrences in `src/` and
  `contrib/epee`. Discarding a bool error return is always silent.

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
  `src/wallet`).
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
  fails on a JSON-RPC `error`, but neither looks at `res.status`. Checking only
  the bool and not `res.status` is a real bug that reads as correct — which is
  why the wallet routes everything through `THROW_ON_RPC_RESPONSE_ERROR`.
- **A daemon JSON-RPC handler that throws instead of filling `error_resp`
  ships `{"error":{"code":0,"message":""}}`** — `MAP_JON_RPC_WE` catches
  `std::exception`, logs it, and serialises an unfilled error object.
  `core_rpc_server.cpp` has far fewer catch clauses than handlers.
- **The epee KV serializer never fails.** `KV_SERIALIZE_N` discards the bool
  and `END_KV_SERIALIZE_MAP()` is literally `return true;}`.
  **Adding a field to an RPC request adds zero validation.**
  The `src/serialization` DSL is the opposite — it fails closed.
- **`expect<T>::operator*` and `operator->` are `noexcept` and only
  `assert()`.** Dereferencing an errored `expect` in a release build is
  undefined, not a throw. `.value()` is the throwing form.
- **In `src/cryptonote_protocol`, handlers `return 1;` for success** even
  though `LEVIN_OK` is 0 — only *negative* returns drop the connection. And
  `END_INVOKE_MAP2`'s generated catch turns any escaping exception into
  `LEVIN_ERROR_CONNECTION_TIMEDOUT`, i.e. **a remotely triggerable peer
  disconnect rather than a crash**. Evaluate a new throw path there as a DoS
  and eclipse surface, not as an exception-safety question.

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
- Search context flags by their misspelling — **`m_verifivation_failed`**, over
  a hundred occurrences; the correct spelling matches nothing.

---

# Part 2 — Concurrency

## The threads that exist

In a running daemon (each verified by its creation site):

| thread(s) | created at |
|---|---|
| **10** P2P/epee ASIO workers | `node_server::run` (`src/p2p/net_node.inl`) — `int thrds_count = 10;` |
| the peers-logger thread | `node_server::run` (`mPeersLoggerThread`) |
| one transient thread **per DNS seed lookup** | `node_server::get_dns_seed_nodes` (`dns_threads`) |
| **2** io threads **per RPC server** | `src/daemon/rpc.h` — `m_server.run(2, false)` |
| one ZMQ thread | `ZmqServer::run` (`src/rpc/zmq_server.cpp`) |
| the Blockchain async pool | `Blockchain::init` (`blockchain.cpp`), running `io_context::run` |
| the shared compute pool | `threadpool::create` (`src/common/threadpool.cpp`) |
| one thread per mining thread, plus the background-mining thread | `miner::start` / `miner::update_autodetection` (`src/cryptonote_basic/miner.cpp`) |
| one thread per download | `download_async` (`src/common/download.cpp`) |
| a stop watchdog | `t_daemon::run` (`src/daemon/daemon.cpp`) |

In a wallet: the `wallet_api` background refresh thread
(`WalletImpl::WalletImpl`, `src/wallet/api/wallet.cpp`), the Trezor
live-refresh thread (`device_trezor::init`), and the
same shared compute pool. **`monero-wallet-rpc` runs exactly one network
thread** (`run(1, true)`), under an explicit comment.

`boost::thread` is the idiom — **there is exactly one `std::thread` in all of
`src/`** (the `arg_prep_blocks_threads` default in `cryptonote_core.cpp`, and
it is only `hardware_concurrency()`). Over `src/` + `contrib/epee`,
`CRITICAL_REGION_LOCAL` (about 200 uses) far outnumbers
`boost::recursive_mutex`, `boost::unique_lock`, `std::mutex` and
`std::lock_guard` (each well under a hundred; `grep -rhoF "NAME" src
contrib/epee | wc -l`).

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

Other stated or structural rules:

- `Blockchain::add_new_block` takes **txpool then blockchain**, in that order,
  deliberately, to avoid deadlocking against a reorg.
- `m_sync_lock` in the protocol handler is **always** taken with
  `boost::try_to_lock`, at every site. Blocking on it would deadlock
  against `m_check_span_queue_mutex`.
- **Nothing held under `m_check_span_queue_mutex` may call a core path that
  takes the txpool lock** — the comment says so.
- Inside the node: `m_host_fails_score_lock` → `m_blocked_hosts_lock` →
  `m_peerlist_lock`.
- In the pool: `m_transactions_lock` → `m_blockchain` → the LMDB `LockedTXN`.
- `handle_alternative_block` takes the txpool lock **while already holding the
  blockchain lock** — the reverse of the documented order. It is safe only
  because of how it is reached; a new caller can break that.

## `epee::critical_section` is a *recursive* mutex

`CRITICAL_REGION_LOCAL(x)` → `boost::unique_lock critical_region_var(x)`, and
`epee::critical_section` is `boost::recursive_mutex`. **Re-locking on the same
thread is normal and intended here**, so "this takes the lock twice" is not by
itself a finding. The generated variable name is fixed, so two in one scope is
a redefinition error.

## Strands, not mutexes, in two places

- **epee networking**: each connection has **two** strands — `m_strand`
  serialising socket reads and writes, and `connection_basic::strand_`
  serialising protocol-handler work. `handle_read` posts to the second
  specifically so queued writes cannot deadlock against it. Per connection at
  most one handler runs at a time; across connections they run in parallel.
- **Dandelion++** (`src/cryptonote_protocol/levin_notify.cpp`): all per-zone
  state (`zone_->map`, `fluffing`, and the per-connection `fluff_txs` and
  `flush_time` in `zone_->contexts`)
  is **strand-confined and not mutex-protected**. Every mutator asserts
  `running_in_this_thread()`. Touching that state from outside the strand is a
  race no lock will catch.

## The threadpool does not guarantee a worker thread

`tools::threadpool` has two process-wide singletons —
`getInstanceForCompute()` and `getInstanceForIO()` (8 threads). Behaviours
that break the obvious mental model:

- **`submit` runs a non-leaf task inline on the caller** when depth > 0 or
  every thread is busy with work already queued.
- **A leaf submit (third argument `true`) is never run inline** — the
  inline path is gated on `!leaf` in `threadpool::submit`, and a leaf job is
  always queued at the front.
- **`submit` throws when called from inside a leaf job** (the `CHECK` on
  `is_leaf` in `threadpool::submit`).
- **`waiter::wait()` drains the queue on the calling thread** (`run(true)`)
  before blocking.
- **`threadpool::waiter::~waiter` calls `wait()`, but too late for locals
  declared after the waiter**: they are destroyed first, so a job that
  captured them by reference can outlive them. Declare the waiter after
  everything its jobs touch.

So "this runs on a worker thread" is never guaranteed, which matters for any
reasoning about reentrancy or thread-local state. `create` spawns `max - 1`
threads because the submitting thread is expected to contribute.

## Thread affinity that is enforced

`BlockchainLMDB` records `m_writer = boost::this_thread::get_id()` in
`batch_start` and `block_wtxn_start`, and re-checks it in `batch_commit`,
`batch_stop`, `batch_abort`, `block_wtxn_start`, `block_wtxn_stop` and
`block_wtxn_abort`. The resize barrier is **lock-free spins** —
`while (creation_gate.test_and_set());` and `while (num_active_txns > 0);` —
sequenced `prevent_new_txns()` → `wait_no_active_txns()` →
`mdb_env_set_mapsize` → `allow_new_txns()`. An early return or throw between
prevent and allow leaks the gate.

**`block_rtxn_start()` silently returns the write transaction** when called on
the writer thread with a write transaction open (batch or `block_wtxn`), so
reads on that thread see uncommitted data.

## The wallet side

**`wallet2` is not internally thread-safe.** Its only per-instance mutex,
`m_daemon_rpc_mutex` (recursive), serialises the HTTP client and
`NodeRPCProxy` — it protects none of `m_transfers`, `m_blockchain` or the
subaddress table. Serialization is the front end's job:

- **simplewallet**: `LOCK_IDLE_SCOPE()` around every command and the idle
  refresh.
- **wallet-rpc**: one network thread, and five `std::atomic`s for the only
  cross-thread interaction (`stop_refresh`).
- **`wallet_api`**: `m_refreshMutex2` in `doRefresh` and the `LOCK_REFRESH()`
  macro — **and this is the one consumer with genuine concurrency.**
  `pauseRefresh()` does not wait for an in-flight refresh (`// TODO
  synchronize access`); `AddressBookImpl`, `SubaddressImpl` and
  `SubaddressAccountImpl` rebuild their row vectors with no mutex at all;
  `TransactionHistoryImpl`'s mutex protects the vector but not the
  `TransactionInfo*` objects it hands out and then deletes.

One cross-cutting inconsistency worth knowing:
`wallet2::process_parsed_blocks` calls `hwdev.generate_key_derivation` from
several threadpool threads **without** holding the `hw::device` lock, while
`check_acc_out_precomp` and `process_new_transaction` take
`boost::unique_lock<hw::device>`.

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
