# Navigating the tree

How to find things here, and the specific ways a search misleads you.

Every recipe below was run against master `3fd0f88c2` (2026-10-25). Paths are relative to
the Monero checkout root.

---

## Before you grep

Four facts change what a search means in this tree:

1. **`.inl` files are implementations.** `src/p2p/net_node.inl` and
   `src/cryptonote_protocol/cryptonote_protocol_handler.inl` (each about
   3000 lines) are the whole P2P node and the whole protocol handler. A tool
   configured for `*.cpp`/`*.h` misses the two most attacker-exposed files in the daemon.
   Include `--include=*.inl` — or with `rg`, `-g '*.inl'` — always.
2. **Most of the interesting code is macro-generated** and does not exist as
   text. See `macros.md`; the short version is that
   `member_do_serialize`, `store`/`load`/`serialize_map`,
   `handle_http_request_map`, `handle_invoke_map`, `operator==` on key types,
   `class Request`, nearly every RPC `request` type (a `struct_init` typedef of
   `request_t`), and every `m_cur_*` in the LMDB backend are all invisible to
   grep.
3. **`git grep` and `git ls-files` cannot see inside submodules.**
   The seven `.gitmodules` entries — `external/randomx`, `supercop`,
   `rapidjson`, `gtest`, `mx25519`, `polyseed` and `utf8proc` — are separate
   repositories; use `rg` or `find` there. A submodule the run did not check
   out is simply absent.
   The FCMP++ prover/verifier is not in the tree at all: `src/fcmp_pp/fcmp_pp_rust`
   is a C-ABI shim (`lib.rs`, `fcmp++.h`) over `monero-oxide` crates pinned by
   `rev` in its `Cargo.toml`. The review pipeline writes the pinned sources to
   `rust-deps/<repo>/` in the checkout (e.g. `rust-deps/monero-oxide/`), and
   crates.io packages the PR adds or bumps, plus the registry original of any
   `[patch.crates-io]` replacement, under `rust-deps/crates/<name>-<version>/`.
   `RUST_DEPS.md` at the tree root lists
   what was fetched, at which revision, what a PR bumps, and what was not
   fetched. Report a dependency listed as not fetched as not covered.
4. **Spelling.** The consensus verdict flag is **`m_verifivation_failed`**
   (and `m_verifivation_impossible`). The correct spelling matches nothing.

## Prefer the symbol index when a run has one

Some review runs build `tags` (ctags), `cscope.out` (source tree excluding
`tests/`) and `tests.out` (the `tests/` tree). Check with a glob before
relying on them.

```
readtags -t tags <symbol>          # where a symbol is DEFINED — better than cscope for C++
cscope -d -L3 <function>           # functions calling this function
cscope -d -f tests.out -L3 <fn>    # callers in tests/, a separate database
rtool callers <function>           # both databases plus every git grep -w match
```

A hit is reliable. **A miss is not.** cscope does not see a call written
inside a macro argument, and most guards here are exactly that:
every call to `passes_max_size_check` sits inside
`CHECK_AND_ASSERT_MES(...)`, and `cscope -L3` returns none of them. Before
calling anything uncalled, read the `git grep -w` matches as well; `rtool
callers` prints both. A miss on `cscope.out` alone says nothing about tests
either: that is `tests.out`.

---

## Recipes

**Where is a type's serializer, when grepping the function name finds
nothing?**
```
rg -n "BEGIN_SERIALIZE(_OBJECT)?(_FN)?\(" src/ -g '*.h' -g '*.cpp'
rg -n "BEGIN_KV_SERIALIZE_MAP\(\)" src/ contrib/
```
The body is the lines up to the matching `END_*`.

**What byte on the wire maps to which C++ type?**
```
rg -n "^VARIANT_TAG\(binary_archive" src/
```
The mapping exists only on those lines. For `tx_extra` they sit at the
*bottom* of `src/cryptonote_basic/tx_extra.h`, at global scope, far from the
structs.

**Which types are raw-`memcpy` serialized?**
```
rg -n "^BLOB_SERIALIZER(_FORCED)?\(" src/
```

**Where does an allocation get bounded against the remaining input?**
```
rg -n "remaining_bytes\(\)" src/                                    # the src/ archive
rg -n "CHECK_AND_ASSERT_THROW_MES" contrib/epee/include/storages/portable_storage_from_bin.h
rg -n "PREPARE_CUSTOM_VECTOR_SERIALIZATION" src/                    # bounded only by its min_wire argument (0 = no bound)
```

**Which network-reachable call sites parse epee binary, and do they pass
limits?**
```
rg -n 'load_from_binary\(|load_t_from_binary\(' contrib/epee/include src
```
See the three-regime table in `flows.md` — the answer is not uniform.

