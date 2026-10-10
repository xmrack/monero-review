# Wallet subsystems

`wallet2` and its three consumers, plus the device abstraction.

**The governing threat model, everywhere in this file:** a user runs a wallet
against a remote node they do not control. The daemon is untrusted and the
keys are in the process. Severity is high because a defect here loses funds or
deanonymises the user directly.

**"Affects the wallet" is not specific enough.** There are three consumers with
genuinely different threat models, and a finding real in one is often
unreachable in another. Always name the one you mean.

Verified against master `160e21504`.

---

## The three consumers

| | `monero-wallet-rpc` | `wallet_api` / libwallet | `monero-wallet-cli` |
|---|---|---|---|
| built from | `src/wallet/wallet_rpc_server.cpp` | `src/wallet/api/` | `src/simplewallet/` |
| driver | an automated client over HTTP | a GUI or mobile app | a human at a terminal |
| errors | JSON-RPC codes in an out-parameter | `status()` / `errorString()` | printed |
| refresh | a 200 ms idle handler on the one RPC thread | a library-owned background thread | an idle thread under `LOCK_IDLE_SCOPE()` |
| human in the loop | **none** | prompts are the GUI's problem | yes, prompts are real |

Consequences worth carrying:

- Anything that **requires user interaction to trigger** may be unreachable
  under wallet-rpc — but anything that **processes daemon responses
  automatically** is *worse* there, because nobody is watching.
- `wallet_api` is the only consumer with genuinely **concurrent** access to
  `wallet2`: a background refresh runs alongside caller-driven calls. State
  that the CLI touches serially can be touched concurrently there.
- `wallet_api` is `EXCLUDE_FROM_ALL`, so a default build does not produce
  it; it is built only when named as a target or pulled in by a dependent
  (`libwallet_api_tests`, added only under `BUILD_GUI_DEPS`, default OFF).

---

## `src/wallet/wallet2.{h,cpp}` — the engine

About 16k lines (`wc -l src/wallet/wallet2.cpp`) in one translation unit. It
owns the account keys, a hashchain of block ids, the `m_transfers` output
set, the payment and transfer maps, the subaddress table; it drives refresh,
builds and signs transactions, and persists two files.

**Two files, two keys.** The keys file is JSON under a password-derived
chacha20 key; the cache file is monero binary serialization under
`derive_cache_key(keys_key, config::HASH_KEY_WALLET_CACHE)` — deliberately not
the same key. Both are written to `<name>.new` and then `tools::replace_file`,
so persistence is atomic. **Neither is authenticated**: chacha20 with a random
IV and no MAC. Tampering is detected only by the deserializer failing.

**Background sync makes it four files and two key hierarchies.** Three modes
-- `BackgroundSyncOff`, `BackgroundSyncReusePassword`,
`BackgroundSyncCustomPassword`, declared in
`src/wallet/wallet2_basic/wallet2_types.h` and re-exported in `tools::wallet2`
-- are parsed from `"off"`, `"reuse-wallet-password"` and `"custom-background-password"` by
`background_sync_type_from_str`, which throws `std::logic_error` on anything
else. In the custom-password mode the wallet keeps `<name>.background` and
`<name>.background.keys` alongside the main pair
(`wallet2::make_background_wallet_file_name`,
`wallet2::make_background_keys_file_name` in `src/wallet/wallet2.cpp`),
encrypted under `m_custom_background_key` -- a **different** key from the main cache, so the
password that opens the background cache is deliberately not the wallet
password.

Four things follow, and a diff can break each of them:

- **The background instance must not hold a spend key.** A separate `wallet2`
  is built in `process_background_cache_on_open` with `m_is_background_wallet
  = true` and `account.forget_spend_key()` (the same call is in
  `get_keys_file_data` when writing the background keys file, and in
  `start_background_sync` on the main account). That call is the entire
  security property of the feature; anything that lets a background
  instance keep or re-derive the spend key defeats it outright.
