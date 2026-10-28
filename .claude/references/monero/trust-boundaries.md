# Threat model and trust boundaries

What Monero protects, who attacks it, where their input enters the code, and
how bad each outcome is. Use it to answer the reachability question concretely
(name the boundary, then trace the call sequence from it to the changed code)
and to rate what you find.

Verified against master `3fd0f88c2` (2026-10-25). The severity tiers follow the
classes of vulnerability the project has actually had to fix and how it rated
them. Verify locations against the checkout — this is a
map, not a substitute for reading the tree. Where a symbol index has been built
(see `navigation.md`), use it (`readtags -t tags <sym>` for definitions,
`cscope -d -L3 <fn>` for callers) rather than assuming.

## What is being protected, in order

1. **Supply integrity.** Amounts are hidden, so nobody can audit total supply
   by adding up balances. Counterfeiting is invisible unless someone already
   knows the flaw and searches for it, so a past exploit can only be ruled out
   by a scan written after the flaw is found. A soundness break in a range
   proof, the balance check, or key-image uniqueness can be permanent and
   undetectable.
2. **Funds and keys.** A theft or burn cannot be reversed.
3. **Privacy.** The chain is permanent and public, so whatever a transaction
   leaks, it leaks to every future analyst with every future heuristic. A
   privacy bug fixed in the next release still exposes every transaction made
   before it. The project rates privacy bugs in its own wallet HIGH.
4. **Consensus agreement.** Two nodes running shipped code must reach the same
   verdict on every block and transaction.
5. **Availability.** Nodes and wallets that stay up and keep syncing. This can
   be recovered, which is why it ranks last; but a crash that **every** node
   suffers stops the network, and that is item 4's severity, not this one's.

## Who the adversary is

Name one of these in every finding. "An attacker" is not specific enough to
judge reachability or rate severity.

| Adversary | What they can do | Cost and realism |
| --- | --- | --- |
| **P2P peer** | Open connections and send any Levin message; occupy peer slots; answer our outbound requests with whatever they like | Free, and running many is cheap. Spy and proxy nodes have been measured as a large fraction of the network, so holding a large share of a victim's peers is a realistic position for **privacy** attacks, not an unusual one |
| **Transaction sender** | Put crafted but valid data on chain: `tx_extra`, output keys, amounts, unlock times, many outputs to one key | Only the fee. Historically the largest source of real money loss (section 5) |
| **Miner** | Choose block contents, the coinbase and timestamps; withhold blocks; reorg | One crafted block needs no special position, because small miners find blocks daily. Reorgs and withholding need a large share; a large minority pool has already produced reorgs deeper than the 10-block lock. Above 50% is out of scope (VRP preamble 6) |
| **Remote node operator** | Answer every wallet request with whatever it likes; see the wallet's IP, timing and the transactions it submits | The common configuration for GUI and mobile users. A network attacker is usually equivalent (section 4) |
| **Restricted-RPC client** | Call the public RPC surface of a node that runs one | Anyone, wherever public remote nodes exist |
| **Counterparty** | A multisig co-signer, the hot half of a cold-signing pair, the payer or payee in a payment, an exchange | Inside the protocol on purpose; a co-signer able to steal funds has happened |
| **Passive chain analyst** | Read every transaction ever made, forever | Free. Ring-signature statistics, decoy-selection bias, fee and `tx_extra` fingerprints |
| **Network observer** | Watch traffic between nodes, or between wallet and node; on-path, an ISP, a DNS resolver | Watching costs nothing; tampering needs an on-path position (MEDIUM) |
| **Local unprivileged** | A browser page making cross-site requests; another process or user on the same machine; whoever supplied a file the user opens | Needs the user to be running something or to open something |
| **Hardware device, or the host it is plugged into** | Each can lie to the other | A compromised host extracting a device's spend key has happened |
| **Supply chain** | Change what gets built or downloaded | Replaced release binaries have happened |

## 1. P2P messages — any peer, no authentication

`src/cryptonote_protocol/cryptonote_protocol_handler.inl`, `src/p2p/net_node.inl`

Handlers named `handle_notify_*`, `handle_request_*` and `handle_response_*`
(map: `HANDLE_NOTIFY_T2` in `cryptonote_protocol_handler.h`) receive
structures a peer fully controls: blocks, fluffy blocks, transactions,
requests for our objects, chain and txpool complement, and responses to our
requests. Before them, `net_node.inl` handles `handle_handshake`,
`handle_timed_sync`, `handle_ping` and `handle_get_support_flags`
(`BEGIN_INVOKE_MAP2(node_server)` in `net_node.h`).

**Two ways into the peer list.** Peerlists arrive only in the **responses**
from peers we dial: `local_peerlist_new` is in `COMMAND_HANDSHAKE_T::response`
and `COMMAND_TIMED_SYNC_T::response`, and `handle_remote_peerlist` is called
from `do_handshake_with_peer` and `do_peer_timed_sync`. The other way in is an
inbound handshake. It carries a peer-chosen `node_data.my_port`;
`handle_handshake` pings that port back and, on success, puts the peer in the
white list. Both feed the eclipse surface. Inbound requests also carry
`CORE_SYNC_DATA` into `process_payload_sync_data`, and a peer's advertised
`rpc_port` ends up served to wallets (section 11).