**What is the complete set of P2P commands, their ids and their size caps?**
```
rg -n 'P2P_COMMANDS_POOL_BASE' src/p2p/p2p_protocol_defs.h
rg -n 'BC_COMMANDS_POOL_BASE' src/cryptonote_protocol/cryptonote_protocol_defs.h
rg -n -A1 'case (nodetool|cryptonote)::' src/cryptonote_basic/connection_context.cpp
```
The caps are `cryptonote_connection_context::get_max_bytes`, enforced in
`contrib/epee/include/net/levin_protocol_handler_async.h`; an ID not listed
there gets `SIZE_MAX`.

**Where is every protocol handler defined?**
```
rg -n 't_cryptonote_protocol_handler<t_core>::' src/cryptonote_protocol/cryptonote_protocol_handler.inl
```

**Which conditions drop a peer, and how hard?**
```
rg -n 'drop_connection|drop_connection_with_score|drop_connections' src/cryptonote_protocol/cryptonote_protocol_handler.inl
```

**Where is a lock taken, and in what order?**
```
rg -n 'Order of locking' src/                    # the one documented statement
rg -n 'CRITICAL_REGION_(LOCAL1?|BEGIN)\(|\.(un)?lock\(\)|m_sync_lock|m_incoming_tx_lock|m_blockchain_lock' src/cryptonote_core src/cryptonote_protocol
```
The documented order (`blockchain.cpp`, in `prepare_handle_incoming_blocks`) is
`m_incoming_tx_lock`, then the txpool lock, then `m_blockchain_lock`.

**Which functions in `blockchain.cpp` exist, in file order?**
```
grep -nE '^[^ /#].*\bBlockchain::~?\w+\(' src/cryptonote_core/blockchain.cpp
```
`db_lmdb.cpp` and `wallet2.cpp` respond to the same trick with
`BlockchainLMDB::` and `wallet2::`. (A character class without digits, such
as `[a-z_:<>, ]*`, silently drops every `uint64_t`-returning function.)
`cryptonote_format_utils.cpp` puts a `//---` separator before most (not all)
functions, so `grep -n '^\s*//---'` enumerates most of it.

**Where does this unit gate on a hard-fork version?**
```
rg -n 'HF_VERSION_|hf_version|get_current_hard_fork_version|get_ideal_version' <dir>
```
Remember `RX_BLOCK_VERSION` lives in `src/crypto/hash-def.h`, not in
`cryptonote_config.h` and not in `hash-ops.h` either. It is a bare `#define`,
so it does not answer to the `HF_VERSION_` grep above; a RandomX gating change
is invisible to that pattern. The per-network fork heights are tables in
`src/hardforks/hardforks.cpp`.

**Where does the wallet talk to the daemon?**
```
rg -n 'invoke_http_bin|invoke_http_json_rpc|invoke_http_json\(' src/wallet/wallet2.cpp src/wallet/node_rpc_proxy.cpp
```

**Which RPC methods are hidden in restricted mode?**
```
rg -n 'MAP_URI_AUTO_JON2_IF|MAP_JON_RPC_WE_IF' src/rpc/core_rpc_server.h
rg -n 'm_restricted' src/rpc/core_rpc_server.cpp        # the in-handler caps
```
For wallet-rpc there is no table — restriction is a per-handler
`if (m_restricted)` early return, or the same check inside
`CHECK_IF_RESTRICTED_BACKGROUND_SYNCING()` / `PRE_VALIDATE_BACKGROUND_SYNC()`
(`src/wallet/wallet_rpc_server.cpp`).

**What log category does this file write to?**
```
grep -n 'define MONERO_DEFAULT_LOG_CATEGORY' <file>
grep -rh 'define MONERO_DEFAULT_LOG_CATEGORY' src/ contrib/epee/ | sort | uniq -c | sort -rn
```
Grepping for the category *string* finds only the `#define`, never the call
sites.

**Which tests cover this?**
```
rg -n '^TEST(_F)?\(' tests/unit_tests/<area>.cpp
grep -n '^\s*GENERATE_AND_PLAY(' tests/core_tests/chaingen_main.cpp
ls tests/fuzz/
```

**What is the value of a constant?**
```
grep -n 'HF_VERSION_\|^#define ' src/cryptonote_config.h
```
The address prefixes, default ports, `NETWORK_ID` and genesis constants are
declared three times, in `namespace config`, `config::testnet` and
`config::stagenet`; the other `config::` constants (fees, `HASH_KEY_*`
domain separators, `MULTISIG_MAX_SIGNERS`) only once.

