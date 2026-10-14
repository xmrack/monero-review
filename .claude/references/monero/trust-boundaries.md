# Trust boundaries

Where untrusted data enters Monero, and what "untrusted" means at each point.
Use this to answer the reachability question concretely: name the boundary, then
trace the call sequence from it to the changed code.

Verify locations against the checkout — this is a map, not a substitute for
reading the tree. Where a symbol index has been built (see `navigation.md`),
use it (`readtags -t tags <sym>` for definitions, `cscope -d -L3 <fn>` for
callers) rather than assuming.

## 1. P2P messages — any peer, no authentication

`src/cryptonote_protocol/cryptonote_protocol_handler.inl`, `src/p2p/net_node.inl`

Handlers named `handle_notify_*`, `handle_request_*` and `handle_response_*`
(map: `HANDLE_NOTIFY_T2` in `cryptonote_protocol_handler.h`) receive
structures a peer fully controls: blocks, fluffy blocks, transactions,
requests for our objects and chain, and responses to our requests. Before
them, `net_node.inl` handles `handle_handshake`, `handle_timed_sync`,
`handle_ping` and `handle_get_support_flags`; the first two carry a
peer-supplied peerlist into `handle_remote_peerlist` (the eclipse surface).
Transaction relay (Dandelion++, anonymity-network queues) is in
`src/cryptonote_protocol/levin_notify.cpp`.

Every protocol message is a one-way notification, so a "response" is whatever
the peer chose to send. The two response handlers drop a peer whose message
type does not match `context.m_expect_response`, but nothing forces the
contents to match the request: mismatched counts, unexpected ordering, and
absent entries are all reachable.

Framing and dispatch: `contrib/epee/include/net/levin_protocol_handler_async.h`.
Size caps: `LEVIN_INITIAL_MAX_PACKET_SIZE` before handshake,
`LEVIN_DEFAULT_MAX_PACKET_SIZE` after (`levin_base.h`), and per command
`cryptonote_connection_context::get_max_bytes`. Payload parse limits:
`default_levin_limits` (`contrib/epee/include/storages/levin_abstract_invoke2.h`).

## 2. RPC — public or admin, and the difference matters

`src/rpc/core_rpc_server.cpp`, handlers named `on_*`; URI and JSON-RPC maps in
`src/rpc/core_rpc_server.h`

The server distinguishes **restricted** (public, what a remote wallet talks to)
from **unrestricted** (full admin). Check which applies to the handler you are
looking at before claiming remote reach: admin-only entries carry
`!m_restricted` in the `MAP_URI_AUTO_JON2_IF` / `MAP_JON_RPC_WE_IF` map, and
shared handlers apply the `RESTRICTED_*` / `MAX_RESTRICTED_*` limits
internally. It is not inferable from the method name. `--restricted-rpc`
defaults to false; `--rpc-restricted-bind-port` adds a second, restricted
server. The epee HTTP parser (`http_protocol_handler.inl`, digest auth in
`contrib/epee/src/http_auth.cpp`) runs before any login check or
restriction, so it is pre-authentication surface on every HTTP RPC server.

A finding reachable only by an unrestricted client is usually not a finding,
because that client is already trusted with far more. A finding on the
restricted surface of a public node is the real thing.

**That holds for a client the operator pointed at the admin interface, and
not for one that arrived uninvited.** The daemon is unrestricted by default,
so a browser page or a co-resident process reaching `127.0.0.1:18081`
cross-site has not been trusted with anything — it took an interface nobody
opened for it. Reach of that shape is a finding at the severity its effect
earns, and the `Unrestricted-RPC-only` row below does not apply.

The case this exists for: an unauthenticated cross-site request reaching
`/stop_daemon` on a default daemon. `json::load_from_json`
(`contrib/epee/include/storages/portable_storage_from_json.h`) accepts an
empty or whitespace-only body as `{}`, so a bodiless `GET` passes the JSON
parse in `MAP_URI_AUTO_JON2_IF` and reaches `on_stop_daemon`, as it does any
other handler whose request has no required fields. CORS headers do not stop
the request executing. The `Host` header is parsed into
`http_header_info::m_host` but nothing in the daemon RPC path compares it to an
allowlist (`grep -rn m_host contrib/epee src/rpc`), so DNS rebinding can make
responses readable as well.

