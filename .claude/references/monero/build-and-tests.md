# Build and tests

The build system and the test topology, from the point of view of somebody
who has to judge whether a change to either is safe.

Measured at master `8308dee67` (2026-10-13).

---

# The build

`cmake_minimum_required(VERSION 3.10)`, `CMAKE_CXX_STANDARD 17`
(`REQUIRED ON`), `CMAKE_EXPORT_COMPILE_COMMANDS ON`, compiler cache chosen
by `COMPILER_CACHE` (`auto` prefers sccache, which is also set as
`RUSTC_WRAPPER`, then ccache). An unset `CMAKE_BUILD_TYPE` becomes `Release`.

## How targets are declared

Everything goes through two wrappers: **`monero_add_library(name …)`**
(top-level `CMakeLists.txt`) and **`monero_add_executable(name …)`**
(`src/CMakeLists.txt`), plus `monero_add_library_with_deps` (called directly
only by `src/fcmp_pp`) and `monero_add_minimal_executable` (tests), both in the
top-level `CMakeLists.txt`. Headers are globbed by `monero_find_all_headers` in
most directories; **sources are not** — each per-directory `CMakeLists.txt`
under `src/` names its `<name>_sources` by hand
(`grep -rl _sources --include=CMakeLists.txt src`).

**So a new `.cpp` needs a `CMakeLists.txt` edit and a new `.h` does not.** A
new-file PR touching no CMake file is fine if it is header-only, and broken if
it is not. The two exceptions: `src/cryptonote_protocol` and `src/p2p` use
`file(GLOB …)`, so a new file there is picked up automatically. Test
binaries list their sources by hand too (`unit_tests_sources` in
`tests/unit_tests/CMakeLists.txt`), so a new test `.cpp` that is not listed
never runs.

The resulting library dependency graph is in `architecture.md`.

## The options that change behaviour

| option | default | why it matters |
|---|---|---|
| `PER_BLOCK_CHECKPOINT` | **ON** | when on, a matching embedded block hash (`m_blocks_hash_check`, loaded from `src/blocks/*.dat` by `Blockchain::load_compiled_in_block_hashes` only if `--fast-block-sync`, default 1, and not FAKECHAIN) makes `handle_block_to_main_chain` skip PoW, `ver_non_input_consensus` **and** per-tx `check_tx_inputs` |
| `BUILD_TESTS` | OFF | gates the whole of `tests/` |
| `STATIC` | OFF | static linking |
| `BUILD_SHARED_LIBS` | ON for a non-`STATIC` debug build, else OFF | internal libraries as shared |
| `SANITIZE` | OFF | `-fsanitize=address,undefined` |
| `NO_AES` | OFF | selects a different `cn_slow_hash` implementation |
| `USE_DEVICE_TREZOR` | ON (env-overridable, `cmake/CheckTrezor.cmake`) | builds `src/device_trezor`; **silently switched off** if protobuf is missing unless `USE_DEVICE_TREZOR_MANDATORY` (set by CI and Guix) |
| `BUILD_GUI_DEPS` | OFF | gates `libwallet_api_tests`; it and `trezor_tests` (`TREZOR_DEBUG`) are the only targets that link `wallet_api` (`EXCLUDE_FROM_ALL`) |
| `ENABLE_FUZZ_TEST` | OFF | adds `tests/fuzz` to a normal build |
| `STACK_TRACE` | OFF in release, else platform | compiles `src/common/stack_trace.cpp`, which **interposes on `__cxa_throw` process-wide** (`--wrap` when static, `dlsym(RTLD_NEXT)` otherwise); Guix forces it OFF on `*linux-gnu*` |
| `MX25519_COPYLEFT` | ON when Monero is the top-level project, OFF as a dependency (`external/CMakeLists.txt`) | includes mx25519's MPL-2.0 assembly backends (ARM64, AMD64, AMD64X); OFF defines `MX25519_NO_COPYLEFT`, leaving only the portable C backend. `cncrypto` links `mx25519_static` |
| `COVERAGE`, `STRIP_TARGETS`, `MANUAL_SUBMODULES`, `BUILD_DEBUG_UTILITIES`, `USE_READLINE`, `BOOST_IGNORE_SYSTEM_PATHS` | | |

