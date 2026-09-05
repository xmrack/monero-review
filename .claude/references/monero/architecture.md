# Architecture

How the Monero tree fits together: the layers, what depends on what, and the
handful of structural facts that explain most of what looks strange when you
open a file here.

Measured against `monero-project/monero` master at `3d3920d7`, 2026-09-03.
Line counts and link edges move; the shape does not. Re-check anything you are
about to put in a finding.

## What ships

Two executables and one library are the whole point of the tree:

- **`monerod`** — the node. `src/daemon/`, linking essentially everything.
- **`monero-wallet-cli`** — the CLI wallet. Built from `src/simplewallet/`;
  note the target is named `simplewallet` and only the installed binary is
  called `monero-wallet-cli` (`src/simplewallet/CMakeLists.txt`).
- **`monero-wallet-rpc`** — `src/wallet/wallet_rpc_server.cpp`, a second
  front end over the same `wallet2`.
- **`wallet_api`** — `src/wallet/api/`, the library the GUI and the mobile
  wallets link. Marked `EXCLUDE_FROM_ALL`, so a default build does not
  produce it.

Everything else in `src/` is a library one of those links, or an offline tool
(`src/blockchain_utilities/`, `src/debug_utilities/`, `src/gen_multisig/`,
`src/gen_ssl_cert/`).

## The layer graph

Taken from `target_link_libraries` in each `CMakeLists.txt`, internal edges
only. Read it upward: a change low down is felt everywhere above it.

```
easylogging  randomx  liblmdb  rapidjson  supercop  qrcodegen   (external/, vendored)
     |
   epee ......................... contrib/epee: portable_storage, Levin, HTTP, TLS
     |
 cncrypto ....................... src/crypto  (-> epee, randomx)
     |
  common ........................ src/common  (-> cncrypto, unbound)
     |
  +--+------------+-------------+
  |               |             |
checkpoints   ringct_basic   fcmp_pp ......... src/fcmp_pp (-> cncrypto, common,
  |               |             |                            epee, libfcmp_pp_rust.a)
  |            device <---------+   src/device (-> cryptonote_format_utils_basic,
  |               |                             ringct_basic, wallet-crypto)
  |            ringct .......... src/ringct (-> common, cncrypto, device, fcmp_pp)
  |               |
cryptonote_basic .+ ............ src/cryptonote_basic (-> common, cncrypto,
  |                                checkpoints, cryptonote_format_utils_basic,
  |                                device, ringct_basic)
blockchain_db ................... src/blockchain_db (-> cryptonote_basic, ringct_basic)
  |
cryptonote_core ................. src/cryptonote_core (-> blockchain_db, ringct,
  |                                device, hardforks, version, wire)
  +---- net ...................... src/net (-> common, epee, cncrypto, libzmq)
  |      |
  |     p2p ...................... src/p2p (-> cryptonote_core, net, version)
  |      |
  |  cryptonote_protocol ......... src/cryptonote_protocol (-> p2p)
  |
  +---- rpc_base -> rpc -> daemon_rpc_server ...... src/rpc
  |
  +---- multisig ................. src/multisig (-> ringct, cryptonote_core)
  |
  +---- wallet ................... src/wallet (-> rpc_base, multisig,
         |                            cryptonote_core, mnemonics, device_trezor, net)
         +-- wallet_api, wallet_rpc_server, simplewallet
```

Three edges in that graph surprise people, and all three are real:

- **`cryptonote_protocol` links `p2p`, not the other way round.** `p2p` links
  `cryptonote_core`. The protocol handler is a template parameterised on the
  core, and `src/p2p/net_node.h` is parameterised on the protocol handler;
  the cycle is broken by templates, not by layering.
- **`ringct` links `fcmp_pp`.** FCMP++ is in the build today (see below).
- **`cryptonote_core` links `wire`**, the newest of the four serialization
  systems.

`serialization` is the odd one out: `src/serialization/CMakeLists.txt` links
`cryptonote_basic`, `cryptonote_core` and `cryptonote_protocol` — backwards
from what the name suggests. That target exists to instantiate templates, not
to be depended on; the archive machinery itself is header-only and every user
just includes it.

## Where the weight is

Nine files carry a disproportionate share of the risk, and eight of them are
over 2,000 lines:

| lines | file | why it matters |
|------:|------|----------------|
| 15450 | `src/wallet/wallet2.cpp` | the entire wallet, one translation unit |
| 11450 | `src/simplewallet/simplewallet.cpp` | the CLI command table and prompts |
|  5769 | `src/blockchain_db/lmdb/db_lmdb.cpp` | the only shipped `BlockchainDB` |
|  5595 | `src/cryptonote_core/blockchain.cpp` | validation and reorganisation |
|  5211 | `src/wallet/wallet_rpc_server.cpp` | the unattended wallet surface |
|  4042 | `src/crypto/crypto-ops.c` | Ed25519 arithmetic, C, `ref10`-derived |
|  3188 | `src/p2p/net_node.inl` | the node; a `.inl`, not a `.cpp` |
|  3132 | `src/rpc/core_rpc_server.cpp` | the daemon's HTTP surface |
|  2917 | `src/cryptonote_protocol/cryptonote_protocol_handler.inl` | the P2P trust boundary |

The last two `.inl` files are implementations, not inline helpers. Grep that
skips `*.inl` misses the two most attacker-exposed files in the daemon.

## Four serialization systems, not two

This is the single most useful structural fact about the tree, and the count
is four, not the two that older notes claim.

1. **`contrib/epee/include/storages/portable_storage*`** — the object model
   under every RPC and P2P *payload*, in both a binary and a JSON encoding.
   Driven by the `KV_SERIALIZE` macro family. This is the one sitting directly
   on attacker bytes.