**ZMQ RPC** (`src/rpc/zmq_server.cpp`, `daemon_handler.cpp`) is on unless
`--no-zmq`, binds `127.0.0.1` by default (non-loopback needs
`--confirm-zmq-rpc-external-bind`), has no authentication, and is unrestricted
unless `--restricted-zmq-rpc`, which blocks `blocked_in_restricted_mode`
(`zmq_restricted_methods.cpp`) and applies the `restricted_max_*` limits; its
help text disclaims filtering of sensitive data. Requests are parsed by
rapidjson (`src/rpc/message.cpp`, `src/serialization/json_object.cpp`). A
browser cannot speak ZMTP; a co-resident process can.

**`monero-wallet-rpc`** requires digest login unless `--disable-rpc-login`,
generating a random password if none is set (`wallet_rpc_server::init`).
Reach without that login is the finding.

## 3. Deserialization — the widest surface

`src/serialization/`, `contrib/epee/include/serialization/`,
`contrib/epee/include/storages/`

Every P2P message, HTTP RPC body, and consensus blob passes through here
(ZMQ RPC uses rapidjson, the wallet cache may fall back to
`boost::serialization`; see section 7). This is where attacker-chosen counts
meet `resize()` and `reserve()`.

It is also where most memory-safety findings die: the layer imposes limits
before application code runs (`portable_storage::limits_t`, the recursion
limits in `portable_storage_from_bin.h` and `portable_storage_from_json.h`).
See `refutations.md` — trace the field's actual constraint before reporting.

## 4. Daemon → wallet — the daemon is NOT trusted

`src/wallet/wallet2.cpp`

This boundary is easy to overlook and has repeatedly produced real bugs. A
wallet connecting to a remote node must treat that node's responses as
untrusted input. `process_parsed_blocks`, `process_new_transaction`, and
`process_new_blockchain_entry` all parse data a malicious or compromised daemon
chose, after the epee HTTP client (`contrib/epee/include/net/http_client.h`)
has parsed the response itself.

The threat model that matters: a user runs a GUI wallet or `wallet-rpc` against
a public remote node. Anything the node can say that corrupts wallet memory,
crashes it, or induces a wrong spend is in scope, and severity is high because
the wallet holds keys. A network attacker is usually equivalent:
`--daemon-ssl` defaults to `autodetect`, which falls back to plaintext when
the TLS handshake fails (`blocked_mode_client::connect` in `net_helper.h`).
`--trusted-daemon` (assumed for a local address in `make_basic`) enables
daemon-reliant commands; it does not make a remote daemon's data safe to parse.

`import_key_images` deserves the same treatment — key-image blobs arrive from
outside and are parsed into wallet state.

## 5. Co-signer messages — multisig and cold signing

`src/multisig/`, `src/wallet/wallet2.cpp` multisig paths,
`src/wallet/pending_tx_validation.cpp`, and the unsigned and signed transfer
blobs a cold wallet exchanges

A co-signer is a counterparty, not a colleague. Every message arriving from one
is attacker-controlled input from the perspective of the wallet that parses it:
key-exchange rounds (`multisig_kex_msg.cpp`, `parse_and_validate_msg`), partial
signatures and the nonce commitments they carry, and the unsigned/signed tx
blobs moved on a USB stick between a view-only wallet and an offline signer.

Most of the enforcement is in `src/wallet/pending_tx_validation.cpp`, not
`wallet2.cpp`: `check_consistent_ins_outs`,
`sanity_check_tx_construction_data`, `sanity_check_unsigned_tx_set`,
`sanity_check_pending_tx` and `sanity_check_pending_tx_set` in namespace
`tools::wallet`.
`wallet2::sanity_check_pending_tx` and `wallet2::sanity_check_pending_tx_set`
are thin wrappers that add a key-image resolver (`make_transfer_ki_resolver`
in `wallet2.cpp`, which does its own key-image checks). The cold-signing
and multisig paths call these, directly or through the wrappers:
`parse_unsigned_tx_from_str`, `sign_tx`, `parse_tx_from_str`,
`make_multisig_tx_set`, `parse_multisig_tx_from_str`, `load_multisig_tx`,
`sign_multisig_tx` and `cold_sign_tx`. Read both files before concluding a
blob goes unchecked.