`MONERO_WALLET_CRYPTO_LIBRARY` (`src/crypto/wallet/CMakeLists.txt`) defaults
to `auto`, which takes whatever `monero_crypto_autodetect`
(`external/supercop/functions.cmake`) reports as best — the supercop
assembly where available — falling back to `cn`. See `subsystems-crypto.md`.

## Hardening flags, and where they are set

All in the top-level `CMakeLists.txt`, and all are supply-chain-relevant —
removing one is a real finding even though it is not a memory-safety bug:

- `-U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=2`, appended with a plain `set` — note the level is
  **2**, and note the guard around it: `if(CMAKE_BUILD_TYPE STREQUAL "Release"
  AND NOT OPENBSD)`, so it is not set in a debug build at all. `STREQUAL` is
  case-sensitive: `-DCMAKE_BUILD_TYPE=release` gets no FORTIFY, and
  `contrib/depends/toolchain.cmake.in` sets lowercase `release` for
  `ARCHITECTURE` `arm` (armv7). A diff that changes that condition removes
  the flag from real builds without touching the flag.
- `-fstack-protector` and `-fstack-protector-strong`, via
  `add_c_flag_if_supported`, likewise inside an `if` that excludes
  OpenBSD and Windows/GCC < 9.1
- `-pie` / `-Wl,-pie`, with documented exclusions: PIE crashes
  under ASAN, and Windows binaries die with PIE under GCC < 9 or when
  dynamically linked
- `-Wl,-z,relro`, `-Wl,-z,now`, `-z noexecstack`/`noexecheap`; on Windows
  `--dynamicbase`, `--nxcompat`, `--high-entropy-va`
- `-fcf-protection=full`, `-fstack-clash-protection` (not Windows/OpenBSD),
  and `-Werror=` for `switch`, `return-type` and `format-security`

Every one of those except `_FORTIFY_SOURCE` uses `add_*_flag_if_supported`, which **silently does
nothing when the compiler rejects the flag**. "The flag is in CMakeLists" is
not the same claim as "the flag is in the build".

Also set tree-wide: **`-fno-strict-aliasing`** (appended twice, before and
after the hardening block) and `-ftemplate-depth=900`.

**`external/` is configured before any of this** (`add_subdirectory(external)`
precedes the flag block), so its targets — LMDB, easylogging++, qrcodegen,
RandomX — compile without `C_SECURITY_FLAGS`. Only `polyseed_static` and
`utf8proc` get them, via an explicit `set_property` after the block. Linker
flags still apply at the final executable link. Submodule pins are checked at
configure time by `check_submodule` unless `MANUAL_SUBMODULES`; a submodule
bump in a diff is a vendored-code change.

## `contrib/depends` — the cross-build dependency tree

A self-contained make-based builder: `packages/` (boost, openssl, sodium,
unbound, zeromq, protobuf, native_protobuf, hidapi, libusb, readline, ncurses, plus
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

Rust in the release build: `rust/cargo.sh` runs `cargo vendor --locked`
against `src/fcmp_pp/fcmp_pp_rust/Cargo.lock` and fails if the result differs
from `rust/config.toml`; the vendored archive is pinned by `RUST_DEPS_HASH`
in `guix-build`. The compiler is Guix's `rust` package (not CI's version),
and `libexec/build.sh` builds `std` from source with `-Zbuild-std` under
`RUSTC_BOOTSTRAP=1`. It also sets `USE_DEVICE_TREZOR_MANDATORY=1`. The
default `HOSTS` list in `guix-build` is what is released.

## CI: three workflows