Every cryptonote protocol message is a one-way notification, so a "response"
is whatever the peer chose to send. `handle_response_get_objects` and
`handle_response_chain_entry` drop a peer whose message type does not match
`context.m_expect_response`, but nothing forces the contents to match the
request: mismatched counts, unexpected ordering, and missing entries are all
reachable. The p2p-layer commands are real request–response invokes.

Framing and dispatch: `contrib/epee/include/net/levin_protocol_handler_async.h`.
Size caps: `LEVIN_INITIAL_MAX_PACKET_SIZE` before handshake,
`LEVIN_DEFAULT_MAX_PACKET_SIZE` after (`levin_base.h`), and per command
`cryptonote_connection_context::get_max_bytes`
(`src/cryptonote_basic/connection_context.cpp`; an unknown command gets no
per-command cap). The payload is parsed **before** the handler checks the
connection state. Any command that fits the pre-handshake cap is fully
deserialized before handshake, and only then ignored. Payload parse limits:
`default_levin_limits` (`contrib/epee/include/storages/levin_abstract_invoke2.h`).

Connection limits: `--in-peers` defaults to -1, which means unlimited inbound
connections; `--max-connections-per-ip` defaults to 1, with IPv6 grouped by
/64; there is no rate limit on accepting connections. Transaction relay
(Dandelion++, anonymity-network queues) is in
`src/cryptonote_protocol/levin_notify.cpp`. Peers arriving over Tor or I2P
(`--anonymous-inbound`) may send only handshake, timed sync and
`NOTIFY_NEW_TRANSACTIONS` (`is_filtered_command` in `net_node.cpp`), and
`has_too_many_connections` does not apply to them.

Historically this is where remote DoS lives: type confusion in Levin
payloads, allocations driven by peer-supplied sizes, memory exhaustion
attacks run against the live network, queue flooding, and connection
miscounts that help an eclipse attack.

## 2. RPC — public or admin, and the difference matters

`src/rpc/core_rpc_server.cpp`, handlers named `on_*`; URI and JSON-RPC maps in
`src/rpc/core_rpc_server.h`

The server distinguishes **restricted** (public, what a remote wallet talks to)
from **unrestricted** (full admin). Check which applies to the handler you are
looking at before claiming remote reach: admin-only entries carry
`!m_restricted` in the `MAP_URI_AUTO_JON2_IF` / `MAP_JON_RPC_WE_IF` map, and
shared handlers apply the `RESTRICTED_*` / `MAX_RESTRICTED_*` limits
internally (`const bool restricted = m_restricted && ctx`). You cannot tell
from the method name. `submit_block`, `get_block_template`, `get_outs`,
`get_output_distribution`, `send_raw_transaction` and `get_public_nodes` are on
the restricted surface; a public client with valid PoW reaches full block
validation through `submit_block`.

`--restricted-rpc` defaults to false. `--rpc-restricted-bind-port` adds a
second, restricted server. `--public-node` restricts nothing: it advertises
an RPC port to peers and throws "restricted RPC mode is required" unless
restriction is already on (`parse_public_rpc_port`, `src/daemon/main.cpp`).
With `--rpc-restricted-bind-port` set it advertises that port; otherwise, with
`--restricted-rpc`, it advertises the main `--rpc-bind-port`. It only warns if
the advertised bind address is loopback or local. The epee HTTP parser
(`http_protocol_handler.inl`, digest auth in `contrib/epee/src/http_auth.cpp`)
runs before any login check or restriction, so it is pre-authentication
surface on every HTTP RPC server. A
`MAP_URI_AUTO_BIN2` body is parsed with `load_t_from_binary` and **no**
`limits_t`; only `MAX_RPC_CONTENT_LENGTH` bounds it.

A finding reachable only by an unrestricted client is usually not a finding,
because that client is already trusted with far more. A finding on the
restricted surface of a public node is the real thing.

**That holds for a client the operator pointed at the admin interface, and
not for one that arrived uninvited.** The daemon is unrestricted by default,
so a browser page or a co-resident process reaching `127.0.0.1:18081` has not
been trusted with anything — it took an interface nobody opened for it. Reach
of that shape is a finding, rated by its effect less the user-interaction step
(see Severity), and the `Unrestricted-RPC-only` row below does not apply.

The case this exists for: an unauthenticated cross-site request reaching
`/stop_daemon` on a default daemon. `json::load_from_json`
(`contrib/epee/include/storages/portable_storage_from_json.h`) accepts an
empty or whitespace-only body as `{}`, so a bodiless `GET` passes the JSON
parse in `MAP_URI_AUTO_JON2_IF` and reaches `on_stop_daemon`, as it does any
other handler whose request has no required fields. A bodiless request is not
the only shape a browser can send: a cross-site page can also send a simple
`POST` with a body. CORS headers do not stop a request executing, they only
decide whether the page can read the reply. The `Host` header is parsed
into `http_header_info::m_host` but nothing in the daemon RPC path compares it
to an allowlist (`grep -rn m_host contrib/epee src/rpc`), so DNS rebinding can
make responses readable as well. This class has been reported against both
the wallet RPC and the daemon.