- **The background cache is untrusted input on the main wallet's open path.**
  `process_background_cache_on_open` loads and merges it when a
  normal wallet is opened, so "the user opened their wallet" reaches a
  deserializer over a second, separately-encrypted file. Everything true of
  the main cache as an attack surface is true of this one.
- **Settings cannot be changed from a background wallet.**
  `THROW_WALLET_EXCEPTION_IF(m_background_syncing || m_is_background_wallet,
  ... "cannot change wallet settings from background wallet")` in
  `wallet2::rewrite`.
- **A missing background file is recreated, not treated as an error**
  (`process_background_cache_on_open`, under "If the background wallet files
  don't exist, recreate them"). A path that recreates on absence is a path
  an attacker can force by deleting.

**Refresh** is traced step by step in `flows.md` §3. The load-bearing summary:
the wallet recomputes every block id from the blob and chains `prev_id`, but
**there is no proof-of-work check anywhere in the wallet** — chaining proves
internal consistency of whatever the node made up. Ownership is decided purely
by local key material, and a received amount is only accepted if the
ECDH-decrypted `(amount, mask)` reopens the Pedersen commitment.

**Invariants worth testing a diff against.**

- The wallet must never take a block id from the daemon; `parsed_block.hash`
  is always the output of `parse_and_validate_block_from_blob` over the blob.
- `process_new_blockchain_entry` only ever appends —
  `height == m_blockchain.size()` is asserted before any transaction is
  processed.
- A reorg deeper than `m_max_reorg_depth` (default 100) aborts the refresh with
  `error::reorg_depth_error` rather than detaching.
- Every `m_transfers` entry with `m_key_image_known` and not
  `m_key_image_partial` has a matching
  `m_key_images` entry and every entry has a matching `m_pub_keys` entry;
  `detach_blockchain` throws if either lookup fails.
- A ring's real member must come back from `/get_outs.bin` with the wallet's
  own stored public key **and** recomputed commitment **and**
  `unlocked == true`.
- Every decoy must be in the main subgroup — both the one-time key and the
  commitment (`rct::isInMainSubgroup` in `tx_add_fake_output`).
- The per-ring `outputs` list must be **sorted by index** before the request
  leaves the wallet; the real pick order lives only in local state.
- Change must go to an address the wallet owns — `sanity_check` throws
  otherwise.
- Multisig nonces are wiped after a single use — `memwipe` under the comment
  "CRITICAL: a nonce may only be used once!" in `wallet2::get_multisig_k`.
  **There is no wallet-level nonce member.**
  The only `m_multisig_k` in the tree is `transfer_details::m_multisig_k`, a
  plain `std::vector<rct::key>` declared in
  `src/wallet/wallet2_basic/wallet2_types.h`, carrying no deprecation
  marker, and it is live state: `wallet2::get_multisig_k` walks
  `m_transfers[idx].m_multisig_k`,
  matches a nonce by its `L = k*G`, hands it out and wipes it in place.
  Two consequences a diff can break. The wipe **leaves a zero entry in the
  vector rather than erasing it**, so the loop's `if (k == rct::zero())
  continue` is what stops a spent nonce being reused — a rewrite that drops
  that test reuses nonces. And `clear_multisig_k_and_store` wipes
  and clears the nonces of every transfer the txset spends and calls
  `store()` under the comment "Must succeed before any
  txset produced with these nonces is exposed", so a change that lets the
  txset out before the store lands is a real finding.
- Daemon error text is mostly not surfaced verbatim when the daemon is
  untrusted — most RPC error sites pass
  `get_rpc_status(m_trusted_daemon, res.status)`. **Not every site does.** In
  `src/wallet/wallet2.cpp`:
  - `wallet2::import_key_images` (its `is_key_image_spent` and
    `gettransactions` calls) uses `THROW_ON_RPC_RESPONSE_ERROR_GENERIC`
    (`src/wallet/wallet_errors.h`), which puts raw `res.status` into
    `wallet_generic_rpc_error::what()`. Not reachable from an untrusted
    daemon; see "Every key-image import with `check_spent` needs a trusted
    daemon" in `refutations.md`.
  - The `get_outs.bin` sites in `get_spend_proof` and `check_spend_proof`
    pass raw `res.status` to `error::get_outs_error`, and
    `get_num_rct_outputs` (`get_output_histogram`) passes raw
    `resp_t.status` to `error::get_histogram_error`. Both types keep the
    status out of `what()`; it appears only in `to_string()`, which
    `throw_wallet_ex` logs.

  Outside `wallet2.cpp`, `src/wallet/node_rpc_proxy.cpp` returns raw
  `res.status` as its error string. Find candidates with
  `grep -n 'THROW_ON_RPC_RESPONSE_ERROR' src/wallet/wallet2.cpp | grep -v get_rpc_status`;
  a new site that copies one of these inherits the leak.

**Traps.**

- **`THROW_WALLET_EXCEPTION_IF` is a bare `if (cond) { … }`** with no
  `do { } while(0)` wrapper — unlike `THROW_WALLET_EXCEPTION`, which has one.
  An `else` after it binds to the macro's hidden `if`.
- **`encrypt_keys(key)` encrypts the *spend* key and decrypts the *view* key**;
  `decrypt_keys` does the reverse. The names describe the spend key only.
- **`hashchain::size()` is a height, not a container size** — it returns
  `m_blockchain.size() + m_offset`, and `operator[]` subtracts the offset.
- **`m_global_output_index` comes from the daemon and is stored unverified.**
  It is unused during scanning and used later to build ring offsets.
- **In the main refresh path the daemon's tx blobs are never checked against
  the block's `tx_hashes`.** The txid recorded on a `transfer_details` comes
  from the block header; the contents come from a separate blob.
- **`should_skip_block` gates scanning on the daemon-supplied block
  timestamp.**
- **`exit(1)` in `wallet2::process_new_transaction`** on the received-amount
  consistency check ("Consistency failure in amounts received") — a library
  function that terminates the host process.
- Most of `wallet2.cpp` before `namespace tools` opens is **two anonymous
  namespaces** (the large one starts with `struct options`); a helper you
  cannot find is probably in there.
- `src/wallet/wallet2_basic/CMakeLists.txt` contains **nothing but a licence
  header** — there is no target; the headers reach the build another way.
- Two independent version numbers govern the cache: `VERSION_FIELD(2)` in the
  native serializer (the `BEGIN_SERIALIZE_OBJECT` block of `tools::wallet2`
  in `src/wallet/wallet2.h`, after `MAGIC_FIELD("monero wallet cache")`) and
  `BOOST_CLASS_VERSION(tools::wallet2, 31)` (same file), plus
  per-struct Boost versions on the nested types. They are bumped independently
  and a field added to one path is not automatically carried by the other, so
  ask which serializer a new cache field is reachable through: the Boost path
  is the `serialize(t_archive &a, const unsigned int ver)` member of
  `tools::wallet2` in `wallet2.h` plus the nested types in
  `src/wallet/wallet2_basic/wallet2_boost_serialization.h`, and the native one
  is the `VERSION_FIELD` block of `wallet2.h` plus
  `src/wallet/wallet2_basic/wallet2_serialization.h`. A field present in
  one and absent from the other reads back default-constructed after a
  round-trip through the other, which is how a wallet silently loses state.
- `tx_construction_data`'s serialized `use_rct` field is a **bitfield carrying
  construction flags** (`construction_flags`: `_use_rct = 1<<0`,
  `_use_view_tags = 1<<1`) under a boolean-sounding name; the in-memory
  `use_rct` member is a plain `bool`.
- `gamma_picker` holds `const std::vector<uint64_t> &rct_offsets` **by
  reference**.
- **MyMonero / light-wallet support is gone.** `light_wallet` appears zero
  times in `wallet2.{h,cpp}`; older write-ups describing it no longer apply.
- `wallet2` is **not internally thread-safe.** Its only per-instance mutex,
  `m_daemon_rpc_mutex`, serialises the HTTP client and `NodeRPCProxy` — it
  protects none of the wallet state (the static `default_daemon_address_lock`
  guards only the process-wide default daemon address).

**Neighbours.** `node_rpc_proxy.cpp` is the caching daemon boundary for scalars
(height, fees, hard forks): height and `get_info` are re-fetched after 30
seconds, the fee estimate per height, and the version and hard-fork data only
after `invalidate()`. `ringdb.cpp` is a separate
LMDB store of previously used rings keyed by key image, so re-spending an
output reuses its ring. A missing key image does not fail `get_rings`: the
`if (dbr == MDB_NOTFOUND) { all_outs.emplace_back(); continue; }` branch
pushes an empty ring and keeps going, so it returns true with exactly one
entry per key image, and throws on an LMDB or decode error. Callers treat
empty as absent — `ringdb::get_ring` via `|| all_outs.front().empty()`, and
`wallet2::get_outs` via `if (!all_outs[i].empty())` when filling
`existing_rings`.

---

## `src/wallet/wallet_rpc_server.*` — `monero-wallet-rpc`

About a hundred method names dispatched by a macro-generated `else if` chain
onto slightly fewer handlers (a few handlers serve two names); count them with
`grep -c 'MAP_JON_RPC_WE' src/wallet/wallet_rpc_server.h`. `main()` is at the
bottom of `wallet_rpc_server.cpp`.

**Threading.** `http_server_impl_base::run(1, true)` — **exactly one network
thread**, under an explicit comment. The only cross-thread callers are
`stop_refresh()` and `send_stop_signal()`, from the signal handler that
`t_daemon::run` installs and from `t_daemon::stop`; `stop_refresh()` touches only the `std::atomic`
members declared in `wallet_rpc_server.h` and, guarded by them, the
`m_wallet` pointer (`m_wallet->shutdown()`).

**Body size.** `m_max_content_length = MAX_RPC_CONTENT_LENGTH * 100` — the
wallet RPC accepts **100 MB** request bodies where the daemon accepts 1 MB.

**Authorisation** is HTTP digest auth in epee plus a coarse `--restricted-rpc`
allowlist, expressed **only as per-handler early returns — there is no central
table**. In `src/wallet/wallet_rpc_server.cpp` the gate takes three forms,
and a grep for any one of them misses the others:
- a literal `if (m_restricted)` return in the handler;
- `CHECK_IF_RESTRICTED_BACKGROUND_SYNCING()`, which expands to
  `CHECK_IF_RESTRICTED_BACKGROUND_SYNCING_BASE(true)` and tests
  `check_restricted && m_restricted` (e.g. `on_set_attribute`,
  `on_tag_accounts`); `CHECK_IF_BACKGROUND_SYNCING()` is the same macro with
  the restricted check off;
- `PRE_VALIDATE_BACKGROUND_SYNC()`, used by the three background-sync
  handlers, which has its own literal `if (m_restricted)`.

Two handlers, `on_get_transfers` and `on_get_transfer_by_txid`, use the
inverted `if (!m_restricted)` to skip only the pool refresh in restricted
mode. A new handler is unrestricted unless it says otherwise.

**Traps.**

- **A missing request field is not an error.** `KV_SERIALIZE` discards the
  serializer's return, so an absent JSON key leaves the value-initialised
  default. Every field needs a validity check in the handler.
- **A JSON string is not accepted where a `uint64_t` is declared.** epee has
  no string-to-integer coercion: such a field hits the generic
  `convert_to_integral<from, to, false>` in
  `contrib/epee/include/storages/portable_storage_val_converters.h`, which
  calls `ASSERT_AND_THROW_WRONG_CONVERSION()`; the throw is caught by the
  plain `try`/`catch` in `BEGIN_KV_SERIALIZE_MAP`'s `load()`
  (`contrib/epee/include/serialization/keyvalue_serialization.h`, reached
  via `PREPARE_OBJECTS_FROM_JSON` in
  `contrib/epee/include/net/http_server_handlers_map2.h`) and the request is
  rejected.
- A handler that returns false without setting `er.code` produces
  `{"error":{"code":0,…}}`; an escaping exception produces
  `{"error":{"code":0,"message":""}}`.
- **`get_tx_key` and `check_tx_key` are not blocked in restricted mode**, while
  `query_key` is.
- **`on_set_daemon` lets an authenticated client point the wallet at an
  arbitrary daemon and set `trusted`.**
- **`on_relay_tx` deserializes a full `tools::wallet2::pending_tx` from
  client-supplied hex** with the monero binary archive, inside a bare
  `catch(...) {}`.
- Command-type names collide with the daemon's: `COMMAND_RPC_GET_HEIGHT` and
  `COMMAND_RPC_START_MINING` exist in both `tools::wallet_rpc` and
  `cryptonote`.
- `tests/fuzz/fuzz_rpc` targets the **daemon** only — `core_rpc_server`
  (`fuzz_rpc.cpp`) and the ZMQ publisher `zmq_pub` (`fuzz_zmq.cpp`). There
  is no wallet-RPC fuzz target.
- `WALLET_RPC_VERSION_MINOR` (`#define` in
  `src/wallet/wallet_rpc_server_commands_defs.h`) must be bumped on **any**
  change to that file; MAJOR bumps reset it.