- **`.github/workflows/build.yml`** — the matrix build; every compile job but
  `build-docker` uses `BUILD_DEFAULT` (`BUILD_TESTS`, `BUILD_GUI_DEPS` and `ENABLE_FUZZ_TEST`
  ON, `Release`), so fuzz targets are compiled but not run. The Debian/Ubuntu
  jobs install a **pinned Rust toolchain** (`INSTALL_RUST`): it fetches
  `rustup-init` 1.29.0, checks it against a hardcoded SHA-256, and installs
  toolchain `1.93`. The macOS, MSYS2 and Arch jobs use the platform's Rust.
  Tests run only in `test-ubuntu` (full `ctest`; on pull requests
  `core_tests` is rebuilt with `MONERO_CRYPTO_SLOW_HASH_ITER=20`) and, reduced
  by `CTEST_EXCLUDE_SLOW`, on macOS and Windows. The Debian 12, Ubuntu 22.04
  and Arch jobs only build.
- **`.github/workflows/depends.yml`** — cross builds through
  `contrib/depends`, one job per host triple, each carrying a `rust_host`
  (`riscv64gc-unknown-linux-gnu`, `aarch64-*`, `i686-*`,
  `x86_64-pc-windows-gnu`, darwin, freebsd, android, …), using the same
  pinned `rustup-init`.
- **`.github/workflows/guix.yml`** — the reproducible build.

**Rust is a hard build dependency** because of `src/fcmp_pp/fcmp_pp_rust`,
built by `cargo build --locked` (so `Cargo.lock` is authoritative). Its
`Cargo.toml` pins the monero-oxide crates to one git `rev`, patches
`crypto-bigint` from a git branch (the lock file fixes the commit), and sets
`overflow-checks = true` and `panic = "abort"` in both profiles. A change to
`Cargo.toml` or `Cargo.lock` is a supply-chain change.

---

# The tests

`tests/` is **not one framework** — it is a dozen harnesses with different
runners, different assertion vocabularies and different build gates.
`tests/README.md` is authoritative prose on how each is run.

## What exists

| directory | what it is |
|---|---|
| `unit_tests` | the only large gtest binary (count: `grep -hcE '^\s*TEST(_F)?\(' tests/unit_tests/*.cpp`) |
| `core_tests` | the chain-generator harness — one active test per `GENERATE_AND_PLAY(` line in `chaingen_main.cpp` |
| `functional_tests` | the Python RPC tests in `DEFAULT_TESTS` (`functional_tests_rpc.py`) driving `N_MONERODS` `monerod` + `N_WALLETS` `monero-wallet-rpc` in regtest, plus two C++ binaries (`functional_tests`, i.e. `transactions_flow_test`, and `cpu_power_test`) |
| `fuzz` | file-driven targets (one per `tests/fuzz/*.cpp` besides `fuzzer.cpp`) + 4 OSS-Fuzz-only RPC/ZMQ ones under `if(OSSFUZZ)` |
| `performance_tests` | a benchmark binary, **no CTest entry** |
| `hash`, `crypto` | replay text vector files |
| `difficulty`, `block_weight` | diff C++ output against a **Python reference implementation** |
| `libwallet_api_tests` | gated on `BUILD_GUI_DEPS` |
| `net_load_tests` | manual two-process socket exhaustion, **no CTest entry** |
| `trezor` | gated on `TREZOR_DEBUG` |
| `data` | fixtures — block 202612 per network, tx blobs under `txs/`, two wallets, fuzz seed corpora, test TLS key/cert under `ssl/`, a ban list under `node/` |

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
`hash-target`, `wallet-crypto-bench`, and conditionally
`functional_tests_rpc` and `check_missing_rpc_methods` (only if Python has
`requests`, `zmq` and `deepdiff`), `libwallet_api_tests` and `trezor_tests`.

**Not covered**: any fuzz target, `performance_tests`,
`net_load_tests_clt/srv`, and the `functional_tests` and `cpu_power_test`
C++ binaries. A change to one of those is not exercised by CI's test step.

**FCMP++ coverage** is `tests/unit_tests/curve_trees.cpp`, the `fcmp_pp`
cases in `tests/unit_tests/crypto.cpp`, and the `cncrypto` vectors below; no
`core_tests` class, functional test or fuzz target exercises `src/fcmp_pp`
(`git grep -il 'fcmp\|curve_trees' -- tests`).

