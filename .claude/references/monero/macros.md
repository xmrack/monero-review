# The macro families

Monero is a macro-DSL codebase. Almost nothing that matters on the wire is
written as ordinary C++, and almost none of the generated functions can be
found by grepping for their names.

**Read this before believing a grep result**, and before saying "nothing calls
this" or "this field is unvalidated".

Verified against master `8308dee67` (2026-10-13).

To count uses of a macro, run
`grep -rhoP "(?<![A-Za-z_])NAME\(" src contrib tests | wc -l`; the count
includes the macro's own definition line.

---

## The four serialization DSLs

They coexist, they share no vocabulary, and **the one nearest a struct's
definition is often not the one that runs**.

### 1. `src/serialization/` — consensus binary

`src/serialization/serialization.h`

| macro | generates |
|---|---|
| `BEGIN_SERIALIZE_OBJECT()` | `member_do_serialize()` (calls `begin_object` / `do_serialize_object` / `end_object`) **and then opens** `do_serialize_object()` |
| `BEGIN_SERIALIZE()` | only `member_do_serialize()` — no object framing |
| `BEGIN_SERIALIZE_OBJECT_FN(stype)` | a **free** `do_serialize_object(Archive<W>&, stype& v)` |
| `BEGIN_SERIALIZE_FN(stype)` | a free `do_serialize(Archive<W>&, stype& v)` |
| `END_SERIALIZE()` | `return ar.good(); }` |

Field macros: `FIELD(f)`, `FIELD_N(t,f)`, `FIELD_F(f)` = `FIELD_N(#f, v.f)`
(for the `_FN` forms), `FIELDS(f)` (no tag), `VARINT_FIELD(f)`,
`VARINT_FIELD_N`, `VARINT_FIELD_F`, `MAGIC_FIELD(m)`, `VERSION_FIELD(v)`,
`CONTAINER_FIELD_CAPPED(f, c)`,
`PREPARE_CUSTOM_VECTOR_SERIALIZATION(size, vec, min_wire)`.

Trait macros: `BLOB_SERIALIZER(T)` / `BLOB_SERIALIZER_FORCED(T)` route `T`
onto the raw `memcpy` overload; `VARIANT_TAG(Archive, Type, Tag)`
binds a wire byte to a C++ type.

- `BEGIN_SERIALIZE_OBJECT()` blocks outnumber `BEGIN_SERIALIZE()` blocks
  several to one.
- **The field name is decorative here.** `binary_archive_base::tag(const char*)`
  is `{ }` (`src/serialization/binary_archive.h`), as are `begin_object` and
  `end_object`. So `FIELD(x)` and `FIELD_N("y", x)` produce identical bytes,
  and the name only surfaces in `json_archive` / `debug_archive`. **The format
  is positional** — when a member is added, check field *position*, not name.
- **Every `FIELD` line is a control-flow exit** — it expands to
  `if (!r || !ar.good()) return false;`.
- `VERSION_FIELD(n)` **declares a local `version`** that escapes the macro so
  the lines below can branch on it, and it never bounds the value upward.
  `MAGIC_FIELD(m)` likewise declares a local `magic`.
- **Allocation bounds.** Generic containers (`do_serialize_container`,
  `src/serialization/container.h`) fail if the element count exceeds the cap
  or `ar.remaining_bytes()`, i.e. they assume at least one byte per element.
  `PREPARE_CUSTOM_VECTOR_SERIALIZATION` resizes to `size` after checking
  `remaining_bytes() / size >= min_wire`; a `min_wire` of `0` (the v1
  `signatures` outer vector in `transaction`'s serializer, sized from
  `vin.size()`) skips the check.
- Outside `src/serialization/`, grepping for `member_do_serialize` finds only
  the four hand-written overloads in `src/cryptonote_basic/tx_extra.h`.

### 2. `contrib/epee/…/keyvalue_serialization.h` — RPC and P2P

