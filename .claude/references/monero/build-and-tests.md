# Build and tests

The build system and the test topology, from the point of view of somebody
who has to judge whether a change to either is safe.

Measured at master `3d3920d7`.

---

# The build

`cmake_minimum_required(VERSION 3.10)`, `CMAKE_CXX_STANDARD 17`
(`REQUIRED ON`), `CMAKE_EXPORT_COMPILE_COMMANDS ON`, compiler cache
autodetected (sccache then ccache).

## How targets are declared

Everything goes through two wrappers defined in `cmake/`:
**`monero_add_library(name …)`** and **`monero_add_executable(name …)`**, plus
`monero_add_library_with_deps` (used only by `src/fcmp_pp`) and
`monero_add_minimal_executable` (tests). Headers are globbed by
`monero_find_all_headers`; **sources are not** — each of the 28 per-directory
`CMakeLists.txt` files names its `<name>_sources` by hand.

**So a new `.cpp` needs a `CMakeLists.txt` edit and a new `.h` does not.** A
new-file PR touching no CMake file is fine if it is header-only, and broken if
it is not. The two exceptions: `src/cryptonote_protocol` and `src/p2p` use
`file(GLOB …)`, so a new file there is picked up automatically.

The resulting library dependency graph is in `architecture.md`.

## The options that change behaviour

| option | default | why it matters |
|---|---|---|
| `PER_BLOCK_CHECKPOINT` | **ON** | when on, a matching embedded block hash makes `handle_block_to_main_chain` skip PoW, `ver_non_input_consensus` **and** per-tx `check_tx_inputs` |
| `BUILD_TESTS` | OFF | gates the whole of `tests/` |
| `STATIC` | OFF | static linking |
| `BUILD_SHARED_LIBS` | platform | internal libraries as shared |
| `SANITIZE` | OFF | `-fsanitize=address,undefined` |
| `NO_AES` | detected | selects a different `cn_slow_hash` implementation |
| `USE_DEVICE_TREZOR` | on where deps exist | builds `src/device_trezor` |
| `BUILD_GUI_DEPS` | OFF | the only way `wallet_api` and `libwallet_api_tests` get built |
| `ENABLE_FUZZ_TEST` | OFF | adds `tests/fuzz` to a normal build |
| `STACK_TRACE` | platform | compiles `src/common/stack_trace.cpp`, which **interposes on `__cxa_throw` process-wide** |
| `COVERAGE`, `STRIP_TARGETS`, `MANUAL_SUBMODULES`, `BUILD_DEBUG_UTILITIES`, `USE_READLINE`, `BOOST_IGNORE_SYSTEM_PATHS` | | |

`MONERO_WALLET_CRYPTO_LIBRARY` defaults to `auto` and silently selects
supercop assembly on x86_64 UNIX — see `subsystems-crypto.md`.

## Hardening flags, and where they are set

All in the top-level `CMakeLists.txt`, and all are supply-chain-relevant —
removing one is a real finding even though it is not a memory-safety bug:

- `-U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=2` (:780-781) — note the level is
  **2**, and note the guard around it: `if(CMAKE_BUILD_TYPE STREQUAL "Release"
  AND NOT OPENBSD)`, so it is not set in a debug build at all. A diff that
  changes that condition removes the flag from real builds without touching
  the flag.
- `-fstack-protector` and `-fstack-protector-strong`, via
  `add_c_flag_if_supported` (:795-798), likewise inside an `if` that excludes
  OpenBSD and Windows/GCC < 9.1
- `-pie` / `-Wl,-pie` (:823-826), with documented exclusions: PIE crashes
  under ASAN, and Windows binaries die with PIE under GCC < 9 or when
  dynamically linked
- `-Wl,-z,relro` (:829)

Every one of those uses `add_*_flag_if_supported`, which **silently does
nothing when the compiler rejects the flag**. "The flag is in CMakeLists" is
not the same claim as "the flag is in the build".

Also set tree-wide: **`-fno-strict-aliasing`** (:775-776, and again at
:871-872 for the other branch) and `-ftemplate-depth=900` (:894).

## `contrib/depends` — the cross-build dependency tree

A self-contained make-based builder: `packages/` (boost, openssl, sodium,
unbound, zeromq, protobuf, hidapi, libusb, readline, ncurses, plus
`android_ndk`, `darwin_sdk`, `freebsd_base`), `hosts/` (android, darwin,
freebsd, linux, mingw32, default), `patches/`, `builders/`, and
`toolchain.cmake.in`.

Each package `.mk` pins a **source URL and a SHA-256**. Changing either is a
supply-chain change. `contrib/depends/README.md` and `packages.md` describe the
mechanism.

## `contrib/guix` — the reproducible release build