- Every dispatch-table method name must have a wrapper in
  `utils/python-rpc/framework/wallet.py` or the `check_missing_rpc_methods`
  test fails.

---

## `src/wallet/api/` — `wallet_api` / libwallet

An exception-free, pointer-based façade over `wallet2` in `namespace Monero`.
Only `wallet2_api.h` is installed, and it deliberately includes **no Monero,
Boost or epee headers** — a GUI can compile against it with just the standard
library. Do not add an include there.

**Errors do not propagate as exceptions.** Every public method must be
noexcept-in-practice: `wallet2` throws, the API catches and stores into
`m_status` / `m_errorString` behind `m_statusMutex`. `status()` and
`errorString()` are **two separate lock acquisitions**; only
`statusWithErrorString()` reads them atomically.

**Concurrency is the distinguishing risk.** `WalletImpl` owns a background
refresh thread; `doRefresh` takes `m_refreshMutex2`, and the `LOCK_REFRESH()`
macro brackets caller-driven work. But:

- `pauseRefresh()` **does not wait** for an in-flight refresh — it clears an
  atomic flag, and the source says `// TODO synchronize access`.
- `createTransactionMultDest` brackets its work with
  `pauseRefresh()`/`startRefresh()`; its sibling
  `createSweepUnmixableTransaction` does **neither**.