`BEGIN_KV_SERIALIZE_MAP()` (several hundred blocks) injects `public:` and
generates **four** members: `store()` (declared `const`, and `const_cast`s
`*this`), `_load()`, `load()` (same as `_load` but wrapped in
try/catch logging "Exception on unserializing"), and
`serialize_map<bool is_store, class t_storage>`.

Field macros, most-used first: `KV_SERIALIZE`, `KV_SERIALIZE_OPT`,
`KV_SERIALIZE_PARENT`, `KV_SERIALIZE_CONTAINER_POD_AS_BLOB`,
`KV_SERIALIZE_VAL_POD_AS_BLOB`, and the `_N` and `_FORCE` variants.
`KV_SERIALIZE(v)` → `KV_SERIALIZE_N(v, "v")` →
`epee::serialization::selector<is_store>::serialize(this_ref.v, stg, hparent_section, "v")`.

- **The wire key is the stringized member name.** Renaming a C++ member renames
  the JSON field.
- **`KV_SERIALIZE` discards the serializer's return.** A missing key on load is
  **not an error** — the member keeps its value-initialised default. Every
  request field needs a validity check in the handler.
  The exceptions: `KV_SERIALIZE_PARENT` does check and `return false`, and the
  `_OPT` forms check and call `epee::serialize_default`.
- **`KV_SERIALIZE_OPT` changes the *store* side too**: `if (is_store &&
  this_ref.variable == default_value) break;`. Switching a field from
  `KV_SERIALIZE` to `KV_SERIALIZE_OPT` makes it vanish from responses whenever
  it holds the default. `KV_SERIALIZE_VAL_POD_AS_BLOB_OPT_N` has no such
  short-circuit, so the two "OPT" families are **not symmetric**.
- **`typedef epee::misc_utils::struct_init<request_t> request;`** means
  `COMMAND_RPC_X::request` and `::request_t` are *different types*, and the
  zero-initialisation of every field comes from that typedef (and from the
  `boost::value_initialized` the dispatch macros wrap around requests), not
  from member initialisers. Not every KV block has a `struct_init<` wrapper.
  Container elements loaded by epee are value-initialised
  (`unserialize_stl_container_t_obj` constructs `value_type()`), but a payload
  struct declared as a plain local (`T x;`) in handler code is not, so its
  scalars really are uninitialised.
- **Only the top level catches.** The entry points (`load_t_from_json`,
  `load_t_from_binary`, `buff_to_t_adapter`) call `load()`; nested objects
  and container elements use `_load()`, so a throw anywhere inside fails the
  whole parse. `unserialize_stl_container_t_obj` inserts every element even
  when that element's `_load` returned false, and ORs the results.

### 3. `contrib/epee/…/serialization/wire/` — the newest, and write-only

`WIRE_BEGIN_MAP` / `WIRE_END_MAP` generate `read_bytes` / `write_bytes` /
`wire_map` (`wire/fwd.h`); `WIRE_DEFINE_OBJECT` (`wire.h`) generates only
`write_bytes`. `WIRE_FIELD(name)` becomes
`::wire::field("name", std::ref(self.name))`, so a JSON key is findable only as
the macro argument.

The only `.cpp` users under `src/` are `src/rpc/zmq_pub.cpp` (calls
`wire::object` / `wire::field` directly) and
`src/cryptonote_core/cryptonote_tx_utils.cpp` (`WIRE_FIELD`); headers
`src/crypto/wire.h` and `cryptonote_tx_utils.h` declare the types.
**`wire::reader` and `wire::json_reader` are forward-declared and never
defined** (`contrib/epee/src/wire/json/` has only `write.cpp`) — the read side
does not exist on master.

### 4. `boost::serialization` — persisted local state

Hand-written `serialize()` free functions plus `BOOST_CLASS_VERSION`
(`grep -rn BOOST_CLASS_VERSION src` for current versions; `tools::wallet2`,
the `wallet2_basic::*` types in `wallet2_boost_serialization.h`, and
`nodetool::peerlist_entry` among them). This is the **third** serializer for
several of the same types.

