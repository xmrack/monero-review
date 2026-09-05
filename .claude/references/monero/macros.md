# The macro families

Monero is a macro-DSL codebase. Almost nothing that matters on the wire is
written as ordinary C++, and almost none of the generated functions can be
found by grepping for their names.

**Read this before believing a grep result**, and before saying "nothing calls
this" or "this field is unvalidated".

Counts below were measured over `src/`, `contrib/` and `tests/` at master
`3d3920d7` with `grep -rhoP "(?<![A-Za-z_])NAME\("`, which includes each
macro's own definition line.

---

## The four serialization DSLs

They coexist, they share no vocabulary, and **the one nearest a struct's
definition is often not the one that runs**.

### 1. `src/serialization/` — consensus binary

`src/serialization/serialization.h`

| macro | generates |
|---|---|
| `BEGIN_SERIALIZE_OBJECT()` :175 | `member_do_serialize()` (calls `begin_object` / `do_serialize_object` / `end_object`) **and then opens** `do_serialize_object()` |
| `BEGIN_SERIALIZE()` :155 | only `member_do_serialize()` — no object framing |
| `BEGIN_SERIALIZE_OBJECT_FN(stype)` :194 | a **free** `do_serialize_object(Archive<W>&, stype& v)` |
| `BEGIN_SERIALIZE_FN(stype)` :166 | a free `do_serialize(Archive<W>&, stype& v)` |
| `END_SERIALIZE()` :206 | `return ar.good(); }` |

Field macros: `FIELD(f)` (236 uses), `FIELD_N(t,f)`, `FIELD_F(f)` = `FIELD_N(#f, v.f)`
(for the `_FN` forms), `FIELDS(f)` (no tag), `VARINT_FIELD(f)` (61),
`VARINT_FIELD_N`, `VARINT_FIELD_F`, `MAGIC_FIELD(m)`, `VERSION_FIELD(v)` (23),
`PREPARE_CUSTOM_VECTOR_SERIALIZATION(size, vec)`.

Trait macros: `BLOB_SERIALIZER(T)` / `BLOB_SERIALIZER_FORCED(T)` route `T`
onto the raw `memcpy` overload; `VARIANT_TAG(Archive, Type, Tag)` (109 uses)
binds a wire byte to a C++ type.

- **51** `BEGIN_SERIALIZE_OBJECT()` / **15** `BEGIN_SERIALIZE()`.
- **The field name is decorative here.** `binary_archive_base::tag(const char*)`
  is `{ }` (`src/serialization/binary_archive.h`), as are `begin_object` and
  `end_object`. So `FIELD(x)` and `FIELD_N("y", x)` produce identical bytes,
  and the name only surfaces in `json_archive` / `debug_archive`. **The format
  is positional** — when a member is added, check field *position*, not name.
- **Every `FIELD` line is a control-flow exit** — it expands to
  `if (!r || !ar.good()) return false;`.
- `VERSION_FIELD(n)` **declares a local `version`** that escapes the macro so
  the lines below can branch on it, and it never bounds the value upward.
- Grepping for `member_do_serialize` finds only four hand-written overloads in
  `src/cryptonote_basic/tx_extra.h`.

### 2. `contrib/epee/…/keyvalue_serialization.h` — RPC and P2P

`BEGIN_KV_SERIALIZE_MAP()` (:43, **423** blocks) injects `public:` and
generates **four** members: `store()` (declared `const`, and `const_cast`s
`*this`), `_load()`, `load()` (same as `_load` but wrapped in
try/catch logging "Exception on unserializing"), and
`serialize_map<bool is_store, class t_storage>`.

Field macros and counts: `KV_SERIALIZE` **922**, `KV_SERIALIZE_OPT` 135,
`KV_SERIALIZE_PARENT` 124, `KV_SERIALIZE_VAL_POD_AS_BLOB`,
`KV_SERIALIZE_CONTAINER_POD_AS_BLOB`, and the `_N` and `_FORCE` variants.
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
  zero-initialisation of every field comes from that typedef, not from member
  initialisers. There are **326** `struct_init<` wrappers against 423 KV
  blocks — nested payload structs held in containers are **not** covered, so
  their scalars really are uninitialised.