Also: under `OSSFUZZ=ON` or `CMAKE_BUILD_TYPE=fuzz`, `tests/CMakeLists.txt`
narrows **only its `add_subdirectory` list** to `tests/fuzz` — the
`if`/`else` on `CMAKE_BUILD_TYPE STREQUAL "fuzz" OR OSSFUZZ` covers those
`add_subdirectory` calls and nothing else. Everything below it is still
configured: `libwallet_api_tests` (under `BUILD_GUI_DEPS`) and `trezor` (under
`TREZOR_DEBUG`) are still added, and `hash-target-tests` and
`monero-wallet-crypto-bench` (both `monero_add_minimal_executable`) are still
built and still register their CTest entries `hash-target` and
`wallet-crypto-bench`.

## The fuzz target list is a map

`tests/fuzz/` is the project's own statement of what it treats as
attacker-reachable: `base58`, `block`, `bulletproof`, `bulletproof-plus`,
`clsag`, `clsag_cout`, `clsag_message`, `clsag_pubs`, `cold-outputs`,
`cold-transaction`, `http-client`, `levin`, `load_from_binary`,
`load_from_json`, `network_address`, `parse_url`, `signature`, `transaction`,
`tx-extra`, `utf8`, plus the `fuzz_rpc/` group. Read `tests/fuzz/` rather than
this list: it is the kind of thing a pull request adds to.

Two readings: a PR touching a surface with an existing target is touching
something known to be reachable, and a PR that **weakens** a harness deserves
a note even though it ships nothing.

A new fuzz target is inert unless it is added in **three** places: a
`monero_add_minimal_executable` in `tests/fuzz/CMakeLists.txt`, a seed corpus
under `tests/data/fuzz/<name>/`, and the type list in
`contrib/fuzz_testing/fuzz.sh`. (That script's `case` list omits `tx-extra`
despite its seeds; compare it against `ls tests/fuzz/*.cpp`.)

## Traps in the test tree

- **`tests/data` is copied by `file(COPY …)` at CMake *configure* time.**
  Editing a fixture or adding a fuzz seed and then running `make && ctest`
  tests the **stale** copy under `build/tests/data`. Re-run cmake.
- **Production headers friend test classes.**
  `class wallet2` in `src/wallet/wallet2.h` befriends
  `::Serialization_portability_wallet_Test` — the class
  `TEST(Serialization, portability_wallet)` expands to — and the test helpers
  `::wallet_accessor_test` and `::wallet_pool_test`. Renaming one breaks the
  build of `src/`, and those tests can reach `wallet2` private state.
- **`IN_UNIT_TESTS` changes access control** in
  `src/cryptonote_core/blockchain.h` for the three translation units that
  define it.
- **`add_custom_target(tests DEPENDS enabled_tests)`** (`tests/CMakeLists.txt`)
  — `DEPENDS` takes target and file names, not a variable name, so
  `make tests` does **not** build the list above it.
- `tests/core_tests/double_spend.inl` is a template implementation `#include`d
  from the bottom of `double_spend.h`, listed under headers.
- `tests/crypto/{crypto-ops,crypto-ops-data,hash,random}.c` and `crypto.cpp`
  `#include` the corresponding `src/crypto` file (`hash.c` also pulls in
  `keccak.c`; `crypto.cpp` adds test wrappers) — `cncrypto-tests` **recompiles crypto
  internals** rather than linking `cncrypto`, so it can reach static functions.
  `tests/crypto/main.cpp` likewise `#include`s
  `src/fcmp_pp/fcmp_pp_crypto.cpp`; the `cncrypto` ctest exercises only its
  `point_to_wei_x_y` path (`mul8_is_identity_vartime` is tested in
  `tests/unit_tests/crypto.cpp`).
- `tests/fuzz/levin.cpp` is largely fenced off behind `#if 0`.
- `BEGIN_SIMPLE_FUZZER` expands to two completely different things:
  `LLVMFuzzerTestOneInput` under OSS-Fuzz, and a `SimpleFuzzer::run(filename)`
  member otherwise.
- `tests/difficulty/CMakeLists.txt` registers `wide_difficulty` with
  `${PYTHON_EXECUTABLE}`, a variable nothing in the project's CMake sets, so it
  expands empty and the scripts run via their shebangs — everything else uses
  `Python3_EXECUTABLE`.
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