- Several row containers (`AddressBookImpl`, `SubaddressImpl`,
  `SubaddressAccountImpl`) delete and rebuild their rows with **no mutex at
  all**. `TransactionHistoryImpl` has one, but it protects the vector, not the
  `TransactionInfo*` objects it hands out and later deletes.
- `setListener` carries `// TODO thread synchronization;`.

**Trust.** `doInit` sets `trustedDaemon` purely from
`Utils::isAddressLocal(daemon_address)`. Changing that predicate silently
changes the trust posture of every GUI user.

**Traps.** `Wallet2CallbackImpl` — the whole GUI notification bridge — is
*defined* in `wallet.cpp` and only forward-declared in `wallet.h`. There are
two unrelated `Wallet::init` functions (a static logging bootstrap and an
instance daemon binding). `tr(x)` is defined as `(x)` here — unlike
simplewallet, nothing is translated. `m_password` is a plain `std::string`
member, exposed verbatim by `getPassword()`, never wiped. `loadUnsignedTx`
returns a heap pointer the API gives no disposal method for. `use_ssl` is
forwarded and then never read.

**`checkBackgroundSync()`** guards every call site found by
`grep -n 'checkBackgroundSync(' src/wallet/api/wallet.cpp` — every operation that needs
spend keys or would corrupt the background cache. A new spend-adjacent method
needs it.