2. **`src/serialization/`** — the template archive machinery for blocks,
   transactions, and the wallet cache. Driven by `BEGIN_SERIALIZE_OBJECT` and
   `FIELD`. Consensus-defining: the serialization *is* the format.
3. **`contrib/epee/include/serialization/wire/`** plus the `wire` and
   `wire-json` targets — the newest system, a typed writer built around
   `wire::object` and `WIRE_FIELD`. **Write-only on master**: `json_reader` is
   forward-declared in `wire/json/fwd.h:38` and never defined, and
   `contrib/epee/src/wire/` ships `write.cpp` and `error.cpp` with no reader.
   Used today by `src/rpc/zmq_pub.cpp` and
   `src/cryptonote_core/cryptonote_tx_utils.cpp`.
4. **`boost::serialization`** — persisted local state, in about two dozen
   headers: the peer list (`src/p2p/net_peerlist_boost_serialization.h`), the
   wallet cache and keys (`src/wallet/wallet2_basic/wallet2_boost_serialization.h`),
   the multisig message store, and a second full description of the tx and
   block types in `src/cryptonote_basic/cryptonote_boost_serialization.h`.

Two consequences worth carrying:

- A transaction has **two independent serialization descriptions** — the
  consensus one in `src/cryptonote_basic/cryptonote_basic.h` and the Boost one
  in `cryptonote_boost_serialization.h`. They are maintained by hand and can
  drift. The Boost one is not consensus, but it is what the wallet cache and
  `tests/core_tests` round-trip through.
- "Which serializer" is usually the first question to settle about a change to
  a wire-facing struct, because the macro family tells you which parser an
  attacker reaches.

`macros.md` has the expansions; `subsystems-node.md` has the read paths and
their bounds.

## Vendored code, and the Rust boundary

`external/` is other people's code held to a different standard than `src/`:
`randomx` (proof-of-work), `supercop` (assembly Ed25519 for the wallet),
`db_drivers/liblmdb` (a *patched* LMDB, not upstream), `easylogging++`,
`rapidjson`, `gtest`, `qrcodegen`. `contrib/epee/` is Monero's own but
predates most of `src/` and follows different conventions — treat it as a
fifth dialect, not as part of `src/`.

**Monero master builds Rust.** `src/fcmp_pp/fcmp_pp_rust/` is a
`crate-type = ["staticlib"]` crate that `src/fcmp_pp/CMakeLists.txt` links as
`libfcmp_pp_rust.a`. Its manifest pulls `ciphersuite 0.4.2` and
`dalek-ff-group 0.5.0` from crates.io, `helioselene` from a git revision of
`github.com/monero-oxide/monero-oxide`, and patches `crypto-bigint` to a
branch of a personal fork. CI installs a pinned toolchain
(`.github/workflows/build.yml` verifies `rustup-init` by SHA-256 and installs
`1.93`), and `contrib/depends` carries a `rust_host` per cross target. A
change under `fcmp_pp_rust/` is a supply-chain change even when the diff looks
like arithmetic.

The C++ side guards the boundary: CMake `try_compile`s
`src/fcmp_pp/ffi_api_c_compat.c` and fails the build with
`"The FCMP++ FFI API header 'fcmp++.h' has broken compatibility with C"` if
the generated header stops being C-compatible.

**FCMP++ is staged, not live.** The only consumer of `src/fcmp_pp/` outside
itself is `src/ringct/rctSigs.cpp`, which includes `fcmp_pp/fcmp_pp_crypto.h`
and calls `fcmp_pp::get_valid_torsion_cleared_point_vartime` from
`rct::verPointsForTorsion` (`src/ringct/rctSigs.cpp:1592`). That function has
no production caller: it appears in `rctSigs.h`, `rctSigs.cpp` and
`tests/unit_tests/crypto.cpp` and nowhere else. Describing FCMP++ as
consensus-reachable today is wrong; describing the code as absent is also
wrong.

## Consensus versus everything else

The line that matters for severity is not "which directory" but "does a node
running this reach a different accept/reject verdict".

Inside the fence: `src/cryptonote_basic/` (the types and their serialization,
`get_block_longhash`, difficulty), `src/cryptonote_core/blockchain.cpp`,
`src/ringct/`, `src/crypto/` where it is on a verification path,
`src/hardforks/`, the consensus constants in `src/cryptonote_config.h`, and
RandomX in `external/randomx/`.

Outside it, but still shipped: the pool's *relay* policy (accepting a
transaction into the pool is local, mining it is not), `src/p2p/`,
`src/rpc/`, the wallet, `src/cryptonote_basic/miner.cpp` — mining is not
verification — and all of `tests/`.

Every behaviour change inside the fence has to be gated on a hard-fork
version. The gates are the `HF_VERSION_*` names in `src/cryptonote_config.h`
(lines 175-196) and the tables in `src/hardforks/hardforks.cpp`. Mainnet is
at v16 from block 2689608; there are separate tables for testnet and
stagenet, and they do not agree with mainnet.

## The three networks

`MAINNET`, `TESTNET` and `STAGENET` are selected at runtime, not at build
time, and carry different network IDs, address prefixes, ports, seed nodes
and — the part that bites — different hard-fork tables. A change tested only
on one is tested on one. `src/cryptonote_config.h` holds all three under
`namespace config` and its `testnet`/`stagenet` sub-namespaces.

## Reading order for a newcomer agent

1. This file.
2. `flows.md` — one end-to-end trace covering whatever the change touches.
3. The matching section of `subsystems-node.md`, `subsystems-wallet.md` or
   `subsystems-crypto.md`.
4. `macros.md` before believing any grep result.