**ZMQ RPC** (`src/rpc/zmq_server.cpp`, `daemon_handler.cpp`) is on unless
`--no-zmq`, binds `127.0.0.1` by default (non-loopback needs
`--confirm-zmq-rpc-external-bind`), has no authentication, and is unrestricted
unless `--restricted-zmq-rpc`, which blocks `blocked_in_restricted_mode`
(`zmq_restricted_methods.cpp`) and applies the `restricted_max_*` limits; its
help text disclaims filtering of sensitive data. Requests are parsed by
rapidjson (`src/rpc/message.cpp`, `src/serialization/json_object.cpp`). A
browser cannot speak ZMTP; a co-resident process can. Restricted mode is
implemented separately on each RPC server, so when a restriction changes on
one, check that the others have it too.

**`monero-wallet-rpc`** requires digest login unless `--disable-rpc-login`,
generating a random password if none is set (`wallet_rpc_server::init`, written
to `monero-wallet-rpc.<port>.login`). Reach without that login is the finding.
Its own `--restricted-rpc` exists and defaults to false; a state-changing call
that gets past it is a finding.

## 3. Deserialization — the widest surface

`src/serialization/`, `contrib/epee/include/serialization/`,
`contrib/epee/include/storages/`

Every P2P message, HTTP RPC body, and consensus blob passes through here
(ZMQ RPC uses rapidjson, the wallet cache may fall back to
`boost::serialization`; see section 8). This is where attacker-chosen counts
meet `resize()` and `reserve()`.

The limits are uneven, so trace the field's actual constraint (and see
`refutations.md`) before reporting or refuting. `portable_storage::limits_t`
defaults to **unlimited**. It is passed on Levin (`default_levin_limits`) and
on the client side of HTTP `.bin` (`default_http_bin_limits` in
`http_abstract_invoke.h`), not on the server side of RPC. JSON has a
recursion limit (`EPEE_JSON_RECURSION_LIMIT_INTERNAL`) and the request body
cap. The consensus serializer bounds counts against the remaining input.

## 4. Daemon → wallet — the daemon is NOT trusted

`src/wallet/wallet2.cpp`, `src/wallet/node_rpc_proxy.cpp`

This boundary is easy to overlook and keeps producing real bugs: tracing
through corrupted decoy responses, timing side channels, the wallet telling
the node which transactions are its own, crashes on malformed responses, and
forged proof results. A wallet
connecting to a remote node must treat that node's responses as untrusted
input. `process_parsed_blocks`, `process_new_transaction` and
`process_new_blockchain_entry` all parse data a malicious or compromised
daemon chose, after the epee HTTP client
(`contrib/epee/include/net/http_client.h`) has parsed the response itself.

The daemon decides more than block contents. It chooses the **decoys**
(`get_output_distribution`, `get_outs`), the **fee** (`get_fee_estimate`), the
height, and the transactions behind proofs (`check_tx_proof`,
`check_spend_proof`, `check_reserve_proof` fetch them). It also sees the IP,
the timing and the transactions the wallet submits. Ask of each value the
wallet takes: what does it do if the node lies?

The threat model that matters: a user runs a GUI wallet or `wallet-rpc` against
a public remote node. Anything the node can say that corrupts wallet memory,
crashes it, makes it spend wrongly, or makes it reveal which outputs are its
own is in scope. Severity is high because the wallet holds keys and because
`wallet-rpc` often runs unattended at exchanges and services.

A network attacker is usually equivalent. `--daemon-ssl` defaults to
`autodetect`. That mode reconnects in plaintext when the TLS handshake fails
(`blocked_mode_client::connect` in `net_helper.h`). Even when TLS succeeds in
that mode, the verify callback in `contrib/epee/src/net_ssl.cpp` accepts an **unverified**
certificate and only logs "SSL peer has not been verified". Only a
fingerprint or a CA-verified mode authenticates the node.

`--trusted-daemon` (assumed by `make_basic` when the address is `localhost`,
`*.localhost` or a loopback literal, via `tools::is_local_address`) enables
mining, `rescan_spent`, spent checks on key-image import and
histogram-based output selection. It does not make a remote daemon's data safe
to parse.

## 5. On-chain data → the recipient's wallet

`wallet2::process_new_transaction`, `process_outgoing`, the coinbase and
`tx_extra` paths, `src/cryptonote_basic/tx_extra.h`

Any sender can put any consensus-valid data on chain, and any miner can do the
same for a coinbase. The recipient's wallet then parses it, decides what it
owns, and reports a balance that an exchange or merchant will credit. This
boundary has caused more real money loss than any other in the codebase.
The classes:

- **Double counting.** Duplicate or extra transaction public keys make the
  wallet count one output several times. This was once treated as a display
  bug until an exchange was robbed through it.
- **Burning.** Many outputs to one one-time key; the wallet credits all of
  them and only one can ever be spent.
- **Crafted coinbase.** A miner shapes a coinbase so the wallet credits an
  amount it did not receive.
- **Lock times.** Outputs locked far into the future credited as spendable.

The question here is never "can this crash". It is "can a sender make the
wallet report funds it cannot spend, or miss funds it owns". Both are fund
loss for whoever acts on the balance.

## 6. Co-signer messages — multisig and cold signing

`src/multisig/`, `src/wallet/wallet2.cpp` multisig paths,
`src/wallet/pending_tx_validation.cpp`, `src/wallet/message_store.cpp` and
`message_transporter.cpp` (MMS), and the unsigned and signed transfer blobs a
cold wallet exchanges

A co-signer is a counterparty, not a colleague. Every message arriving from one
is attacker-controlled input from the perspective of the wallet that parses it:
key-exchange rounds (`multisig_kex_msg.cpp`, `parse_and_validate_msg`), partial
signatures and the nonce commitments they carry, and the unsigned/signed tx
blobs moved on a USB stick between a view-only wallet and an offline signer.
The multisig messaging system (MMS) also takes messages over PyBitmessage: hand-parsed
XML, double base64, then `load_t_from_json` into `transport_message`.

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
`sign_multisig_tx`, `cold_sign_tx` and `commit_tx`. Read both files before
concluding a blob goes unchecked.

What makes this a boundary rather than a detail: the wallet holds a key share
and is being asked to combine it with something a stranger chose. A message
that makes it reuse a nonce, sign a different transaction than the one shown,
or reveal a share, costs the user their funds and has done so before:
signature forgery and nonce reuse between co-signers, a co-signer causing a
recipient to be paid repeatedly, and a hot wallet redirecting a cold signer's
change.

An M-of-N setup means a threshold of the signers is assumed honest — the rest
are not. Say which assumption a finding breaks. Multisig is off by default
behind an experimental flag. That limits who is exposed, but it does not make
the code unreachable for the users who turn it on.

## 7. Hardware device responses

`src/device/device_ledger.cpp`, `src/device_trezor/`, `device.hpp`

The device is the thing the user trusts INSTEAD of the host, so the host must
not treat what comes back from it as trusted. Responses cross a boundary in
both directions: a malicious or spoofed device can return key material, a
signature over the wrong data, or a malformed reply the host parses; a
compromised host can ask the device to display one thing and sign another,
or coax key material out of it.

Parsing of device replies (`exchange`, `receive_secret` and the protobuf paths
under `device_trezor/trezor/`) is untrusted input. A change that widens what
the host accepts belongs in a review even though "the device is trusted"
sounds like it settles the question. The Trezor `BridgeTransport` speaks HTTP
and JSON to `127.0.0.1:21325` (or `TREZOR_BRIDGE_PORT`), so whatever local
process holds that port can pose as the device. `UdpTransport` is always compiled
but used only with `WITH_DEVICE_TREZOR_UDP` or `WITH_TREZOR_DEBUGGING`.

## 8. Wallet cache, key files and other blobs the user is handed

Opening a wallet parses an on-disk cache. "The user opened a file they were
given" is a realistic threat model for custodial and multi-user setups. Treat
cache parsing as untrusted input, not as trusted local state.

Knowing the wallet's keys is not a precondition. `wallet2::load_wallet_cache`
decrypts with ChaCha20 (no MAC) and tries `binary_archive` (types in
`src/wallet/wallet2_basic/`) then older `boost::archive` schemes; if all of
those fail it parses the raw file as an **unencrypted**
`portable_binary_iarchive`, then `binary_iarchive`. The post-load index
checks against `m_transfers` are in the same function.

Other blobs that arrive from outside and are parsed or believed:
`import_key_images`, `import_outputs_from_str`, `import_multisig`, `parse_uri`,
and the proof checkers (`check_tx_proof`, `check_spend_proof`,
`check_reserve_proof`). A proof that verifies when it should not is a finding,
because its whole purpose is to convince a stranger. `monero-blockchain-import`
parses `.raw` bootstrap files; its `--dangerous-unverified-import` skips
verification.

## 9. Consensus validation

`src/cryptonote_core/blockchain.cpp`, `tx_pool.cpp`,
`tx_verification_utils.cpp`, `src/cryptonote_basic/`, `src/ringct/`,
`src/crypto/`, `src/hardforks/`

Every node must reach the same verdict on every block and transaction, and
nothing may create money. Ask both questions of any change here. The input is
an ordinary transaction from anyone or an ordinary block from any miner. A
miner does not need a large share of hashrate to put one crafted block on
chain, because even a small miner finds blocks every day. Only reorgs and
withholding need a large share.

**Which layer a rule lives in matters as much as the rule.** A rule that moves
between layers can silently stop running on some path.