> **The multi-serializer trap, concretely.** `rct::rctSigBase` has a
> `BEGIN_SERIALIZE_OBJECT()` block in `rctTypes.h` **and** the member template
> `serialize_rctsig_base`. The consensus path uses only the latter. A `FIELD()`
> added to the former changes nothing on the wire.
> Likewise `transfer_details` carries both a `BEGIN_SERIALIZE_OBJECT_FN` block
> (in `src/wallet/wallet2_basic/wallet2_serialization.h`, not next to the type) and a Boost hook.
> **Before judging a change to any type that crosses a wire or a disk,
> enumerate all of its serializers.**

---

## Dispatch tables — there is no runtime registration

| macro family | defined in | generates |
|---|---|---|
| `BEGIN_URI_MAP2` / `MAP_URI_AUTO_JON2[_IF]` / `MAP_URI_AUTO_BIN2` | `contrib/epee/include/net/http_server_handlers_map2.h` | `handle_http_request_map()` — a chain of `else if` |
| `BEGIN_JSON_RPC_MAP` / `MAP_JON_RPC` / `MAP_JON_RPC_WE[_IF]` | same | another `else if` chain on the method name |
| `CHAIN_HTTP_TO_MAP2` | same | `handle_http_request()` |
| `BEGIN_INVOKE_MAP2` / `HANDLE_INVOKE_T2` / `HANDLE_NOTIFY_T2` / `CHAIN_INVOKE_MAP_TO_OBJ_FORCE_CONTEXT` | `contrib/epee/include/storages/levin_abstract_invoke2.h` | `handle_invoke_map()`, a run of `if (… ID == command) return …` checked against `is_notify` |
| `BEGIN_RPC_MESSAGE_CLASS` / `_REQUEST` / `_RESPONSE` | `src/rpc/daemon_messages.h` | the ZMQ `Request` / `Response` classes |

Consequences:

- **A URI string or JSON-RPC method name appears once on the server side**, in
  the table (client call sites in `wallet2.cpp` / `node_rpc_proxy.cpp` may
  repeat it). Grepping for the handler finds its declaration and definition
  but not the URI.
- **The method-level restricted-mode gate is the `_IF` suffix.**
  `MAP_URI_AUTO_JON2_IF(..., !m_restricted)` versus `MAP_URI_AUTO_JON2(...)`.
  Dropping the `_IF` and its condition from a table line silently exposes a
  method. A false condition falls through: a URI ends in 404, a JSON-RPC
  method in "Method not found". There is **no `MAP_URI_AUTO_BIN2_IF`**, so
  every `.bin` endpoint is reachable in restricted mode and any restriction is
  in the handler body (`const bool restricted = m_restricted && ctx;`, which
  is also how handlers trim output and cap request sizes).
- `MAP_URI_AUTO_BIN2` calls `load_t_from_binary` with **no `limits_t`**, unlike
  the Levin adapters (`default_levin_limits`) and the client side
  (`default_http_bin_limits`).
- Exceptions from a handler are caught inside the map entry (HTTP 500 /
  JSON-RPC error), and `CHAIN_HTTP_TO_MAP2` catches anything else as 500.
- **The HTTP chains are opened by `if (false) return true;` and order
  matters.** An entry added after a matching one is dead code that compiles
  cleanly. The Levin map returns on the first match, with the same effect.
- `node_server`'s map (`src/p2p/net_node.h`) first returns early for
  `is_filtered_command`, handles the four P2P commands, then chains into the
  protocol handler's map (`cryptonote_protocol_handler.h`).
- A Levin command with no matching entry logs "Unknown command" and returns
  `LEVIN_OK` for notifies (a silent no-op) or
  `LEVIN_ERROR_CONNECTION_HANDLER_NOT_DEFINED` for invokes. All protocol
  handler commands are notifies, so an invoke carrying one of their IDs is
  unhandled.
