# Coding style

**This tree is not one codebase with one style. It is four dialects that share
a licence header and almost nothing else**, plus vendored code that follows
nobody's rules but its own. Carrying a rule from one dialect into another is
the most common way to be wrong about style here.

All counts measured at master `160e21504`.

---

## The dialects

| dialect | where | indent | guards | error idiom | naming |
|---|---|---|---|---|---|
| **cryptonote core** | `src/cryptonote_*`, `src/p2p`, `src/rpc`, `src/wallet/wallet2.*`, `src/blockchain_db` | 2 | `#pragma once` | `CHECK_AND_ASSERT_MES` | `lower_snake_case`, `m_` members |
| **epee** | `contrib/epee/` | 2, tabs mixed in | `#pragma once` | `CHECK_AND_ASSERT_*`, `TRY_ENTRY` | `t_` template params, `m_` on *public* wire members |
| **crypto (C)** | `src/crypto/` | 2, C89-ish | mixed: `#ifndef` in the hash-function C headers, `#pragma once` elsewhere | raw `assert` | hyphenated filenames |
| **"new" C++** | `src/net`, `src/lmdb`, `src/rpc/zmq*`, `src/fcmp_pp`, `src/device`, `src/wallet/api`, `src/wallet/wallet2_basic` | **4** (except `src/rpc/zmq*`, `src/net/http.*` and `src/net/resolve.*`: 2) | `#pragma once` | `expect<T>`, `MONERO_CHECK` | CamelCase more common |
| **vendored** | `external/*`, `src/crypto/crypto_ops_builder/` | upstream's | upstream's | upstream's | upstream's |

**Indentation is a reliable fingerprint**: 2 spaces in the core, 4 in most
of the newer subsystems. `src/wallet` is split exactly down the
middle — `wallet2.*` is old, `api/` and `wallet2_basic/` are new.

**Do not review `external/`, `src/crypto/crypto_ops_builder/`, or the
Sabelnikov-headed half of `contrib/epee` for Monero style.** Do check that a
change to vendored code is either an upstream sync or a deliberate,
documented local patch.

---

## What is actually settled

Four conventions hold with no meaningful exceptions:

1. **A 3-clause BSD licence block starting on line 1** — line 1 is
   `// Copyright (c) <years>, The Monero Project`, then a fixed 26-line body.
   Older files add "Parts of this file are originally copyright (c) 2012-2013
   The Cryptonote developers" (`git grep -l 'Parts of this file are originally'
   -- src ':!src/crypto'`).
2. **No `using namespace` in a header.** Zero occurrences in `src/*.h` and
   zero in `contrib/epee` headers and `.inl` files. In `.cpp` files it is
   common in `src/`, overwhelmingly `using namespace epee;` and
   `using namespace cryptonote;`. **This is the one convention with no
   exceptions — reject a header that breaks it.**
3. **A new `.cpp` must be added by name** to its directory's `CMakeLists.txt`
   `<name>_sources` list. A new `.h` need not be — headers are globbed by
   `monero_find_all_headers`.
4. **Per-translation-unit log category**: `#undef MONERO_DEFAULT_LOG_CATEGORY`
   then `#define` its own, after the includes
   (`git grep -l '^#undef MONERO_DEFAULT_LOG_CATEGORY' -- src`).

## What is not settled, and should not be a finding on its own

- **Brace style.** Control statements: next-line braces are the majority
  (roughly 4:1 in `src/`, more in `contrib/epee`), but same-line is common.
  Namespaces: mostly next-line. There is **no `.clang-format`**
  in the tree, and `docs/CONTRIBUTING.md` asks for local consistency only.
- **Reference binding.** `src/` leans to `const T &x`, with `const T& x`
  close behind; `contrib/epee` strongly prefers `const T& x`.
- **Header guards.** `#pragma once` dominates in `src/`, and some headers
  (most of `src/wallet/api`'s) have **no guard at all**
  (`grep -L 'pragma *once' $(git ls-files 'src/*.h')`); `src/crypto` is mixed.
- **Include order.** There is no convention. Only a little over half of the
  `src/` `.cpp` files with a matching header include it first.
- **The copyright year.** It is bumped by hand, per file, on touch, with no
  automation anywhere in `utils/`. The tree simultaneously carries 2024, 2025
  and 2026 end years, and many files still say `2014-2024`
  (`git grep -l '2014-2024, The Monero Project'`). Neither presence nor absence of a bump in a diff means anything.
- **Blank comment lines in the licence header** are written `// ` with a
  trailing space in about half the tree and `//` in the other half, and a
  handful of files carry CRLF there. A "whitespace-only" hunk in a licence header is
  real churn, not noise.

---

## Naming

- **Types**: mostly `lower_snake_case`, then `ALL_CAPS` (nearly all of them
  `COMMAND_` or `NOTIFY_` — wire message types), then `CamelCase` (the newer
  and API-facing subsystems). `src/ringct/rctTypes.h` mixes all three in one file.
- **`m_` marks a member of a class that has behaviour.** Structs describing a
  wire or disk format use plain names — **because those names *are* the
  serialised keys**. Plain member declarations outnumber `m_` ones in `src/`
  headers, concentrated in the two RPC commands-defs headers.
  **The exception that bites**: some *serialised* structs keep `m_` —
  `account_public_address` (`src/cryptonote_basic/cryptonote_basic.h`),
  `account_keys` (`src/cryptonote_basic/account.h`) and the `m_block_ids` /
  `m_block_weights` chain-entry fields — so `m_spend_public_key` really is the
  wire key there. Check
  `grep -rc "KV_SERIALIZE\w*(m_"` before assuming.
- Only four `m_Uppercase` identifiers exist in the tree: `m_L`, `m_LR`,
  `m_R`, and epee's `m_URI`.
- **Constants**: consensus and protocol constants are `ALL_CAPS #define`s in
  `src/cryptonote_config.h` (`grep -c '^#define' src/cryptonote_config.h`;
  only a handful of `constexpr` in the whole file). Network-parameterised constants are `const` objects in
  `namespace config` / `config::testnet` / `config::stagenet` — **the same
  names declared three times**, so a hunk showing `P2P_DEFAULT_PORT = 18080`
  is ambiguous about which network it belongs to until you look at the
  enclosing namespace.
- **Template parameters**: `contrib/epee` uses `t_`-prefixed names for a
  large minority; `src/` mostly does not.

---

## The shape of a translation unit

**A `.inl` here is the entire implementation of a class template**, not a
small inline helper. The first-party ones outside `tests/`, largest first
(`git ls-files '*.inl' | grep -v ^external | xargs wc -l | sort -rn`):

```
src/p2p/net_node.inl
src/cryptonote_protocol/cryptonote_protocol_handler.inl
contrib/epee/include/net/abstract_tcp_server2.inl
contrib/epee/include/net/http_protocol_handler.inl
contrib/epee/include/stats.inl
src/daemonizer/windows_daemonizer.inl
src/daemonizer/posix_daemonizer.inl
```

The first two — the whole P2P node and the whole protocol handler — are
emitted from **`src/rpc/instantiations.cpp`, which is six lines of code**:

```cpp
#include "p2p/net_node.h"
#include "p2p/net_node.inl"
#include "cryptonote_protocol/cryptonote_protocol_handler.h"
#include "cryptonote_protocol/cryptonote_protocol_handler.inl"
namespace nodetool { template class node_server<cryptonote::t_cryptonote_protocol_handler<cryptonote::core>>; }
namespace cryptonote { template class t_cryptonote_protocol_handler<cryptonote::core>; }
```

Two consequences: **a grep that skips `*.inl` misses the two most
attacker-exposed files in the daemon**, and a change to `core`'s signature
produces its compile errors in `instantiations.cpp`, far from the edit.
The `daemonizer` `.inl` files are different — platform-conditional bodies
included under `#ifdef`.

**Namespaces map to subsystems, not directories, and are reopened freely.**
`namespace cryptonote` is opened in over a dozen `src/` directories;
`namespace tools` spans `src/common`, `src/wallet` and `src/cryptonote_core`.
The one-namespace-one-directory cases are `src/net` (`net`), `src/lmdb`
(`lmdb`), `src/wallet/api` (`Monero`) and `src/ringct` (`rct`).

**Include paths.** `src`, `contrib/epee/include`, `external`,
`external/easylogging++`, `external/rapidjson/include`,
`external/supercop/include` and — appended by the polyseed work —
`external/polyseed/include` and `external/utf8proc` are all on the global
include path (one `include_directories` call in the top-level
`CMakeLists.txt`). So **a
bare quoted include is usually an epee header**: `#include "span.h"`,
`#include "string_tools.h"`, `#include "misc_log_ex.h"`.
Five basenames collide between `src/` and
`contrib/epee/include`: `base.h`, `enums.h`, `error.h`, `fwd.h`, `wire.h`.

**Forward-declaration headers** are `fwd.h` per subsystem, except
`src/common/common_fwd.h`. Two epee files named `fwd.h` are *not* pure forward
declarations — `serialization/wire/fwd.h` defines macros.

---

## Memory, ownership and secrets

Measured in `src/` (`git grep -c <pattern> -- src`): `boost::optional`
outnumbers `std::optional` by more than ten to one — Boost is the idiom, and
mixing them at a boundary is a real inconsistency. `std::shared_ptr` is more
common than `std::unique_ptr`; `reinterpret_cast` is far more common than
`const_cast`.

**Scope guards**: the current idiom is `epee::scope_guard` and, rarely,
`epee::unique_scope_guard` (`contrib/epee/include/scope_guard.h`), which adds
`.reset()` (run the action now) and `.release()` (disarm). **`tools::scope_leave_handler` and
`epee::misc_utils::auto_scope_leave_caller` do not exist any more** — zero
occurrences. Older notes naming them are describing a previous tree.

**Non-owning views** are pervasive and easy to misread:

- `epee::span<T>` **never owns**. `epee::strspan<uint8_t>(some_string)` is
  valid only while that string lives.
- `epee::byte_slice` is move-only with a reference-counted backing;
  `remove_prefix`, `take_slice` and `operator=` can drop the last reference and
  invalidate a previously returned `data()` pointer.
- `epee::byte_stream::put_unsafe` does **not** check capacity outside debug.
- `cryptonote::blobdata_ref` is a `boost::string_ref`, and several functions
  take it **by value**, accepting a temporary `std::string` implicitly.

**Secret lifetime.** `memwipe` (`contrib/epee/src/memwipe.c`) has three
mutually exclusive implementations selected by `HAVE_MEMSET_S` /
`HAVE_EXPLICIT_BZERO`, and **every one ends with the `SCARECROW` inline-asm
barrier** — without it the compiler may elide the clear. `epee::wipeable_string`
routes every size change through `grow()`, which wipes the discarded tail on
shrink and both buffers on reallocation. `tools::scrubbed<T>` static_asserts
that `T` is POD and trivially destructible. Note **all of this lives in
`contrib/epee`, not `src/common`**, despite being conceptually part of the
utility layer.

The tree is built with **`-fno-strict-aliasing`** (`CMakeLists.txt`), which is
a standing acknowledgement that the POD/`reinterpret_cast` idioms at the wire
boundary would otherwise be undefined.

---

## The C++ dialect

`CMAKE_CXX_STANDARD 17`, `CMAKE_CXX_STANDARD_REQUIRED ON`
(top-level `CMakeLists.txt`), `-ftemplate-depth=900`.

Modern-C++ adoption in `src/` (matching lines, excluding `src/crypto`:
`git grep -c <pattern> -- src ':!src/crypto'`): `NULL` still outnumbers
`nullptr`, and `enum class` is a small minority of `enum`s. So plain `enum` and `NULL` are still
the majority idiom in the core, and a diff modernising them is a style
change, not a fix.

Boost is used heavily and is not going away: `asio` (all networking),
`thread` (essentially all threading — `std::thread` appears in `src/` only
for `hardware_concurrency()`),
`filesystem`, `serialization` (persisted state), `program_options`,
`multiprecision` (`difficulty_type` is `uint128_t`), `uuid`, `variant`
(`txin_v`, `txout_target_v`, `tx_extra_field`), `multi_index` (the peer
lists).

---

## When style *is* worth raising

Almost never on its own. The cases that are real:

- A `using namespace` added to a header.
- A member renamed inside a `BEGIN_KV_SERIALIZE_MAP`, `BEGIN_SERIALIZE_OBJECT`
  or `WIRE_FIELD` map — **that renames a wire or on-disk key**.
- A field added to a `request_t`/`response_t` that is *not* wrapped by
  `struct_init`, so it is genuinely uninitialised.
- A new `.cpp` missing from its `CMakeLists.txt`.
- A `THROW_WALLET_EXCEPTION_IF` placed before an `else` without braces.
- Two `CRITICAL_REGION_LOCAL`, or two `PERF_TIMER` with the same name, in
  one scope (name collision).
- A rule imported from the wrong dialect — suggesting `expect<T>` in
  `cryptonote_core` (0 uses there), or `CHECK_AND_ASSERT_MES` in `src/net`.

Everything else in this file is context for *reading* the code, not a
checklist for correcting it.
