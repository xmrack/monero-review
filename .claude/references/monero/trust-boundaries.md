# Trust boundaries

Where untrusted data enters Monero, and what "untrusted" means at each point.
Use this to answer the reachability question concretely: name the boundary, then
trace the call sequence from it to the changed code.

Verify locations against the checkout — this is a map, not a substitute for
reading the tree. Use the symbol index (`readtags -t tags <sym>` for
definitions, `cscope -d -L3 <fn>` for callers) rather than assuming.

## 1. P2P messages — any peer, no authentication

`src/cryptonote_protocol/cryptonote_protocol_handler.inl`

Handlers named `handle_notify_*` and `handle_response_*` receive structures
that a peer fully controls: new blocks, new transactions, fluffy blocks, and
responses to our own object requests. Anyone can connect and send these.

The response handlers are worth particular attention: code often assumes a
response corresponds to what was requested, and a malicious peer is under no
obligation to comply. Mismatched counts, unexpected ordering, and absent
entries are all reachable.

Framing and message dispatch live in
`contrib/epee/include/net/levin_protocol_handler_async.h`.

## 2. RPC — public or admin, and the difference matters

`src/rpc/core_rpc_server.cpp`, handlers named `on_*`

The server distinguishes **restricted** (public, what a remote wallet talks to)
from **unrestricted** (full admin). Check which applies to the handler you are
looking at before claiming remote reach — the gating is in the code, not
inferable from the method name.

A finding reachable only by an unrestricted client is usually not a finding,
because that client is already trusted with far more. A finding on the
restricted surface of a public node is the real thing.

**That holds for a client the operator pointed at the admin interface, and
not for one that arrived uninvited.** The daemon is unrestricted by default,
so a browser page or a co-resident process reaching `127.0.0.1:18081`
cross-site has not been trusted with anything — it took an interface nobody
opened for it. Reach of that shape is a finding at the severity its effect
earns, and the `Unrestricted-RPC-only` row below does not apply.

The case this exists for: an unauthenticated cross-site `GET` reaching
`/stop_daemon` on a default daemon. Ask which one you have before you lean on
the paragraph above.

## 3. Deserialization — the widest surface

`src/serialization/`, `contrib/epee/include/serialization/`

Every P2P message, RPC body, and wallet cache passes through here. This is
where attacker-chosen counts meet `resize()` and `reserve()`.

It is also where most memory-safety findings die: the layer imposes limits
before application code runs. See `refutations.md` — trace the field's actual
constraint before reporting.

## 4. Daemon → wallet — the daemon is NOT trusted

`src/wallet/wallet2.cpp`

This boundary is easy to overlook and has repeatedly produced real bugs. A
wallet connecting to a remote node treats that node's responses as untrusted
input. `process_parsed_blocks`, `process_new_transaction`, and
`process_new_blockchain_entry` all parse data a malicious or compromised daemon
chose.

The threat model that matters: a user runs a GUI wallet or `wallet-rpc` against
a public remote node. Anything the node can say that corrupts wallet memory,
crashes it, or induces a wrong spend is in scope, and severity is high because
the wallet holds keys.

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

The enforcement is no longer in `wallet2.cpp`. `pending_tx_validation.h`
declares `sanity_check_pending_tx`, `sanity_check_pending_tx_set` and
`check_consistent_ins_outs`, and the `wallet2.cpp` multisig paths a reviewer
would go to are thin wrappers around them. Callers, at line numbers as of
`3c9eab1559a8`: `sign_tx` (7892), `parse_tx_from_str` (8173),
`make_multisig_tx_set` (8273), `parse_multisig_tx_from_str` (8340),
`load_multisig_tx` (8386), `sign_multisig_tx` (8429) and `cold_sign_tx` (11535,
11570). Read the validation file before concluding a blob goes unchecked.

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

## 8. Consensus validation

`src/cryptonote_core/blockchain.cpp`, `tx_pool.cpp`, `src/ringct/`,
`src/crypto/`

Block and transaction acceptance. Bugs here are consensus-critical by
definition: the question is not just "does it crash" but "would a node running
this code reach a different verdict than the rest of the network on the same
input".

Fork gating lives in `src/hardforks/hardforks.cpp` and the `HF_VERSION_*`
constants. Any behaviour change must be gated to the correct version, and you
should ask explicitly whether an ungated change makes old and new nodes
disagree.

## 9. Build and CI

`CMakeLists.txt` files, `.github/workflows/`, `contrib/depends/`

Not consensus code, but a supply-chain surface. A change that alters what gets
compiled in, disables a hardening flag, changes a dependency source or pinned
hash, or weakens a release workflow is worth reporting even though it is not a
memory-safety bug. Removal of a hardening flag (`-D_FORTIFY_SOURCE`, stack
protector, RELRO, PIE) is a genuine finding.

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