- `class Request` / `class Response` appear in `daemon_messages.h` only
  inside the `BEGIN_RPC_MESSAGE_REQUEST` / `_RESPONSE` macro bodies, never at
  a message class.

---

## Failure macros — function exits with no `return` or `throw` token

Most-used first:

| macro | behaviour |
|---|---|
| `CHECK_AND_ASSERT_THROW_MES(expr, msg)` | log then **throw `std::runtime_error`** |
| `CHECK_AND_ASSERT_MES(expr, ret, msg)` | `LOG_ERROR` then **`return ret`** |
| `THROW_WALLET_EXCEPTION_IF(cond, type, …)` | throw a typed `tools::error` with `__FILE__:__LINE__` |
| `ASSERT_MES_AND_THROW(msg)` | no condition: log then `throw std::runtime_error` |
| `CHECK_AND_NO_ASSERT_MES*` | logs at `LOG_PRINT_L0/L1` instead, still returns |
| `CHECK_AND_ASSERT(expr, ret)` | **silent** return, no log |
| `CHECK_AND_ASSERT_MES_NO_RET(expr, msg)` | logs then bare `return;` |
| `CHECK_AND_ASSERT_MES2` | logs and does **not** return (defined, no callers) |
| `MONERO_PRECOND` / `MONERO_CHECK` / `MONERO_THROW` / `MONERO_UNWRAP` | `expect<T>` dialect |

**Read every one of these lines as a `return` or a `throw`.** A grep for
`return false` in a validation function misses most of its failure paths. When
reviewing a refactor that moves code across such a line, check that cleanup and
unlock ordering still hold.

**`THROW_WALLET_EXCEPTION_IF` is a bare `if (cond) { … }`** — no
`do { } while(0)` — while its sibling `THROW_WALLET_EXCEPTION` *is* wrapped.
Putting the `_IF` form before an `else` rebinds that `else` to the macro's
hidden `if`. Insist on braces.

**The dialects are geographic**, and suggesting the wrong one is against the
grain. Roughly, by subtree: `cryptonote_core` and `cryptonote_basic` are
mostly `CHECK_AND_ASSERT_MES`; `ringct` mixes it with
`CHECK_AND_ASSERT_THROW_MES`; `multisig` and `fcmp_pp` are almost entirely
`CHECK_AND_ASSERT_THROW_MES`; `wallet` is dominated by
`THROW_WALLET_EXCEPTION_IF`; `blockchain_db` uses none of the three (it uses
`throw0`/`throw1`). In `src/fcmp_pp/tower_cycle.cpp`, `CHECK_FFI_RES` wraps
`CHECK_AND_ASSERT_THROW_MES(r == 0, …)` on a local `r`, so those FFI throw
sites do not match a grep for the inner macro. Per-subtree counts:
`grep -rhoP "(?<![A-Za-z_])CHECK_AND_ASSERT_MES\(" src/<dir> | wc -l`.
**`src/crypto` uses none of them** — no epee check or log macros, dozens of
raw `assert(`.
The `expect<T>` dialect lives only in `src/common`, `src/net`, `src/lmdb`,
`src/rpc/zmq*`, and the address parsing in `src/p2p` (`net_node.cpp`,
`net_node.inl`, `net_peerlist_boost_serialization.h`) and
`src/daemon/command_parser_executor.cpp` that consumes `src/net`.

`TRY_ENTRY()` / `CATCH_ENTRY(location, ret)` / `CATCH_ENTRY_L0..L4` /
`CATCH_ENTRY_SWALLOW_EX` are an **unbalanced brace pair split across two
macros** — a diff hunk showing only one looks syntactically broken. They catch
`std::exception` and `...`, log at error, and `return ret` (or, for
`_SWALLOW_EX`, continue). The `_L0..L4` suffix suggests a log level and
controls nothing.