`manifest.scm`, `guix-build`, `guix-attest`, `guix-verify`, `guix-clean`,
`libexec/`, `patches/`, and — notably — **`rust/`**. This is what produces the
binaries people actually download, so a change here changes what ships.

## CI: three workflows

- **`.github/workflows/build.yml`** — the matrix build. Installs a **pinned
  Rust toolchain**: it fetches `rustup-init` 1.29.0, checks it against a
  hardcoded SHA-256, and installs toolchain `1.93`.
- **`.github/workflows/depends.yml`** — cross builds through
  `contrib/depends`, one job per host triple, each carrying a `rust_host`
  (`riscv64gc-unknown-linux-gnu`, `aarch64-*`, `i686-*`,
  `x86_64-pc-windows-gnu`, darwin, freebsd, android, …).
- **`.github/workflows/guix.yml`** — the reproducible build.

**Rust is now a hard build dependency** because of `src/fcmp_pp/fcmp_pp_rust`.

---

# The tests

`tests/` is **not one framework** — it is a dozen harnesses with different
runners, different assertion vocabularies and different build gates.
`tests/README.md` is authoritative prose on how each is run.

## What exists

| directory | what it is |
|---|---|
| `unit_tests` | the only large gtest binary — **896** `TEST`/`TEST_F` across 78 translation units |
| `core_tests` | the chain-generator harness — **165** active `GENERATE_AND_PLAY` tests |
| `functional_tests` | 19 Python RPC tests driving 5 `monerod` + 7 `monero-wallet-rpc` in regtest, plus two C++ binaries |
| `fuzz` | **27** executables: 23 file-driven targets + 4 OSS-Fuzz-only RPC/ZMQ ones (`grep -c monero_add_minimal_executable tests/fuzz/CMakeLists.txt`; 24 = 20 + 4 on `master`) |
| `performance_tests` | a benchmark binary, **no CTest entry** |
| `hash`, `crypto` | replay text vector files |
| `difficulty`, `block_weight` | diff C++ output against a **Python reference implementation** |
| `libwallet_api_tests` | gated on `BUILD_GUI_DEPS` |
| `net_load_tests` | manual two-process socket exhaustion, **no CTest entry** |
| `trezor` | gated on `TREZOR_DEBUG` |
| `data` | fixtures — block 202612 per network, 7 tx blobs, two wallets, fuzz seed corpora |

## Why `core_tests` matters more than it looks

Each test class synthesises a `std::vector<test_event_entry>` of blocks,
transactions and callbacks, then **replays it through a real
`cryptonote::core` on a FAKECHAIN LMDB**, asserting on the resulting
`block_verification_context` / `tx_verification_context`.

That is what proves consensus behaviour no unit test can reach — reorgs,
double spends, hard-fork gating, ring and RingCT rejection — because
acceptance is a property of the whole pipeline, not of any one function. **If
a diff changes an accept/reject verdict, the test that should move is here.**

Its invariants: the event list must begin with a `block`; the default
`check_*_verification_context` requires that **nothing** fails, so a test
expecting a rejection must override it; every `DO_CALLBACK` name needs a
matching `REGISTER_CALLBACK` in the constructor; and a new `gen_` class must
be visible through `chaingen_tests_list.h`.

## What is *not* run by CTest

`ctest` covers `unit_tests`, `core_tests`, `cncrypto`, `cnv4-jit`,
`difficulty`, `wide_difficulty`, `block_weight`, the `hash-*` entries,
`hash-target`, `wallet-crypto-bench`, `functional_tests_rpc`,
`check_missing_rpc_methods`, and conditionally `libwallet_api_tests` and
`trezor_tests`.

**Not covered**: any of the 27 fuzz targets, `performance_tests`,
`net_load_tests_clt/srv`, and the `functional_tests` C++ binary
(`transactions_flow_test`). A change to one of those is not exercised by CI's
test step.

Also: under `OSSFUZZ=ON` or `CMAKE_BUILD_TYPE=fuzz`, `tests/CMakeLists.txt`
narrows **only its `add_subdirectory` list** to `tests/fuzz` — the
`if`/`else` on `CMAKE_BUILD_TYPE STREQUAL "fuzz" OR OSSFUZZ` spans lines
50–65 and nothing else. Everything below it is still configured:
`libwallet_api_tests` (lines 67–69, under `BUILD_GUI_DEPS`) and `trezor`
(lines 71–73, under `TREZOR_DEBUG`) are still added, and
`hash-target-tests` (`monero_add_minimal_executable`, line 80) and
`monero-wallet-crypto-bench` (line 123) are still built and still register
their CTest entries `hash-target` (`add_test`, lines 90–92) and
`wallet-crypto-bench` (line 126).

## The fuzz target list is a map