| Layer | What it enforces | Where it does not run |
| --- | --- | --- |
| `ver_non_input_consensus` (`tx_verification_utils.cpp`) → `core::check_tx_semantic` | blob ≤ `CRYPTONOTE_MAX_TX_SIZE`, weight ≤ `get_transaction_weight_limit`, version bounds, output point validity (`check_outs_valid`), amount overflow (`check_inputs_overflow`, `check_outs_overflow`), key-image domain (`check_tx_inputs_keyimages_domain`) and uniqueness within the tx, RingCT semantics and batched range proofs | below the fast-sync height |
| `Blockchain::check_tx_outputs` | which RCT types, output types and view tags each fork allows | below the fast-sync height (only `ver_non_input_consensus` calls it) |
| `Blockchain::check_tx_inputs` | ring size, at least two outputs, inputs sorted by key image, the 10-block minimum age (`CRYPTONOTE_DEFAULT_TX_SPENDABLE_AGE`), unlock times, key image not already spent, ring signatures | below the fast-sync height, and for alt-chain blocks until a reorg applies them |
| `prevalidate_miner_transaction`, `validate_miner_transaction` | the coinbase: one `txin_gen` at the block height, unlock at height + `CRYPTONOTE_MINED_MONEY_UNLOCK_WINDOW`, the RCT type and version each fork requires, and the claimed amount against reward plus fees | the coinbase never goes through `check_tx_semantic`, so its output keys are not checked as valid points the way other outputs are |
| The DB | no duplicate key image or txid anywhere in the chain | — |
| `tx_memory_pool::add_tx` (**relay only**) | minimum fee (`check_fee`), `MAX_TX_EXTRA_SIZE`, `unlock_time == 0`, conflicts with key images already in the pool | blocks. A transaction mined by someone else skips all of these |

Two consequences reviewers miss:

- **Relay rules are not consensus.** Fee, `tx_extra` size and unlock time are
  pool policy today. A change to them is not a fork, and a change that applies
  them to block validation **is** one. Several become consensus rules at the
  FCMP++ fork, so check which version a change targets.
- **The pool feeds the block template.** `fill_block_template` takes pool
  transactions without re-running `ver_non_input_consensus`; it relies on
  `tx_memory_pool::validate` re-checking the pool when the fork changes. A pool
  that holds anything consensus rejects makes every default miner build an
  invalid block, which stops the chain.

**Economic rules.** All integer arithmetic, and some of it lives in
`contrib/epee` (`mul128`, `div128_64` in `int-util.h`; `misc_utils::median`
and `rolling_median_t`), so a change there can be a consensus change.

- *Reward and emission:* `get_block_reward` in `cryptonote_basic_impl.cpp`.
  `MONEY_SUPPLY` drives the base reward, `FINAL_SUBSIDY_PER_MINUTE` the tail
  emission, and the penalty cuts the reward for blocks above the median.
  `HF_VERSION_EXACT_COINBASE` requires the coinbase to claim the amount
  exactly.
- *Block weight:* short-term and long-term medians
  (`update_next_cumulative_weight_limit`, `get_next_long_term_block_weight`,
  `CRYPTONOTE_LONG_TERM_BLOCK_WEIGHT_WINDOW_SIZE`,
  `CRYPTONOTE_SHORT_TERM_BLOCK_WEIGHT_SURGE_FACTOR`). A block may weigh at most
  twice the effective median. Transaction weight is not blob size
  (`get_transaction_weight`, the bulletproof clawback).
- *Fees:* `get_dynamic_base_fee` derives the relay fee from the reward and the
  median.

Past consensus bugs in this area have been caches: a value computed from a
cache on one node and from the chain on another, or a rolling median not
resized when its window changed at a fork. **Every consensus value must be
recomputable from the chain alone**, not from cache warmth, startup order or
which node did a refresh. Spam that grows the medians, and miners that hold
them down, are both studied attacks. Rate a change that makes either cheaper
by what it does to fees and to the cost of verifying a block.

**Difficulty and time.** `next_difficulty` in `difficulty.cpp` (window
`DIFFICULTY_WINDOW`, `DIFFICULTY_CUT` dropped from each end, `DIFFICULTY_LAG`)
has two callers that must agree: `get_difficulty_for_next_block`, which is
cached, and `get_next_difficulty_for_alternative_chain`. `check_hash` has
64-bit and 128-bit paths. `check_block_timestamp` requires a timestamp not below
the median of the last `BLOCKCHAIN_TIMESTAMP_CHECK_WINDOW` blocks and not above
local time + `CRYPTONOTE_BLOCK_FUTURE_TIME_LIMIT`. The upper bound reads the
node's **clock**, so it is the one acceptance rule that is not a function of
the chain. That is tolerable only because the rejection is not permanent.
Ask whether a change makes the verdict depend on anything local. Timestamps
steer difficulty, so a miner who controls them steers it.