---

## Locking, logging and timing

**`CRITICAL_REGION_LOCAL(x)`** (`contrib/epee/include/syncobj.h`, about 200 uses)
→ `boost::unique_lock critical_region_var(x)`. Note:

- The `#define` has **two spaces** after it, so `grep '^#define CRITICAL_REGION_LOCAL'`
  misses it.
- **The lock variable always has the same name** (`critical_region_var`), so
  two in one scope is a redefinition error, and grepping for a lock variable
  is useless. `CRITICAL_REGION_LOCAL1` names its variable
  `critical_region_var1`, which is how a second lock coexists in one scope.
- `CRITICAL_REGION_LOCAL1` and `CRITICAL_REGION_BEGIN` insert a
  `g_test_dbg_lock_sleep()` debug delay; plain `CRITICAL_REGION_LOCAL` does
  not. `CRITICAL_REGION_BEGIN` opens a brace that `CRITICAL_REGION_END()`
  closes.
- Not every acquisition is a macro: `blockchain.cpp` also calls
  `m_tx_pool.lock()` and `m_blockchain_lock.lock()` / `unlock()` directly.
- It relies on C++17 CTAD — there is no template argument.

**Logging.** `MERROR` / `MWARNING` / `MINFO` / `MDEBUG` / `MTRACE` →
`MCERROR(MONERO_DEFAULT_LOG_CATEGORY, x)` → … → `MCLOG_TYPE`, which wraps
everything in `if (el::Loggers::allowed(level, cat))`.

- **Arguments are only evaluated if the category and level pass.** Never put a
  needed side effect in a log statement.
- **The category comes from a per-file `#define`, not the call site.** There
  are over a hundred definition sites, each immediately preceded by `#undef`,
  and dozens are in *headers*, so including one changes the category for the
  includer (`grep -rn "#define MONERO_DEFAULT_LOG_CATEGORY" src contrib/epee`).
- **`LOG_PRINT_L0` is `MWARNING`.** `L1` → `MINFO`, `L2` → `MDEBUG`, `L3`/`L4`
  → `MTRACE`. Reading a change from `L0` to `L1` as "made it noisier" is
  backwards.
- `MGINFO` and friends hardcode `"global"`, ignoring the file's category.
- Most-used over `src/` + `contrib/epee`: `MERROR`, `MDEBUG`, `LOG_ERROR`,
  `MINFO`, `LOG_PRINT_L3`, `LOG_PRINT_L0`. The modern M\* family leads (in
  `src/` by well under two to one over `LOG_PRINT_L*`), and `contrib/epee` is
  mostly converted.
- The M\* macros are **not variadic**, so a top-level comma in the logged
  expression is a compile error.

**`PERF_TIMER(name)`** declares `pt_##name`, an RAII object whose log category
is `"perf." MONERO_DEFAULT_LOG_CATEGORY` built by string concatenation. Two in
one scope collide.

---

## Small families that mislead

- **`DISABLE_VS_WARNINGS(w)` expands to nothing, on every compiler**
  (`contrib/epee/include/warnings.h`). Adding or removing one changes
  nothing. `DISABLE_GCC_WARNING` is a no-op under clang.
  `PUSH_WARNINGS` / `POP_WARNINGS` are real `_Pragma`s.
- **`POD_CLASS` is gone**, and so is `src/common/pod-class.h`. Older notes
  and older review comments still reach for it. The key types it used to
  declare are now plain `struct`s inside `#pragma pack(push, 1)` in
  `src/crypto/crypto.h` — `ec_point`, `ec_scalar`, `ec_coord`,
  `public_key`, `key_derivation`, `key_image`, `signature`, `view_tag` — and
  `src/crypto/hash.h` (`hash`, `hash8`). The
  packing is what makes them wire-shaped, so a field added inside that region,
  or a `pop` moved, changes serialized layout with nothing warning about it.
