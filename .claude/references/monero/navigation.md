# Navigating the tree

How to find things here, and the specific ways a search misleads you.

Every recipe below was run against master `3d3920d7`. Paths are relative to
the Monero checkout root.

---

## Before you grep

Four facts change what a search means in this tree:

1. **`.inl` files are implementations.** `src/p2p/net_node.inl` (3188 lines)
   and `src/cryptonote_protocol/cryptonote_protocol_handler.inl` (2917) are
   the whole P2P node and the whole protocol handler. A tool configured for
   `*.cpp`/`*.h` misses the two most attacker-exposed files in the daemon.
   Include `--include=*.inl` — or with `rg`, `-g '*.inl'` — always.
2. **Most of the interesting code is macro-generated** and does not exist as
   text. See `macros.md`; the short version is that
   `member_do_serialize`, `store`/`load`/`serialize_map`,
   `handle_http_request_map`, `handle_invoke_map`, `operator==` on key types,
   `class Request`, `struct request`, and every `m_cur_*` in the LMDB backend
   are all invisible to grep.
3. **`git grep` and `git ls-files` cannot see inside submodules.**
   `external/randomx`, `supercop`, `rapidjson` and `gtest` are separate
   repositories — use `rg` or `find` there.
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
```

A hit is reliable. **A miss is not** — and a miss on `cscope.out` alone means
no *production* caller, not no caller.

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
rg -n "PREPARE_CUSTOM_VECTOR_SERIALIZATION" src/                    # the ones with NO bound
```

**Which network-reachable call sites parse epee binary, and do they pass
limits?**
```
rg -n 'load_from_binary\(|load_t_from_binary\(' contrib/epee/include src
```
See the three-regime table in `flows.md` — the answer is not uniform.

**What is the complete set of P2P commands, their ids and their size caps?**
```
rg -n 'BC_COMMANDS_POOL_BASE' src/cryptonote_protocol/cryptonote_protocol_defs.h
rg -n -A1 'case cryptonote::NOTIFY' src/cryptonote_basic/connection_context.cpp
```

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
rg -n 'CRITICAL_REGION_LOCAL1?\(|m_sync_lock|m_incoming_tx_lock|m_blockchain_lock' src/cryptonote_core src/cryptonote_protocol
```

**Which functions in `blockchain.cpp` exist, in file order?**
```
grep -n "^[a-z_:<>, ]*Blockchain::" src/cryptonote_core/blockchain.cpp
```
`db_lmdb.cpp` (5769 lines) and `wallet2.cpp` (15450) respond to the same
trick with `BlockchainLMDB::` and `wallet2::`.
`cryptonote_format_utils.cpp` uses a strict `//---` separator between every
function, so `grep -n '^\s*//---'` enumerates it.

**Where does this unit gate on a hard-fork version?**
```
rg -n 'HF_VERSION_|hf_version|get_current_hard_fork_version|get_ideal_version' <dir>
```
Remember `RX_BLOCK_VERSION` lives in `src/crypto/hash-ops.h`, not
`cryptonote_config.h`.

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
`if (m_restricted)` early return.

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
Remember the same names are declared three times, in `namespace config`,
`config::testnet` and `config::stagenet`.

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
| `slow_hash_allocate_state` | declared in no header at all — callers write a local `extern "C"` |

## Things that look like one thing and are another

- **`m_cur_blocks`** and 17 siblings look like members; they are macros for
  `m_cursors->m_txc_blocks`.
- **`TXN_PREFIX_RDONLY()`** declares locals named `m_txn` and `m_cursors` that
  shadow the members.
- **`/get_transaction_pool_hashes.bin`** is a JSON endpoint despite the
  suffix.
- **`LOG_PRINT_L0`** is a warning, not level 0.
- **`DISABLE_VS_WARNINGS(x)`** expands to nothing on every compiler.
- **`t_core::run()`** returns true and does nothing.
- **`i18n_translate`** returns its argument unchanged; every `tr()` in the
  daemon is a no-op (in simplewallet it is real).
- **`rx_slow_hash_allocate_state`** is an empty function.
- **`hashchain::size()`** returns a height, not a count.
- **`m_expected_heights`** is a vector of hashes.
- **`is_rct_bulletproof()`** is false for `RCTTypeBulletproofPlus`.
- **`add_new_tx` returns true** for a transaction that was already there.
- **`checkBackgroundSync()` returns true** when the operation must be refused.
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