**Expand the macros when reading is not enough.**
```
g++ -E -I contrib/epee/include -I src -I external/easylogging++ -std=c++17 \
    src/rpc/core_rpc_server_commands_defs.h | grep -o 'selector<[^>]*>::serialize[^(]*'
```
Expand a file that **uses** a macro, not the one that defines it. Output is
enormous — always pipe through `grep`.

---

## Where things live when the name does not suggest it

| looking for | it is in |
|---|---|
| the P2P node's implementation | `src/p2p/net_node.inl`, emitted from `src/rpc/instantiations.cpp` |
| the protocol handler's implementation | `src/cryptonote_protocol/cryptonote_protocol_handler.inl`, same |
| the consensus wire format | the `BEGIN_SERIALIZE` bodies in `src/cryptonote_basic/cryptonote_basic.h` |
| the rct consensus deserializer | `serialize_rctsig_base` / `serialize_rctsig_prunable` in `src/ringct/rctTypes.h` — **not** the `BEGIN_SERIALIZE_OBJECT` block in the same file |
| `memwipe`, `wipeable_string` | `contrib/epee`, not `src/common` |
| the alt-chain state | the LMDB `alt_blocks` table — there is no in-memory map |
| the RPC URI table | `src/rpc/core_rpc_server.h`, not the `.cpp` |
| the wallet cache struct definitions | `src/wallet/wallet2_basic/wallet2_types.h`; their serializers are in two *other* files |
| `parse_hash256` | the **global** namespace, bottom of `cryptonote_basic_impl.h` |
| the C++ LMDB wrapper (`lmdb::database`) | `src/lmdb/` — **not** the block store, which is `src/blockchain_db/lmdb/` |
| the RandomX shim | `src/crypto/rx-slow-hash.c`; there is no `rx-slow-hash.h`, the declarations are in `hash-ops.h` |
| `slow_hash_allocate_state` | declared in no header at all — callers (`blockchain.cpp`, `miner.cpp`) write a local `extern "C"` |
| FCMP++ / curve trees | `src/fcmp_pp/` (`curve_trees`, `tower_cycle`, `fcmp_pp_crypto`) over the Rust FFI. On master nothing outside `src/fcmp_pp` and `tests/` includes it; `ringct` only links it. `src/carrot_core` and `src/carrot_impl` are not on master; only Carrot-spec primitives are (`src/crypto/x25519.cpp`, `ge_p3_to_x25519` in `crypto-ops.h`) |

## Things that look like one thing and are another

- **`m_cur_blocks`** and its siblings (`grep '#define m_cur_'
  src/blockchain_db/lmdb/db_lmdb.h`) look like members; they are macros for
  `m_cursors->m_txc_blocks` and the like.
- **`TXN_PREFIX_RDONLY()`** declares locals named `m_txn` and `m_cursors` that
  shadow the members.
- **`/get_transaction_pool_hashes.bin`** is a JSON endpoint despite the
  suffix.
- **`LOG_PRINT_L0`** is a warning, not level 0.
- **`DISABLE_VS_WARNINGS(x)`** expands to nothing on every compiler.
- **`daemonize::t_core::run()`** (`src/daemon/core.h`) returns true and does nothing.
- **`i18n_translate`** (`src/common/i18n.h`) returns its argument unchanged;
  every `tr()` in the tree (the per-class wrappers, `src/wallet/api`'s
  `#define tr(x) (x)`, simplewallet's) is a no-op.
- **`rx_slow_hash_allocate_state`** is an empty function.
- **`hashchain::size()`** returns a height, not a count.
- **`m_expected_heights`** is a vector of hashes.
- **`is_rct_bulletproof()`** is false for `RCTTypeBulletproofPlus`.
- **`core::add_new_tx` returns true** for a transaction already in the pool or
  the chain, without verifying it.
- **`WalletImpl::checkBackgroundSync()` returns true** when the operation must be refused.
- **An engaged `boost::optional<std::string>`** from `node_rpc_proxy` is the
  *error*.

## Before you claim "nothing calls this"

Check, in order: an `.inl` file; a macro that generates the caller
(`HANDLE_NOTIFY_T2`, `BEGIN_URI_MAP2`, `BEGIN_KV_SERIALIZE_MAP`,
`CRYPTO_MAKE_HASHABLE`, `INITIALIZER`); an explicit template instantiation
(`src/rpc/instantiations.cpp`); a submodule that `git grep` cannot see; and
the `tests/` cscope database, which the main one excludes.

`rct::verPointsForTorsion` is the worked example: it really does have no
production caller — but that conclusion took checking all five.