---

## `src/simplewallet/` and `src/mnemonics/`

`simplewallet.cpp` is about 12k lines (`wc -l`): the command table, argument parsing, and the
confirmation prompts. The prompts are the point — this is the only consumer
where "the user would notice" is a real control, and it is only a control if
the prompt is actually shown. A flow that batches or automates past a prompt
turns that defence into nothing. `tr()` here **is** a real translation hook,
unlike in `wallet_api`.

`LOCK_IDLE_SCOPE()` (defined at the top of `simplewallet.cpp`) is what
serialises the idle refresh thread against user commands — `wallet2` does
nothing itself.

`src/mnemonics/` is the electrum-style seed: one header per language (each
~1700 lines of word list), plus `electrum-words.cpp` for the checksum and
language detection. The word lists dominate the directory's line count and are
data, not logic — but they are no longer all of it.

**`src/mnemonics/polyseed/` is a second, independent seed scheme with its own
key derivation**, and it is logic: a C++ wrapper over libpolyseed
(`polyseed.cpp`, `data::generate_secret_key` and `data::keygen`), a
PBKDF2-HMAC-SHA256 implementation injected as the polyseed KDF (`pbkdf2.c`,
`crypto_pbkdf2_sha256`), and utf8proc normalisation of user phrases and
passphrases. `src/CMakeLists.txt` adds `mnemonics/polyseed` (target
`polyseed_wrapper`), which `mnemonics` links publicly.
`electrum-words.cpp` also has `words_to_bytes_ex`
(`crypto::ElectrumWords::words_to_bytes_ex`), which decides polyseed versus legacy
from an arbitrary phrase, and `normalize_mnemonic`. A reviewer who reads this
directory as word lists and a checksum will walk straight past a live
key-derivation path.