### 3. `contrib/epee/…/serialization/wire/` — the newest, and write-only

`WIRE_BEGIN_MAP` / `WIRE_END_MAP` / `WIRE_FIELD(name)` / `WIRE_DEFINE_OBJECT`
generate `read_bytes` / `write_bytes` / `wire_map`. `WIRE_FIELD(name)` becomes
`::wire::field("name", std::ref(self.name))`, so a JSON key is findable only as
the macro argument.

Used by exactly **two** files under `src/`: `src/rpc/zmq_pub.cpp` and
`src/cryptonote_core/cryptonote_tx_utils.cpp`. **`wire::json_reader` is
forward-declared and never defined** — the read side does not exist on master.

### 4. `boost::serialization` — persisted local state

Hand-written `serialize()` free functions plus `BOOST_CLASS_VERSION` (~24
lines: `tools::wallet2` = 31, `wallet2_basic::transfer_details` = 12,
`address_book_row` = 18, `peerlist_entry` = 3, …). This is the **third**
serializer for several of the same types.

> **The multi-serializer trap, concretely.** `rct::rctSigBase` has a
> `BEGIN_SERIALIZE_OBJECT()` block in `rctTypes.h` **and** the member template
> `serialize_rctsig_base`. The consensus path uses only the latter. A `FIELD()`
> added to the former changes nothing on the wire.
> Likewise `transfer_details` carries both a `BEGIN_SERIALIZE_OBJECT_FN` block
> (in `wallet2_serialization.h`, not next to the type) and a Boost hook.
> **Before judging a change to any type that crosses a wire or a disk,
> enumerate all of its serializers.**

---

## Dispatch tables — there is no runtime registration

| macro family | defined in | generates |
|---|---|---|
| `BEGIN_URI_MAP2` / `MAP_URI_AUTO_JON2[_IF]` / `MAP_URI_AUTO_BIN2` | `contrib/epee/include/net/http_server_handlers_map2.h` | `handle_http_request_map()` — a chain of `else if` |
| `BEGIN_JSON_RPC_MAP` / `MAP_JON_RPC[_WE][_IF]` | same | another `else if` chain on the method name |
| `CHAIN_HTTP_TO_MAP2` | same | `handle_http_request()` |
| `BEGIN_INVOKE_MAP2` / `HANDLE_INVOKE_T2` / `HANDLE_NOTIFY_T2` | `contrib/epee/include/storages/levin_abstract_invoke2.h` | `handle_invoke_map()`, dispatching on `CMD::ID == command` |
| `BEGIN_RPC_MESSAGE_CLASS` / `_REQUEST` / `_RESPONSE` | `src/rpc/daemon_messages.h` | the ZMQ `Request` / `Response` classes |

Consequences:

- **A URI string or JSON-RPC method name appears exactly once**, in the table.
  Grepping for the handler finds its declaration and definition but not the
  URI.
- **The whole restricted-mode access-control policy is the `_IF` suffix.**
  `MAP_URI_AUTO_JON2_IF(..., !m_restricted)` versus `MAP_URI_AUTO_JON2(...)`.
  Dropping four characters from a table line silently exposes a method.
- **The chains are opened by `if (false) return true;` and order matters.** An
  entry added after a matching one is dead code that compiles cleanly.
- A Levin command with no `HANDLE_NOTIFY_T2` entry logs "Unknown command" and
  returns `LEVIN_OK` for notifies — a silent no-op.
- `class Request` / `class Response` never appear as searchable text in
  `daemon_messages.h`.

---

## Failure macros — function exits with no `return` or `throw` token

Measured counts:

| macro | uses | behaviour |
|---|---:|---|
| `CHECK_AND_ASSERT_MES(expr, ret, msg)` | 603 | `LOG_ERROR` then **`return ret`** |
| `CHECK_AND_ASSERT_THROW_MES(expr, msg)` | 570 | log then **throw `std::runtime_error`** |
| `THROW_WALLET_EXCEPTION_IF(cond, type, …)` | 537 | throw a typed `tools::error` with `__FILE__:__LINE__` |
| `CHECK_AND_ASSERT(expr, ret)` | 11 | **silent** return, no log |
| `CHECK_AND_NO_ASSERT_MES*` | ~17 | logs at `LOG_PRINT_L0/L1` instead, still returns |
| `CHECK_AND_ASSERT_MES2` | 2 | logs and does **not** return |
| `MONERO_PRECOND` / `MONERO_CHECK` / `MONERO_THROW` / `MONERO_UNWRAP` | 16/13/14/30 | `expect<T>` dialect |

**Read every one of these lines as a `return` or a `throw`.** A grep for
`return false` in a validation function misses most of its failure paths. When
reviewing a refactor that moves code across such a line, check that cleanup and
unlock ordering still hold.

**`THROW_WALLET_EXCEPTION_IF` is a bare `if (cond) { … }`** — no
`do { } while(0)` — while its sibling `THROW_WALLET_EXCEPTION` *is* wrapped.
Putting the `_IF` form before an `else` rebinds that `else` to the macro's
hidden `if`. Insist on braces.

**The dialects are geographic**, and suggesting the wrong one is against the
grain. Roughly, by subtree
(`CHECK_AND_ASSERT_MES` / `CHECK_AND_ASSERT_THROW_MES` / `THROW_WALLET_EXCEPTION_IF`):
`cryptonote_core` 81/9/0, `cryptonote_basic` 63/20/0, `ringct` 62/47/0,
`wallet` 35/59/531, `blockchain_db` 0/0/0 (it uses `throw0`/`throw1`).
**`src/crypto` uses none of them** — zero epee macros, ~112 raw `assert(`.
The `expect<T>` dialect lives only in `src/common`, `src/net`, `src/lmdb`,
`src/rpc/zmq*` and `src/p2p/net_node.cpp`.

`TRY_ENTRY()` / `CATCH_ENTRY(location, ret)` / `CATCH_ENTRY_L0..L4` /
`CATCH_ENTRY_SWALLOW_EX` are an **unbalanced brace pair split across two
macros** — a diff hunk showing only one looks syntactically broken. The
`_L0..L4` suffix suggests a log level and controls nothing.

---

## Locking, logging and timing

**`CRITICAL_REGION_LOCAL(x)`** (`contrib/epee/include/syncobj.h:81`, 204 uses)
→ `boost::unique_lock critical_region_var(x)`. Note:

- The `#define` has **two spaces** after it, so `grep '^#define CRITICAL_REGION_LOCAL'`
  misses it.
- **The lock variable always has the same name**, so two in one scope is a
  redefinition error, and grepping for a lock variable is useless.
- `CRITICAL_REGION_LOCAL1` and `CRITICAL_REGION_BEGIN` insert a
  `g_test_dbg_lock_sleep()` debug delay; plain `CRITICAL_REGION_LOCAL` does
  not.
- It relies on C++17 CTAD — there is no template argument.

**Logging.** `MERROR` / `MWARNING` / `MINFO` / `MDEBUG` / `MTRACE` →
`MCERROR(MONERO_DEFAULT_LOG_CATEGORY, x)` → … → `MCLOG_TYPE`, which wraps
everything in `if (el::Loggers::allowed(level, cat))`.

- **Arguments are only evaluated if the category and level pass.** Never put a
  needed side effect in a log statement.
- **The category comes from a per-file `#define`, not the call site.** There
  are ~126 definition sites, 122 of them immediately preceded by `#undef`.
  39 are in *headers*, so including one changes the category for the includer.