`tests/fuzz/` is the project's own statement of what it treats as
attacker-reachable: `base58`, `block`, `bulletproof`, `bulletproof-plus`,
`clsag`, `clsag_cout`, `clsag_message`, `clsag_pubs`, `cold-outputs`,
`cold-transaction`, `http-client`, `levin`, `load_from_binary`,
`load_from_json`, `multisig-info`, `multisig-kex`, `multisig-tx`,
`network_address`, `parse_url`, `signature`, `transaction`, `tx-extra`,
`utf8`, plus the OSS-Fuzz-only group `fuzz_rpc`, `fuzz_rpc_full`,
`fuzz_rpc_full_no_exceptions` and `fuzz_zmq` (the `if(OSSFUZZ)` block ending
at `tests/fuzz/CMakeLists.txt:98`). Read `tests/fuzz/` rather than this list:
it is the kind of thing a pull request adds to.

The three `multisig-*` targets are recent: multisig key exchange, the
multisig unsigned-tx set and the multisig info export became part of that
attacker-reachable list with `multisig-kex_fuzz_tests`,
`multisig-tx_fuzz_tests` and `multisig-info_fuzz_tests`, declared at
`tests/fuzz/CMakeLists.txt:368`, `:382` and `:398`, with seeds under
`tests/data/fuzz/multisig-kex`, `multisig-tx` and `multisig-info`.

Two readings: a PR touching a surface with an existing target is touching
something known to be reachable, and a PR that **weakens** a harness deserves
a note even though it ships nothing.

A new fuzz target is inert unless it is added in **three** places: a
`monero_add_minimal_executable` in `tests/fuzz/CMakeLists.txt`, a seed corpus
under `tests/data/fuzz/<name>/`, and the type list in
`contrib/fuzz_testing/fuzz.sh`. (That script currently accepts 22 names for 23
file fuzzers — 19 for 20 on `master` — and `tx-extra` is the one file fuzzer
with seeds it will not run: `tx-extra_fuzz_tests` is declared at
`tests/fuzz/CMakeLists.txt:293` with seeds in `tests/data/fuzz/tx-extra`, but
`tx-extra` appears in neither the usage string nor the case list. Count the
names with `sed -n '17p' contrib/fuzz_testing/fuzz.sh | tr '|' '\n' | wc -l`.)

## Traps in the test tree

- **`tests/data` is copied by `file(COPY …)` at CMake *configure* time.**
  Editing a fixture or adding a fuzz seed and then running `make && ctest`
  tests the **stale** copy under `build/tests/data`. Re-run cmake.
- **Production headers friend gtest-generated class names.**
  `src/wallet/wallet2.h:175` has
  `friend class ::Serialization_portability_wallet_Test;` — the class
  `TEST(Serialization, portability_wallet)` expands to. Renaming that test
  breaks the build of `src/`.
- **`IN_UNIT_TESTS` changes access control** in
  `src/cryptonote_core/blockchain.h` for the three translation units that
  define it.
- **`add_custom_target(tests DEPENDS enabled_tests)`** (`tests/CMakeLists.txt`)
  — `DEPENDS` takes target and file names, not a variable name, so
  `make tests` does **not** build the list above it.
- `tests/core_tests/double_spend.inl` is a template implementation `#include`d
  from the bottom of `double_spend.h`, listed under headers.
- `tests/crypto/*.c` and `crypto.cpp` are ~3-line shims that `#include` the
  corresponding `src/crypto` file — the binary **recompiles crypto internals**
  rather than linking `cncrypto`, so it can reach static functions.
- `tests/fuzz/levin.cpp` is largely fenced off behind `#if 0`.
- `BEGIN_SIMPLE_FUZZER` expands to two completely different things:
  `LLVMFuzzerTestOneInput` under OSS-Fuzz, and a `SimpleFuzzer::run(filename)`
  member otherwise.
- `tests/difficulty/CMakeLists.txt` registers `wide_difficulty` with
  `${PYTHON_EXECUTABLE}`, a variable nothing in the project sets — everything
  else uses `Python3_EXECUTABLE`.
- `tests/difficulty/gen_wide_data.py` and `tests/block_weight/block_weight.py`
  are **independent reimplementations of consensus rules** in Python. A change
  to `next_difficulty` or to the long-term-weight algorithm needs the
  reference updated too, or the test diverges.
- `tests/data/account-00*` have no reader anywhere in the tree — orphaned
  fixtures.

## Running one thing

```
ctest -R core_tests                      # the whole consensus suite
./core_tests --list_tests                # enumerate
./core_tests --generate_and_play_test_data --filter 'gen_bpp_*'
ctest -R unit_tests
```

The `--filter` argument is a glob, converted by `tools::glob_to_regex`.