---

## `src/device/` and `src/device_trezor/`

The abstraction between wallet logic and an external signer.

`hw::device` (`src/device/device.hpp`) is a large pure-virtual interface —
key derivation, subaddress derivation, scalar and point operations, key
images, and the transaction-signing protocol. `device_type` is
`SOFTWARE = 0`, `LEDGER = 1`, `TREZOR = 2`, and `device_protocol_t` is
`PROTOCOL_DEFAULT` / `PROTOCOL_PROXY` (Ledger) / `PROTOCOL_COLD` (Trezor).

Implementations: `device_default.{hpp,cpp}` (software — the default, and what
`account_keys::m_device` points at unless the account was created against a
device), `device_ledger.cpp` (about 2.5k lines, over `device_io_hid`), and
`src/device_trezor/` (protobuf transport, gated by `USE_DEVICE_TREZOR`).

Devices are found through a **registry**: `hw::get_device(descriptor)` over a
process-wide `device_registry` that is `new`ed into a function-local static and
cleared by `atexit`.

**The review question for anything here** is not whether the device is
correct, but **what the host can convince it to do**: which values the device
derives or verifies itself, and which it accepts from the host. Key
derivation, output-index handling and change detection are where a host-supplied
value does damage.

**A concurrency note that spans this and `wallet2`:** `process_parsed_blocks`
calls `hwdev.generate_key_derivation` from several threadpool threads
**without** holding the `hw::device` lock, unlike `process_new_transaction`,
which takes `boost::unique_lock<hw::device>` around its own derivation and
around each `scan_output` call.
Any change that makes a device implementation stateful has to reckon with
that.

---

## Multisig, from the wallet side

The arithmetic lives in `src/multisig/` (see `subsystems-crypto.md`). What
lives here is the transport: `src/wallet/message_store.{h,cpp}` and
`message_transporter.{h,cpp}` move key-exchange and signing messages between
participants.

The security question is almost never the arithmetic — it is
**authentication of configuration**: whether a participant, or someone
impersonating one, can alter the signer set, their addresses, or the
threshold, and whether the other participants would notice. And "would notice"
depends on a confirmation actually being shown, which brings you back to which
of the three consumers you are talking about.