- **`LOG_PRINT_L0` is `MWARNING`.** `L1` → `MINFO`, `L2` → `MDEBUG`, `L3`/`L4`
  → `MTRACE`. Reading a change from `L0` to `L1` as "made it noisier" is
  backwards.
- `MGINFO` and friends hardcode `"global"`, ignoring the file's category.
- Counts, `src/` + `contrib/epee`: `MERROR` 421, `MDEBUG` 393, `LOG_ERROR`
  271, `MINFO` 251, `LOG_PRINT_L3` 241, `LOG_PRINT_L0` 208. The modern M\*
  family leads (`src/`: 1122 M\* vs 711 `LOG_PRINT_L*`), and `contrib/epee` is
  essentially fully converted.
- The M\* macros are **not variadic**, so a top-level comma in the logged
  expression is a compile error.

**`PERF_TIMER(name)`** declares `pt_##name`, an RAII object whose log category
is `"perf." MONERO_DEFAULT_LOG_CATEGORY` built by string concatenation. Two in
one scope collide.

---

## Small families that mislead

- **`DISABLE_VS_WARNINGS(w)` expands to nothing, on every compiler**
  (`contrib/epee/include/warnings.h:7`). Adding or removing one changes
  nothing. `DISABLE_GCC_WARNING` is a no-op under clang.
  `PUSH_WARNINGS` / `POP_WARNINGS` are real `_Pragma`s.
- **`POD_CLASS`** (`src/common/pod-class.h:33`) is `struct`. Used 11 times,
  all inside `#pragma pack(push,1)` in `src/crypto/crypto.h`.
- **`CRYPTO_MAKE_COMPARABLE` / `_CONSTANT_TIME` / `CRYPTO_MAKE_HASHABLE` /
  `CRYPTO_DEFINE_HASH_FUNCTIONS`** (`src/crypto/generic-ops.h`) generate the
  `operator==`, `std::hash` and `boost::hash_value` for the key types. **None
  of those exist as text anywhere.** The plain form is `memcmp`; the
  `_CONSTANT_TIME` form is libsodium's `crypto_verify_32`.
- **`INITIALIZER` / `FINALIZER`** (`src/crypto/initializer.h`) → GCC
  `__attribute__((constructor))`. Used in exactly one place:
  `src/crypto/random.c` seeds the RNG **before `main`**. `init_random` has no
  caller anywhere; grepping for "who seeds the RNG" finds nothing.
- **`CHECKED_GET_SPECIFIC_VARIANT(v, T, name, ret)`** both returns from the
  function on a type mismatch **and declares `name`**. Grepping the enclosing
  function for that variable's declaration finds nothing.
- **LMDB member-renaming macros**: `src/blockchain_db/lmdb/db_lmdb.h` defines
  18 of the form `#define m_cur_blocks m_cursors->m_txc_blocks`, plus
  `CURSOR(name)` / `RCURSOR(name)` (102 call sites) and `TXN_PREFIX*` (57).
  `m_cur_blocks` looks like a member and is a macro; the real member
  `m_txc_blocks` never appears at a use site. `CURSOR` declares a local
  `result`.
- **`AUTO_VAL_INIT(v)`** is an *expression* producing a value-initialised
  temporary — `T x = AUTO_VAL_INIT(x);` (84 uses).
- **`tests/core_tests/chaingen.h`**: the macro argument **is** the declared
  variable name. `MAKE_NEXT_BLOCK(events, blk_2, blk_1, miner)` declares
  `blk_2`. `MK_COINS(amount)` only compiles with a literal.

---

## The checklist this file exists for

Before saying **"nothing calls this"** or **"this is unused"**, search for the
macro that would generate it: `BEGIN_KV_SERIALIZE_MAP`,
`BEGIN_SERIALIZE_OBJECT`, `CRYPTO_MAKE_HASHABLE`, `HANDLE_NOTIFY_T2`,
`BEGIN_URI_MAP2`, `INITIALIZER`, `VARIANT_TAG`.

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