**Proof of work.** `get_block_longhash`. RandomX keys change every
`SEEDHASH_EPOCH_BLOCKS` with a lag of `SEEDHASH_EPOCH_LAG` (`rx_seedheight` in
`rx-slow-hash.c`). Verifying a block under any seed other than the current
one is far slower, and a new seed means rebuilding a cache. So the order of
checks on blocks from peers matters: is PoW checked before any expensive work,
and can a peer make the node switch seeds repeatedly? Both epoch values are
read from environment variables whatever the network. RandomX's JIT, its
interpreter and every architecture must produce identical hashes.

**Trust roots.**

- *Hard-coded checkpoints* (`src/checkpoints/checkpoints.cpp`): no alt block
  at or below the last checkpoint is allowed. Otherwise there is **no maximum
  reorg depth**.
- *Fast sync* (`src/blocks/checkpoints.dat`, its sha256 pinned in
  `blockchain.cpp`, `--fast-block-sync` on by default on mainnet): up to the
  embedded height, which is nearly the whole chain at release, blocks are
  accepted without PoW, `ver_non_input_consensus` or input checks. For that
  history, supply integrity rests on the release binary. A change to that file,
  to its hash, or to what the fast path skips changes what a new node trusts.
- *DNS checkpoints* are enforced only with `--enforce-dns-checkpointing`.

**Hard forks.** Heights are in `src/hardforks/hardforks.cpp`, the
`HF_VERSION_*` constants in `src/cryptonote_config.h`. `HardFork::check`
requires the block's major version to equal the scheduled version and its minor
version (the vote) to be at least that. Any behaviour change must be gated to
the correct version. Ask explicitly whether an ungated change makes old and new
nodes disagree, and check `>` against `>=` at the boundary and the grace forks
where two values are allowed.

**Reorgs.** `switch_to_alternative_blockchain`,
`rollback_blockchain_switching`, `pop_block_from_blockchain`. Popped
transactions return to the pool already marked verified. Alt blocks are stored
and only fully validated when a reorg applies them. Check that an alt-chain
path applies the same rules as the main-chain path; they have diverged before.

**Determinism.** No floating point anywhere in consensus; keep it that way.
Watch for `assert` guarding consensus arithmetic, because it is compiled out
of release builds, and for `size_t` arithmetic that differs on 32-bit. Watch
also for behaviour that depends on unordered-container iteration, sort
stability, `getenv`, build flags or DB contents. A second, independent node
implementation (Cuprate) now follows these rules, so a monerod quirk is itself
a split risk.

**Canonical encodings.** Key images are compared byte for byte, which is only
sound because decoding is canonical: `ge_frombytes_vartime` and
`fe_frombytes_vartime` reject non-canonical points, and `sc_check` rejects
non-canonical scalars. Replacing a decoder (a Rust library, `mx25519`, a new
`ge_*` routine) must keep identical accept and reject behaviour on every
input, or two encodings of one key image both become spendable.

**FCMP++ and Carrot** (`src/fcmp_pp/`). Built and linked into `ringct`, but
on master it has no caller in `src/` outside its own directory. Carrot is not
merged and no `HF_VERSION_FCMP*` exists yet (see `codebase-notes.md`). Rate it
as it will run once activated, not as dead code. When it activates it adds
consensus **state**, not only new rules:

- a curve tree of every spendable output, with a root each block commits to
  and each transaction references;
- tree growth as outputs unlock, and trimming on reorg;
- a migration that inserts every historical output.

Questions it raises:

- Does tree building handle every output already on chain, malformed ones
  included, identically on every node?
- Is the key-image generator taken from the same point it always was, so no
  output gains a second key image across the fork?
- Is the referenced tree root bounded and checked against the right layer count?
- Do reorgs of any depth restore the tree exactly?

The Rust side builds with `panic = "abort"` and `overflow-checks = true`
(`fcmp_pp_rust/Cargo.toml`). Any panic or overflow a transaction can reach
becomes a node abort the C++ cannot catch: on a relayed transaction, every
node. Proof verification also costs far more per input than ring signatures,
so verification cost per byte becomes a DoS question.

FCMP++ removes ring-statistics attacks and decoy selection. Fee, output-count
and `tx_extra` fingerprints and every network-level leak remain.

## 10. Build and CI

`CMakeLists.txt` files, `.github/workflows/`, `contrib/depends/`,
`contrib/guix/`, `.gitmodules`, `src/fcmp_pp/fcmp_pp_rust/Cargo.toml` and
`Cargo.lock`

Not consensus code, but a supply-chain surface. A change that alters what gets
compiled in, disables a hardening flag, changes a dependency source or pinned
hash (including a submodule commit or a Cargo git `rev`), or weakens a release
workflow is worth reporting even though it is not a memory-safety bug.
Removal of a hardening flag (`-D_FORTIFY_SOURCE`, stack protector, RELRO, PIE)
is a genuine finding. The Rust build runs `cargo build --locked`, and a crate
pinned by `branch` is held only by `Cargo.lock`, so dropping `--locked` would
be a finding. Release integrity rests on the Guix reproducible builds and the
signed hashes.

## 11. DNS and the other ways the node learns about the world