What makes this a boundary rather than a detail: the wallet holds a key share
and is being asked to combine it with something a stranger chose. A message
that makes it reuse a nonce, sign a different transaction than the one shown,
or reveal a share, costs the user their funds and has done so before.

An M-of-N setup means a threshold of the signers is assumed honest — the rest
are not. Say which assumption a finding breaks.

## 6. Hardware device responses

`src/device/device_ledger.cpp`, `src/device_trezor/`, `device.hpp`

The device is the thing the user trusts INSTEAD of the host, so the host must
not treat what comes back from it as trusted. Responses cross a boundary in
both directions: a malicious or spoofed device can return key material, a
signature over the wrong data, or a malformed reply the host parses; a
compromised host can ask the device to display one thing and sign another.

Parsing of device replies (`exchange`, `receive_secret` and the protobuf paths
under `device_trezor`) is untrusted input, and a change that widens what the
host accepts belongs in a review even though "the device is trusted" sounds
like it settles the question.

## 7. Wallet cache and key files

Opening a wallet parses an on-disk cache. "The user opened a file they were
given" is a realistic threat model for custodial and multi-user setups. Treat
cache parsing as untrusted input, not as trusted local state.

Knowing the wallet's keys is not a precondition. `wallet2::load_wallet_cache`
decrypts with ChaCha20 (no MAC) and tries `binary_archive` (types in
`src/wallet/wallet2_basic/`) then older `boost::archive` schemes; if all of
those fail it parses the raw file as an **unencrypted**
`portable_binary_iarchive`, then `binary_iarchive`. The post-load index
checks against `m_transfers` are in the same function.

## 8. Consensus validation

`src/cryptonote_core/blockchain.cpp`, `tx_pool.cpp`, `src/ringct/`,
`src/crypto/`

Block and transaction acceptance, including `ver_non_input_consensus`
(`src/cryptonote_core/tx_verification_utils.cpp`, called from
`tx_memory_pool::add_tx` and the block paths), which runs
`core::check_tx_semantic` and its key-image subgroup check
`check_tx_inputs_keyimages_domain`. The question is not
just "does it crash" but "would a node running this code reach a different
verdict than the rest of the network on the same input".

Fork heights live in `src/hardforks/hardforks.cpp`, the `HF_VERSION_*`
constants in `src/cryptonote_config.h`. Any behaviour change must be gated to
the correct version; ask explicitly whether an ungated change makes old and
new nodes disagree.

`src/fcmp_pp/` (FCMP++) is built and linked into `ringct` but has no caller in
`src/` outside its own directory; see `codebase-notes.md`.

## 9. Build and CI

`CMakeLists.txt` files, `.github/workflows/`, `contrib/depends/`,
`contrib/guix/`, `.gitmodules`, `src/fcmp_pp/fcmp_pp_rust/Cargo.toml` and
`Cargo.lock`

Not consensus code, but a supply-chain surface. A change that alters what gets
compiled in, disables a hardening flag, changes a dependency source or pinned
hash (including a submodule commit or a Cargo git `rev`), or weakens a release
workflow is worth reporting even though it is not a memory-safety bug.
Removal of a hardening flag (`-D_FORTIFY_SOURCE`, stack protector, RELRO, PIE)
is a genuine finding.

## Severity anchoring by boundary

| Reached from | Typical ceiling |
| --- | --- |
| Consensus validation, any divergence | CRITICAL |
| P2P, unauthenticated, memory corruption | CRITICAL |
| Malicious daemon → wallet memory corruption | CRITICAL (keys are present) |
| P2P or restricted RPC, crash or OOM | HIGH |
| Malicious daemon → wallet crash | HIGH |
| Privacy break that links or deanonymises | HIGH |
| Requires non-default option or unusual position | MEDIUM |
| Cross-site or unattended reach to the default-unrestricted daemon | what the effect earns; NOT the row below |
| Unrestricted-RPC-only reached by a client the operator pointed there, or test-only | LOW, usually not reportable |