- **`CRYPTO_MAKE_COMPARABLE` / `_CONSTANT_TIME` / `CRYPTO_MAKE_HASHABLE` /
  `CRYPTO_DEFINE_HASH_FUNCTIONS`** (`src/crypto/generic-ops.h`) generate the
  `operator==`, `std::hash` and `hash_value` (for `boost::hash`) for the key
  types. **None of those exist as text anywhere.** The plain form is `memcmp`; the
  `_CONSTANT_TIME` form is libsodium's `crypto_verify_32` (used for
  `secret_key` and `public_key_memsafe`, see the bottom of `crypto.h`). The
  hash is keyed SipHash-2-4 (`siphash_to_size_t`) with a per-process random
  key from `get_static_siphash_key()` in `src/crypto/random.c`, not a copy of
  the key bytes; bear that in mind before claiming hash-flooding.
- **`INITIALIZER` / `FINALIZER`** (`src/crypto/initializer.h`) → GCC
  `__attribute__((constructor))` / `((destructor))`. `INITIALIZER` has no
  user; `src/crypto/random.c` uses `FINALIZER(deinit_random)` and
  `FINALIZER(deinit_sip)` to wipe RNG and SipHash-key state at exit. The RNG is seeded lazily:
  `init_random` has no direct caller and runs only as the callback in
  `CTHR_ONCE_CALL(&init_random_once, init_random)` on the first
  `generate_random_bytes_not_thread_safe` / `add_extra_entropy_not_thread_safe`.
- **`CHECKED_GET_SPECIFIC_VARIANT(v, T, name, ret)`**
  (`cryptonote_format_utils.h`) both returns from the function on a type
  mismatch **and declares `name`**. Grepping the enclosing function for that
  variable's declaration finds nothing. It is two statements with no
  `do { } while(0)`.
- **LMDB member-renaming macros**: `src/blockchain_db/lmdb/db_lmdb.h` defines
  a set (`grep '^#define m_cur_' src/blockchain_db/lmdb/db_lmdb.h`) of the
  form `#define m_cur_blocks m_cursors->m_txc_blocks`, plus
  `CURSOR(name)` / `RCURSOR(name)` (about a hundred call sites) and
  `TXN_PREFIX*` / `TXN_BLOCK_PREFIX` (over fifty), all in `db_lmdb.cpp`;
  each can `throw0(DB_ERROR(...))`.
  `m_cur_blocks` looks like a member and is a macro; the real member
  `m_txc_blocks` never appears at a use site. `CURSOR` declares a `result`
  local inside its own `if` block.
- **`AUTO_VAL_INIT(v)`** is an *expression* producing a value-initialised
  temporary — `T x = AUTO_VAL_INIT(x);`.
- **`tests/core_tests/chaingen.h`**: the macro argument **is** the declared
  variable name. `MAKE_NEXT_BLOCK(events, blk_2, blk_1, miner)` declares
  `blk_2`. `MK_COINS(amount)` only compiles with a literal.

---

## The checklist this file exists for

Before saying **"nothing calls this"** or **"this is unused"**, search for the
macro that would generate it: `BEGIN_KV_SERIALIZE_MAP`,
`BEGIN_SERIALIZE_OBJECT`, `CRYPTO_MAKE_HASHABLE`, `HANDLE_NOTIFY_T2`,
`BEGIN_URI_MAP2`, `CTHR_ONCE_CALL`, `VARIANT_TAG`.

Before saying **"this field is validated"**, check which serializer runs and
whether its macro discards the result.

Before saying **"this returns"** or **"this cannot throw"**, expand the
assert macros.

And when you need the generated code itself, `g++ -E` is the tool — expand a
file that **uses** the macro, not the one that defines it:

```
g++ -E -I contrib/epee/include -I src -I external/easylogging++ -std=c++17 \
    src/rpc/core_rpc_server_commands_defs.h | grep -o 'selector<[^>]*>::serialize[^(]*'
```