`src/common/dns_utils.cpp`, `src/common/updates.cpp`, `node_server::get_dns_seed_nodes`,
`core::check_updates`, `core_rpc_server::on_get_public_nodes`

- **Seed nodes.** A fresh node looks up DNS seeds. Answers are thrown away
  only when DNSSEC is available and fails to validate; an unsigned answer is
  accepted. So a resolver or on-path attacker can supply the first peers of a
  new node, which helps an eclipse attack. Seed lookups are skipped behind
  `--proxy` unless `--proxy-allow-dns-leaks` is set.
- **TXT records** (`load_txt_records_from_dns`: DNSSEC-valid, at least two,
  majority agreement) feed update checks (`--check-updates`, default
  `notify`), DNS checkpoints (only with `--enforce-dns-checkpointing`) and the
  DNS blocklist (`--enable-dns-blocklist`, default off). Whoever controls the
  moneropulse zones is trusted here, by design.
- **Public nodes.** Peers advertise an RPC port in their handshake and
  peerlist entries. `get_public_nodes` (restricted surface) serves those
  entries to wallets, which offer them as remote nodes. A P2P peer can
  therefore nominate itself as a wallet's remote node, which leads to
  section 4.
- **ZMQ pub** (`--zmq-pub`, off by default) has no authentication and no
  loopback check on the address the operator gives it. Its `ZMQ_XPUB` socket
  parses subscription requests from anyone who connects.

Removed, and so not surfaces any more: bootstrap-daemon mode, RPC payments
(`rpc_credits_per_hash` is still parsed from peers and unused), and UPnP
(`--igd` / `--no-igd` are accepted and do nothing). Notify hooks
(`--block-notify`, `--tx-notify` and the rest) go through `tools::Notify` and
`tools::spawn` with `execve` and no shell, and substitute only hashes and
integers.

## Severity

The ladder is `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, and the finding standard
uses it as written here. First decide which asset the defect harms and who can
reach it, then apply the modifiers below.

**CRITICAL** — harm to the whole network, or theft with no special position.

- Counterfeiting or inflation reachable by anyone who can submit a
  transaction or mine a block: range proof, balance, key-image uniqueness or
  subgroup checks.
- A consensus divergence between nodes running shipped code on an ordinary
  block or transaction, including a fork-gating error in staged code that
  would split the chain when it activates.
- A crafted transaction or block that crashes or stalls **every** default node
  it reaches, because relay or mining delivers it everywhere. A panic in the
  Rust code under consensus counts, since it aborts the node.
- Anything that stops the chain: a pool or template rule that makes default
  miners build invalid blocks, or a valid block nodes cannot accept.
- Memory corruption or code execution reached from an unauthenticated peer,
  the restricted RPC, a remote daemon talking to a wallet, or on-chain data
  parsed by a wallet.
- A wallet crediting funds that do not exist or cannot be spent, triggered by
  any sender or miner.

**HIGH** — harm to individual nodes or users, from a position anyone can
take.

- A relayed transaction or a block that is cheap to make and expensive to
  verify, slowing every node it reaches without crashing them.
- A consensus rule that no longer holds as intended, when every node still
  agrees and nothing is minted, such as a limit or minimum age that can be
  bypassed. If the rule protects supply, it is CRITICAL instead.
- Crash, permanent hang or OOM of a default node by an unauthenticated peer or
  restricted-RPC client.
- A remote daemon crashing a wallet, making it spend more than the user chose,
  or learning which outputs or transactions are the user's.
- A privacy break that weakens every transaction the reference wallet makes,
  or that is written into the chain: decoy-selection bias, a wallet
  fingerprint, a link between addresses or between the real spend and the
  decoys.
- Any protocol-level privacy break, defined below the tiers.
- Theft or key disclosure by a counterparty the protocol is meant to tolerate:
  a multisig co-signer, the hot wallet in cold signing, a host against a
  hardware device.
- Control of a wallet by someone who was not given it: a bypassed wallet-rpc
  login or restriction, or an unprivileged local process reaching it.

**MEDIUM** — it needs a significant position, or the effect is limited.

- An on-path network position or control of the DNS resolver, for anything
  short of the CRITICAL rows.
- A miner below 50% hashrate exploiting reorg depth, timestamps or block
  withholding.
- Resource exhaustion that slows a node down but does not crash it (the VRP
  pays less for "DoS's which do not crash a node remotely").
- An out-of-band wallet proof check that accepts a forged proof:
  `wallet2::check_tx_proof`, `check_spend_proof`, `check_reserve_proof`,
  `check_tx_key` or a message signature (`wallet2::verify`). A consensus
  proof that accepts a forgery (a range proof, CLSAG or MLSAG, the FCMP++
  membership proof or SA/L) is CRITICAL: inflation or theft.
- A privacy leak to an observer who must be in a particular place at a
  particular time, which is not written into the chain and is not a
  protocol-level break, such as linking a node's Tor and clearnet identities.
  A flaw in Dandelion++ that reveals where transactions came from is
  protocol-level, and HIGH.
- A sender making a wallet unable to spend or sweep, without loss.
- A HIGH effect that only works if the user takes an action the attacker
  needs, such as visiting a page while the daemon runs (a cross-site
  `stop_daemon`).

**LOW** — defence in depth, or a real defect with no attacker path today.

- Code with no production caller, or reachable only from trusted
  configuration or an operator who opened the admin interface on purpose.
- Theoretical side channels with no demonstrated measurement path.
- Attacks needing more than 50% of hashrate, which the VRP puts out of scope.
- Hardening: a missing check that something else already enforces.

**A protocol-level privacy break is HIGH at least.** It is a flaw in what
Monero's protocol itself reveals, rather than one wallet's or one node's
mistake: the transaction format and what consensus accepts in it, the
membership and spend proofs (rings, CLSAG, FCMP++), key images, output and
address construction (subaddresses, Carrot, view tags, encrypted amounts), or
the relay protocol's origin hiding (Dandelion++). It lets an observer link a
spend to the output it spends, link outputs, addresses or transactions to
each other, learn an amount, or find where a transaction came from, for users
who follow the protocol as designed. It is HIGH whichever wallet built the
transaction and wherever the observer has to sit: the observer-position
MEDIUM row and modifiers 3 and 4 below do not lower it. Only modifier 6 does,
for code that is not and will not be live. It is CRITICAL where a CRITICAL
row also applies, such as the same flaw letting a proof be forged.

**Modifiers.**

1. **Propagation raises.** If the input is relayed or mined before it does
   harm, it reaches every node, not one. A crash on validating a transaction
   that relays is CRITICAL, not HIGH.
2. **Permanence raises.** A privacy leak recorded in a transaction cannot be
   fixed by a later release. Do not discount it because a fix would be easy.
3. **User interaction lowers by one tier.** It must be an action the attacker
   needs the victim to take (visit a page, open a file, approve a signing
   request), not the ordinary use of the software. Syncing, receiving a
   payment and running `wallet-rpc` unattended are ordinary use.
4. **Non-default configuration lowers only for rare configurations.** Rate
   against the people who actually run that configuration. Public remote
   nodes run `--restricted-rpc` or `--rpc-restricted-bind-port`, exchanges
   run `wallet-rpc`, and privacy-conscious users run `--tx-proxy` and
   `--anonymous-inbound`. A bug in those is not "unusual configuration". A
   bug that needs `--dangerous-unverified-import`, `--disable-rpc-login` on a
   public interface, or a debug build is.
5. **Staged code is rated as it will run** (FCMP++, anything a future fork or
   new `RCTType` switches on).
6. **Unreachable lowers to LOW. It does not refute** (see the verifier).

## Severity anchoring by boundary

A quick ceiling per boundary. It is a starting point, and the tiers and
modifiers above decide the final rating.

| Reached from | Typical ceiling |
| --- | --- |
| Consensus validation: inflation, a consensus proof accepting a forgery, or divergence between shipped nodes | CRITICAL |
| Relayed transaction or mined block that crashes nodes, or anything that halts the chain | CRITICAL |
| Relayed transaction or block that is cheap to make and expensive to verify; a non-supply consensus rule bypassed by everyone alike | HIGH |
| P2P, restricted RPC, daemon → wallet, or on-chain data → wallet: memory corruption | CRITICAL |
| On-chain data → wallet: wrong balance credited | CRITICAL |
| P2P or restricted RPC: crash, hang or OOM of one node | HIGH |
| Malicious daemon → wallet: crash, wrong spend, owned-output leak | HIGH |
| Privacy break in the reference wallet's transactions, or written on chain | HIGH |
| Protocol-level privacy break, from any observer position | HIGH at least, never lowered by position, configuration or user action |
| Co-signer, cold-signing partner or device/host: theft or key disclosure | HIGH |
| On-path network, DNS, or miner below 50% | MEDIUM |
| Slowdown without a crash; forged wallet proof (tx, spend, reserve, message) accepted; observer-position privacy leak that is not protocol-level | MEDIUM |
| Cross-site or unattended reach to the default-unrestricted daemon | its effect, one tier lower for the visit; NOT the row below |
| Unrestricted-RPC-only reached by a client the operator pointed there, or test-only | LOW, usually not reportable |
| More than 50% of hashrate | LOW (out of the VRP's scope) |

## How this maps to the project's own scale

Monero's Vulnerability Response Process (`monero-project/meta`,
`VULNERABILITY_RESPONSE_PROCESS.md`) has three tiers. HIGH there means "impacts
network as a whole … results in the loss of monero"; MEDIUM means "impacts
individual nodes, routers, wallets, or must be carefully exploited"; LOW means
"not easily exploitable or is low impact". Its HIGH is roughly this file's
CRITICAL plus fund-loss HIGH. Its MEDIUM is roughly the rest of HIGH and this
file's MEDIUM. Both of its upper tiers get a point release. The VRP requires
any report made with AI assistance to disclose that and to include a working
proof of concept and logs. A finding whose confidence rests on reading alone
is a lead for a human to confirm, not a report to send.
