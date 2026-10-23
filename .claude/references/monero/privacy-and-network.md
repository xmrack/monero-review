# Privacy and the P2P network: what the research shows, and what to check

> Nothing in this resource is intended to express any opinions for any audit firms. Please review their source documents for their own words. Summaries here may not fully cover the nuances of their opinions and observations.

Published research on Monero's on-chain and network privacy, turned into
questions for reviewing a pull request. Read the `privacy` section of
`lenses.md` and the adversary table in `trust-boundaries.md` first.

Paths and symbols were checked on master `8340be5e9` (2026-10-19); when the
tree disagrees, the tree wins. Cite files and symbols, never line numbers.
Paper numbers are quoted as stated and attributed. Where a paper describes an
older release and master differs, this file says so.

Rating rule: a protocol-level privacy break is HIGH at least, from any
observer position; rate everything else with `trust-boundaries.md`.

## 1. Attacker positions the research demonstrates

Name one of these in every privacy finding.

### Passive spy nodes

A spy node runs ordinary software, accepts connections and logs the first
peer that sends it each transaction.

- Kopyciok, Schmid and Victor (2025) classified 14.74% of the peers they
  reached (13.19% of reachable peers) as non-standard, with one entity
  estimated to control at least 1,582 nodes. On average 20.37% of their
  measurement nodes' incoming and 15.26% of outgoing connections went to
  non-standard peers. With the community ban list enabled, outgoing dropped to
  7.13%, but 1,022 of the anomalous IPs were not on the list.
- Kirschner (2026) found 4,840 of 20,560 active nodes (24%) sending peer lists
  larger than the 1,000-entry white list; they take part in 67% of edges.
- Rucknium's `monerosim` analysis (2026), 100-node networks of real
  `monerod`, all reachable: first-spy macro-averaged recall 0.30474 with 30%
  spy nodes and 0.35188 with 35%, the Dandelion++ bound (recall about the spy
  share). The author concludes the implementation works as designed.
- MRL (2024) recommended operators opt in to the spy-node ban list. Rucknium
  measured about 15% of a default node's outbound connections to listed IPs,
  about 5% with rbrunner's draft subnet de-duplication (2025), and notes spy precision scales
  roughly with the square of that share.

A spy learns the IP that first relayed a transaction to it and partial
topology: `levin_notify.cpp`, `handle_timed_sync`, `handle_handshake`.

### Topology learners

- Kopyciok et al. summarise Cao et al. as recovering connections with 97.98%
  recall from shared `last_seen` timestamps. Master zeroes them when sending
  (`get_peerlist_head` with `anonymize`) and receiving (`sanitize_peerlist`);
  Kopyciok et al. saw 288 IPs in one AS still sending placeholder values.
- Gao et al. (2025) inferred neighbours without timestamps, from how often an
  address recurs in a peer's lists: precision 68.73% to 79.35% on one week of
  data and 73.00% to 82.99% on three. They describe sharing 250 entries from
  the top 300 white-list entries; master shuffles the whole white list.

Topology is an input to origin inference, not a break on its own.

### Eclipse attackers (active Sybil)

- Shi et al. (NDSS 2025) eclipsed their own reachable mainnet node with 1,020
  IPs: 20 flood the gray list via timed-sync responses, 1,000 fill the white
  list via inbound handshakes, and a "connection reset" (conflicting double
  spends) made the victim drop honest peers. Averages over ten runs: 65.26 s
  to take every outgoing slot, 155.97 s for a full eclipse. Same-IP limits
  were relaxed to stand in for 1,000 real IPs (about $400 a month). Master no
  longer drops a peer for a double spend (section 3).
- Shi et al. (CCS 2026) eclipsed unreachable (no-inbound) nodes. "Nyx"
  poisons reachable nodes' lists, lets timed sync carry the records, and
  rides `update_sync_search` churn: all 12 outgoing slots in about 27 minutes
  in a 1,200-node emulation, held for the 18.2-hour run. "Moros" poisons seed
  nodes: newborn nodes eclipsed within 8 s on mainnet (controlled targets).

An eclipse attacker learns every transaction the victim originates, with
certainty, and can censor, feed a chosen chain, and aid selfish mining and
partition (Shi et al. 2025).

### Tor and I2P adversaries

Shi et al. (ProxyMark, 2026) combine malicious hidden services with malicious
Tor relays. They report: role (hidden service or client) identified at 100%
precision and recall; 7 to 11 of 12 outbound hidden-service slots taken after
restarts, 8 to 10 of 10 after periodic replacement; proxy selection raised
from 15.3% to 35.7% with one slot by advertising inflated heights; watermark
linking of identifier to IP at 100% precision, 93.8% recall for hidden
services and 91.4% for clients. That last step needs a malicious entry guard:
179 relays of 20 MB/s give 0.12 (hidden services) and 0.06 (clients).

It learns a Tor-using node's transactions and real IP, via
`node_server::send_txs`, the noise channels, the `get_out_connections` height
filter and `handle_timed_sync`. MRL (2026) noted Dandelion++ stems over Tor
would risk blackholing.

### Passive chain analyst

- Kumar et al. (2017) traced 88% of inputs to February 2017 with certainty
  (65.9% had no mix-ins; the cascade did the rest). "Guess newest" had a
  98.1% true-positive rate, 99.5% under uniform and 96% under triangular
  sampling. Merged outputs gave 87.3% true positives on non-RingCT inputs.
  Nine mix-in counts were used by one input each, identifying its user.
- MRL-0001 (2014) showed that trivial rings start chain reactions, and that
  with a minimum of one mix-in an attacker who floods the chain with its own
  outputs can trace later users; larger minimums make reactions die out.
- MRL-0004 (2015) added age-based guessing, joint-spend association and
  same-block combinatorics, recommended a network-wide minimum mix-in, and
  warned that any fixed decoy distribution can diverge from real behaviour.
- MRL-0007 (2018) generalised spent-output sets. In October 2018 it flagged
  86% of non-confidential outputs and 5 of 7,445,622 confidential ones, so the
  effect on modern rings is negligible.
- ACK-J (2022): classifiers trained on labelled stagenet and testnet rings
  reached 13.30% macro F1 on mainnet samples against 9% random guessing.
- Yang, Xu and Zhu (MWM) reached F1 0.9316 on pre-RingCT data, but 0.1084
  against a 0.0909 baseline on ACK-J's ring-size-11 stagenet set. In their
  synthetic test, gamma sampling held every method near random, while uniform
  and triangular sampling left F1 near 0.8 above ring size 10. They conclude
  gamma sampling was a sound choice.
- Rucknium's OSPEAD estimates (MRL, 2025): the gap between real spend ages and
  the current decoy distribution gives an attacker 23.5% success on average
  since the August 2022 fork (effective ring size 4.2 of 16); a fitted
  distribution would give 7.6% (13.2).
- Rucknium's black-marble analysis of the suspected 2024 spam: mean effective
  ring size about 5.5, with under 1% of rings reduced to one member. MRL saw a
  larger ring as the best deterrent; work moved to FCMP++.
- Venturi et al. (ART, 2025) classified transactions from ring count, ring
  size, output count, fee and member ages: F1 0.857 on 19 WannaCry-linked
  transactions against 150 others, presented as a first step.
- Kopyciok et al. (DEX, 2025) linked Haveno trades across chains from shape,
  a shared high fee and broadcast timing: 671 candidate swaps among 371,206
  transactions in 14 days; 50 trades matched to a median of one Bitcoin
  transaction.

### Signer-side covert channel

Cinal et al. (2025, revised 2026) hide about 440 bytes per CLSAG input (ring
of 16) in the random scalars for decoy positions, undetectable even with the
view key; honest users lose nothing. Whatever picks those scalars or decoys
can exfiltrate data unseen, so a third-party signer, device or library that
supplies them deserves the scrutiny of one that holds keys.

### Miners

Lee and Kim (2025) attributed Qubic's blocks by a coinbase extra-nonce
pattern (share up to 23-34% in ten intervals, longer orphan forks while
mining selfishly). Coinbase `tx_extra` fingerprints pools, and a reorg can
force a spend to be rebuilt on the new branch (section 2, ring reuse).

## 2. Decoy selection

### What the analyses agree on

- Ring size and decoy distribution are the two levers. MWM's synthetic test
  shows that with a poor sampler, larger rings barely help. MRL backed one fixed
  ring size for everyone (2018) and chose 16 for the 2022 fork (2021);
  wallet-side binning was deferred.
- Real spends are young. Kumar et al., MRL-0004, MWM and OSPEAD all find the
  newest members disproportionately real unless decoys match spend age.
- Anything a wallet does that others do not is a fingerprint. Kumar et al.
  note it for wallet-specific sampling, MRL (2021) for one alternative
  wallet's old algorithm, ACK-J for non-uniform fees ("anonymity puddles").
  MRL discussion of a partial OSPEAD rollout found early adopters could fare
  worse than 23.5%, though later simulations suggested a no-fork rollout may
  still beat the status quo.
- Joint spending links outputs (Kumar Attack II, MRL-0004); only the wallet
  can avoid it.

### Properties the code must keep

`gamma_picker` (`wallet2.h`, `wallet2.cpp`) and `wallet2::get_outs`:

1. **Distribution.** `GAMMA_SHAPE` and `GAMMA_SCALE` sample the log of an age
   in seconds; `pick` maps it to an output index with `average_output_time`
   (at most a year of `rct_offsets`), then picks a block and an output
   uniformly within it. Changing any of these changes every reference-wallet
   ring; ask for the analysis.
2. **Unlock window.** Ages at or below `DEFAULT_UNLOCK_TIME` are redrawn
   uniformly within `RECENT_SPEND_WINDOW`; larger ages are shifted down by
   `DEFAULT_UNLOCK_TIME`. `end` excludes only the youngest
   `CRYPTONOTE_DEFAULT_TX_SPENDABLE_AGE - 1` blocks; the wallet spends once
   `wallet2::is_transfer_unlocked` allows, and `Blockchain::check_tx_inputs`
   enforces the age. Rule: every age a real input can have, a decoy can have.
   Guard test: `select_outputs.exact_unlock_block`
   (`tests/unit_tests/output_selection.cpp`).
3. **Daemon data is checked.** `get_outs` rejects a distribution that is
   non-monotonic, too short, or does not cover the wallet's own highest index,
   and throws unless the daemon returns the real output with its key, mask and
   `unlocked`, so a node cannot serve dummy data and watch which entry the
   wallet corrects.
4. **The daemon does not learn the real output's position.** Picks are
   requested with the real one mixed in, each ring's request section is
   sorted, the pick order is kept in `secret_picking_order`, and finished rings
   are sorted by global index.
5. **Same ring across forks.** Rings are saved with `set_rings` and reused
   from `existing_rings` (`ringdb`, `src/wallet/ringdb.cpp`). MRL-0007: two
   rings with one key image on two branches reveal the spend in their
   intersection.
6. **Sanity floor.** `tx_sanity_check` (`tx_sanity_check.cpp`) requires at
   least 80% unique indices and a median index at least 60% of available
   outputs, catching a daemon that skews decoys old. `get_outs` retries on
   failure; `on_send_raw_tx` runs it when `do_sanity_checks` is set.
7. **Consensus fixes shape.** `Blockchain::check_tx_inputs` requires one ring
   size across a transaction and exactly the fork's size, so Kumar et al.'s
   unique-mix-in fingerprint cannot recur. It also requires at least two
   outputs (`HF_VERSION_MIN_2_OUTPUTS`), which MRL adopted after single-output
   transactions were found linkable (2019). `tx_memory_pool::add_tx` refuses
   to relay a nonzero `unlock_time` or `tx_extra` above `MAX_TX_EXTRA_SIZE`
   (MRL agreed on timelock 0 in 2024). Consensus sets only a minimum fee
   (`Blockchain::check_fee`); Rucknium (2024) estimated about 5% of
   transactions pay non-standard fees.
8. **Joint spending is discouraged.** `wallet2::get_output_relatedness` scores
   same-transaction, same-block and nearby-block pairs; input selection
   (`pick_preferred_rct_inputs`, `create_transactions_2`) prefers unrelated
   outputs.

### Privacy lessons from decoy-selection bugs

- jeffro256's 10-block post-mortem (2023, HIGH): `end` excluded one block too
  many (the transaction lands in the next block, not the tip), so wallets
  v0.13.0.2 to v0.18.2.1 never picked 10-block-old decoys but could spend
  10-block-old outputs. Custom wallets diluted the heuristic; the author notes
  statistical analysis of the distribution would have found it.
- MRL (2021) recorded earlier fixes to integer truncation and the recent-spend
  window, and (2023) that the 10-block lock guards against reorgs.

### Regression shapes

- **Off-by-one in the unlock window.** Any edit to `end`,
  `DEFAULT_UNLOCK_TIME`, `RECENT_SPEND_WINDOW`, `rct_outs_available`,
  `CRYPTONOTE_DEFAULT_TX_SPENDABLE_AGE` or the unlock rule: the youngest
  spendable and youngest pickable ages must match, counted from the next
  block.
- **Distribution change.** A new sampler, parameter, averaging window,
  coinbase special case (Kumar et al. found coinbase spent faster) or binning
  changes every user's rings and fingerprints early adopters. MWM's
  same-block sampling is a research proposal, not a drop-in change.
- **Fingerprintable choices.** A per-user ring size, sampler, fee multiplier
  or non-standard fee; an output count, unlock time or `tx_extra` pattern that
  differs by feature; different behaviour with few outputs. The DEX study
  matched trades from fee and shape alone.
- **Order leaks.** Real output always first or last in a request, an unsorted
  ring, or a default-level log of the real index.
- **Ring reuse lost.** A path that builds a fresh ring for a key image already
  in `ringdb` (a retry after a reorg, multisig, or any path that bypasses
  `get_outs`), or that clears rings without cause.
- **Trusting the daemon more.** Removing a distribution or real-output check,
  or skipping `tx_sanity_check` on a path that builds rings.

FCMP++ code is in `src/fcmp_pp` on master but not active, so rings and the
gamma picker remain the live defence. `trust-boundaries.md` notes FCMP++
removes ring statistics but not fee, shape, `tx_extra` or network leaks.

## 3. Transaction relay: Dandelion++ and anonymity networks

### What leaks origin

- **Being first.** The first node to send a transaction is likely its origin.
  Dandelion++ bounds a spy's recall near its share of nodes (Rucknium 2026);
  Sybil share is the real parameter (section 1).
- **Asymmetric forwarding over Tor and I2P.** ProxyMark's root cause: a node
  sends its own transactions only to outbound anonymity-network peers and
  relays others' over the public network, so a hidden service that receives a
  transaction from an inbound Tor peer knows that peer made it.
- **Eligibility filters an attacker can satisfy.** Stem and noise channels use
  `get_out_connections`: outbound peers claiming a height no more than 2 below
  ours. Hidden-network peers are never block-synced
  (`process_payload_sync_data` marks them `state_normal`), so the height is a
  claim; ProxyMark claimed higher ones to be selected.
- **Distinctive self-advertisement.** ProxyMark identified hidden services by
  their own onion address coming last in timed-sync responses with a live
  `last_seen`. On master `handle_timed_sync` inserts `m_our_address` at a
  random position with `last_seen` 0, once per connection
  (`sent_addresses`).
- **Message timing as a covert channel.** ProxyMark watermarked circuits by
  varying how often it sent timed-sync and other requests. The handlers do not
  limit that rate. The authors propose fixed rates and no timed sync before
  the handshake.
- **Stem transactions seen where they should not be**: in a public pool
  listing, a ZMQ feed or a block template.
- **Blackholing.** A stem node that drops a transaction stalls it. On Beam,
  where stem nodes aggregate, 10% malicious nodes kept over 45% of
  transactions out of blocks (Tabatabaee et al. 2021). Monero's defence is
  the embargo timer.

### What code guards it

`src/cryptonote_protocol/levin_notify.cpp`, `src/net/dandelionpp.h`,
`src/cryptonote_core/tx_pool.cpp`, `node_server::send_txs` in `net_node.inl`,
`handle_notify_new_transactions` in `cryptonote_protocol_handler.inl`.

- **Epochs and stems.** `start_epoch` fluffs with probability
  `CRYPTONOTE_DANDELIONPP_FLUFF_PROBABILITY` for an epoch of
  `CRYPTONOTE_DANDELIONPP_MIN_EPOCH` plus random
  `CRYPTONOTE_DANDELIONPP_EPOCH_RANGE`. `net::dandelionpp::connection_map`
  maps each source to one of `CRYPTONOTE_DANDELIONPP_STEMS` outbound peers.
- **Local transactions always stem.** `dandelionpp_notify` stems when the zone
  is not fluffing or `tx_relay == relay_method::local`. RPC submissions enter
  as `local` (`on_send_raw_tx`), or `none` with `do_not_relay`.
- **Embargo.** A stem transaction gets a Poisson timer averaging
  `CRYPTONOTE_DANDELIONPP_EMBARGO_AVERAGE` (derived in a `tx_pool.cpp`
  comment); `tx_memory_pool::get_relayable_transactions` fluffs it if the
  network has not.
- **Fluff timing and order.** `fluff_notify` queues per connection with
  Poisson delays (`fluff_average_in`, half that outbound). `fluff_flush` sorts
  and de-duplicates each batch ("don't leak receive order").
  `--pad-transactions` pads `make_tx_message` to 1,024-byte granularity.
- **Inbound handling.** Public-zone arrivals are treated as stem. Tor and I2P
  arrivals are `forward`, delayed by `CRYPTONOTE_FORWARD_DELAY_AVERAGE`,
  unless the sender set `dandelionpp_fluff`. A duplicate transaction in one
  notification drops the peer.
- **Zone routing.** `node_server::send_txs` sends anything received from a
  peer over the public zone. Local transactions go to an anonymity zone when
  `--tx-proxy` is set.
- **Noise.** With noise on, `send_noise` sends fixed `CRYPTONOTE_NOISE_BYTES`
  packets every `CRYPTONOTE_NOISE_MIN_DELAY` plus up to
  `CRYPTONOTE_NOISE_DELAY_RANGE` seconds on `CRYPTONOTE_NOISE_CHANNELS`
  outbound links; real transactions are fragmented into those slots. Stem is
  downgraded to `local` there; a `fluff_flush` comment says I2P and Tor stand
  in for Dandelion++'s Sybil protection.
- **Visibility gates.** `matches_category(..., relay_category::legacy)` keeps
  stem transactions out of ZMQ (`core::notify_txpool_event`,
  `core::on_transactions_relayed`). RPC pool queries use
  `allow_sensitive = !request_has_rpc_origin || !restricted`, and
  `on_getblocktemplate` passes `include_sensitive` only when unrestricted;
  `get_block_template_backlog` and `get_txpool_backlog` default to broadcast
  transactions.
- **No disconnect on relayed offences.** `tx_memory_pool::add_tx` sets
  `m_no_drop_offense` for double spends, low fees, oversize extra and nonzero
  unlock time, so `handle_notify_new_transactions` keeps the connection,
  closing Shi et al.'s connection reset. The authors note double spends then
  map topology; the trade-off was accepted.
- **Cross-zone separation.** `is_filtered_command` allows only handshake,
  timed sync and `NOTIFY_NEW_TRANSACTIONS` off the public zone.
  `handle_handshake` checks for self-connection only on the public zone, so a
  clearnet peer cannot test a Tor peer id. `get_local_node_data` advertises
  `my_port` and `rpc_port` only where the zone can ping back.

### What a PR could break

- A path that relays a `local` or `stem` transaction with the fluff flag, to
  more than one peer, or to an inbound peer during stem.
- A change to the source-to-stem mapping, epoch length, fluff probability or
  embargo. Each is a protocol parameter; ask for the analysis.
- Removing the receive-order sort, padding or Poisson draws, or swapping them
  for fixed delays.
- Anything that lets stem transactions out: a new RPC, ZMQ topic,
  default-level log, or miner-data field without the sensitive gate. (P2Pool
  relies on `get_miner_data` and the ZMQ `json-full-miner_data`,
  `json-full-chain_main` and `json-minimal-txpool_add` topics, with miner data
  for N+1 before chain data for N.)
- New commands on anonymity zones, block sync over Tor or I2P, or anything
  that makes a hidden service and a client behave differently on the wire.
- Trusting unverified heights from hidden-network peers more.
- Reintroducing disconnects for conditions a third party can trigger in
  relayed content: the connection-reset primitive again.

A relay change can be measured with Rucknium's `monerosim` method (many
networks, first-spy recall, cluster-robust intervals): recall above the spy
share is a regression. `tests/unit_tests/levin.cpp` covers each relay method
for public and private zones.

## 4. P2P topology and eclipse resistance

### How master selects and keeps peers

- **Counts.** `P2P_DEFAULT_CONNECTIONS_COUNT` (12) outbound; some papers
  report 8, an older default. `--in-peers` defaults to unlimited, which Shi
  et al. call protective since Monero has no inbound eviction.
  `--max-connections-per-ip` defaults to 1, IPv6 grouped by /64
  (`has_too_many_connections`, `is_same_p2p_connection_limit_host`).
- **Lists** (`peerlist_manager`, `net_peerlist.h`): white, one entry per host
  (`evict_host_from_peerlist`); gray, keyed by address and port; anchor,
  outbound peers by `first_seen`.
- **Filling.** `connections_maker` tries anchors, then white until
  `P2P_DEFAULT_WHITELIST_CONNECTIONS_PERCENT` of slots (all while a pruning
  stripe is needed), then gray; seeds (`get_ip_seed_nodes`,
  `get_dns_seed_nodes`) when white is empty or nothing connects.
- **Candidate filtering.** `make_new_connection_from_peerlist` keeps one entry
  per host, shuffles, keeps one per IPv4 /24 or IPv6 /32, and skips subnets
  already connected; if nothing remains it retries without the subnet filter.
- **Churn.** `update_sync_search` runs every 101 s. When outbound slots are
  full and fewer than `P2P_DEFAULT_SYNC_SEARCH_CONNECTIONS_COUNT` peers are
  syncing, it drops one synced non-anchor outbound peer, in every zone.
- **Promotion.** `gray_peerlist_housekeeping` tests one random gray entry a
  minute. An inbound peer that advertises `my_port` and answers a ping-back
  (`try_ping` in `handle_handshake`) enters the white list.
- **Sharing.** `get_peerlist_head` with `anonymize` shuffles the whole white
  list, keeps `P2P_DEFAULT_PEERS_IN_HANDSHAKE`, and zeroes `last_seen`;
  `sent_addresses` stops repeats on a connection.
- **Receiving.** `handle_remote_peerlist` rejects more than
  `P2P_MAX_PEERS_IN_HANDSHAKE` as spam and entries from another zone.
  `sanitize_peerlist` drops loopback, local, zero-IP and port-equals-RPC-port
  entries and zeroes `last_seen`; `merge_peerlist` adds the rest to gray. This
  runs for timed-sync responses from inbound peers too.
- **Bans.** `add_host_fail` blocks after `P2P_IP_FAILS_BEFORE_BLOCK` failures
  for `P2P_IP_BLOCKTIME`; also `block_host`, `block_subnet`, `--ban-list`,
  `--enable-dns-blocklist` and unrestricted `set_bans`. After a 2026 DNS
  ban-list update, Rucknium reported about half of honest nodes running it.

### What the research shows still works

- **White-list filling through inbound handshakes**, one IP per entry (Shi et
  al. 2025). Their fixes (no white-list entry from inbound peers, a larger
  white list) are not on master.
- **Gray-list flooding through inbound timed-sync responses**: 20 connections
  times 250 entries fill 5,000 slots (both Shi papers).
- **Port diversity.** One IP under many ports gives many gray entries (Nyx);
  the authors propose de-duplicating the gray list by IP.
- **Autonomous churn.** `update_sync_search` replaces benign outbound peers
  without any reset. Nyx peers advertise the genesis block as their top, so
  `have_block(top_id)` keeps them `state_normal`, eligible and never
  "syncing".
- **Bootstrap.** A newborn node's first gray list is the seeds' answer
  (Moros).
- **The /24 filter** raises cost by a constant factor (Shi et al. 2026). The
  anchor list offers nothing during a reset, because dropped outbound peers
  leave it (Shi et al. 2025, appendix B).
- **Concentration.** Gao et al.: 14 top-degree nodes adjacent to 3,153 of
  4,837 nodes (82.1%). Kirschner: 86% of nodes in 14% of node-hosting ASes,
  about 55% in about 12% of BGP prefixes, a routing-attack risk. Kopyciok et
  al.: ban-listed peers promoted in most peer lists, suggesting most nodes do
  not use the list.

### What a PR could weaken

- Fewer outbound slots, a lower white-list share, fewer anchors, or anchors
  lost on restart.
- Weaker per-host or per-subnet de-duplication, or de-duplication after
  `last_seen` ordering instead of after a shuffle.
- Trusting a remote `last_seen`; sharing ordered, timestamped or repeated
  lists; dropping `sent_addresses`.
- Loosening the `P2P_MAX_PEERS_IN_HANDSHAKE` cap or skipping
  `sanitize_peerlist`.
- Inbound eviction, or a default inbound cap without it (Shi et al. found
  unlimited inbound protective).
- Drop or ban triggers on relayed content or cheaply induced states: reset
  primitives, and lasting bans let an attacker get honest peers banned.
- More aggressive `update_sync_search`, or a looser "synced" test.
- Fewer seeds, more trust in unsigned DNS answers, or seeds consulted when
  the node already has peers.

The header-only sync proposal (SChernykh, 2026) is not on master. Its codec
checks bytes, not semantics, so an eclipsing peer still chooses the chain a
node sees, within proof of work.

## 5. Wallet-to-daemon leaks

Observer: the remote node operator (integrity is `trust-boundaries.md`
section 4). If it is also a spy, the wallet's IP is the origin whatever
Dandelion++ does; Shi et al. (2025) note eclipsing a public RPC node exposes
every wallet behind it.

What the daemon learns, and from which call:

- **IP and timing**, unless the wallet uses its `--proxy` option.
- **The submitted transaction**, via `sendrawtransaction`. `do_not_relay`
  keeps it in that node's pool; Shi et al. used that to put a transaction on
  one node only.
- **The candidate set behind each ring**, via `get_outs.bin`. The node cannot
  tell which is real (section 2), but can recognise the resulting rings on
  chain and tie a transaction relayed elsewhere to the requesting IP.
- **Key images.** `wallet2::rescan_spent` and `import_key_images` with
  `check_spent` send them to `/is_key_image_spent`; `simple_wallet::rescan_spent`,
  `wallet_rpc_server::on_rescan_spent` and `on_import_key_images` refuse
  without a trusted daemon. `check_reserve_proof` sends the prover's, not the
  verifier's.
- **Specific transaction ids.** jeffro256's `find_and_save_rings` post-mortem
  (2025; HIGH with untrusted daemons, MEDIUM otherwise): wallets v0.12.0.0 to
  v0.18.4.1, reloaded after a restore, sent outgoing transaction ids to
  `/gettransactions` without a trust check, letting the operator link the
  wallet to receivers and build probabilistic transaction graphs. On master
  the function is deprecated and `m_ring_history_saved` defaults to true.
- **Decoy inputs.** `get_rct_distribution` and `get_output_distribution` come
  from the daemon. Integrity is section 2's checks; the privacy risk is a
  skewed distribution that makes this wallet's rings distinctive.
- **Fees.** `adjust_priority` and `get_base_fee` use the daemon's fee estimate
  and backlog; lies can give this wallet a fee nobody else pays.
- **Public nodes.** `get_public_nodes` returns RPC nodes the daemon learned
  from peers; a Sybil-heavy list sends wallets to spy nodes.

Rules for review:

- Any request whose content depends on what the wallet owns must be gated on
  `is_trusted_daemon()`, or hidden in a request that does not depend on
  ownership. Refresh fetches every block; pool scanning must also fetch
  uniformly.
- A call that runs automatically (load, refresh, background sync) leaks more
  than one the user types.
- A new wallet RPC or API path to an existing trusted-only operation needs the
  same check; `wallet_rpc_server.cpp` and `simplewallet.cpp` check
  `is_trusted_daemon()` separately.
- Decoy-related responses must stay checked as in section 2.

## 6. Recipient and address privacy

- **Subaddresses** (MRL-0006, 2017) are unlinkable to each other and to the
  main address for anyone without the private view key. A view-key holder who
  learns one subaddress and its index recovers the main public spend key and
  can derive other likely subaddresses, so view access cannot be limited to
  some subaddresses. A sender proving payment to a subaddress must reveal it.
- **Janus.** A sender who knows two of a recipient's addresses can test
  whether they share a wallet. MRL (2019–2020) noted wallets can mitigate it;
  Carrot is designed to prevent it (MRL, 2024).
- **View-only wallets and the burning bug.** kayabaNerve's Guaranteed
  Addresses (superseded by Featured Addresses, which carry feature flags)
  note that a view-only wallet cannot see spends and so over-credits burnt
  duplicate outputs, while importing key images to fix that may break the
  user's privacy model. The gist also raises that a distinctive address type
  can reveal which wallet an organisation receives with.
- **Third parties holding view keys.** Cinal et al. note that exchanges under
  EU rules may request view keys or OutProofs, revealing incoming history to
  that party.

What a PR could weaken: anything that lets a sender, recipient or view-key
holder learn more than the protocol says (another subaddress, the main
address, outgoing activity); a proof that discloses more than needed; a new
address or output format whose use is visible on chain or off chain; wallet
behaviour that differs by address type in a way visible on chain.

## 7. Checklist: the observer verifier angle

Fill one row per candidate privacy finding; one that cannot fill the third
column has not shown a leak.

| Observer | Position | Learns from this change | Did research show it already had it? |
| --- | --- | --- | --- |
| Passive spy peer | Ordinary peer | ? | First-spy recall about equal to spy share (Rucknium); about 15% of peers non-standard (Kopyciok) |
| Topology learner | Harvests peer lists | ? | Neighbours inferable without timestamps (Gao); handshake flooding observed (Kopyciok) |
| Eclipse attacker | About 1,000 IPs in distinct subnets | ? | Full eclipse of reachable (Shi 2025) and unreachable nodes (Shi 2026) |
| Tor/I2P adversary | Hidden services plus guard relays | ? | Origin and IP of Tor nodes' transactions, given a malicious guard (ProxyMark) |
| Network observer | ISP, on path | ? | Noise and padding target this observer; size and timing otherwise visible |
| Remote node | Answers the wallet | ? | IP, submitted transaction, ring candidate sets, key images on trusted-only paths |
| Restricted-RPC client | Public RPC | ? | Only broadcast transactions; peer and connection RPCs are unrestricted-only |
| Chain analyst | Reads the chain forever | ? | Near-random ring guessing post-RingCT (ACK-J, MWM), but 23.5% from age mismatch (OSPEAD); fee, shape and timing fingerprints (ART, DEX study) |
| Output flooder | Owns many outputs | ? | Effective ring size about 5.5 of 16 during the 2024 spam (Rucknium); chain reactions (MRL-0001) |
| Recipient or view-key holder | Paid by, or audits, the user | ? | All subaddresses of a wallet whose view key it holds (MRL-0006) |
| Miner or pool | Builds blocks | ? | Pools identifiable by coinbase extra nonce (Lee and Kim) |

Then answer, in order:

1. **Name the observer**, from the table or `trust-boundaries.md`.
2. **State what it learns** that it could not on master, and the symbol that
   releases it.
3. **Check whether it already had it**, using the last column and the list
   below. Already leaked to the same observer is not new, unless the change
   reaches more users or makes the leak permanent.
4. **Decide whether it is protocol-level**: does the protocol itself reveal it
   (transaction format, rings, key images, outputs, addresses, Dandelion++
   origin hiding) for users who follow it? Then HIGH at least, from any
   position; otherwise use `trust-boundaries.md`.
5. **Ask whether it is written on chain.** That cannot be fixed later.

Already true on master, so not new findings by themselves:

- A spy with share p of nodes guesses origins at about rate p.
- Neighbours are inferable from peer-list frequency over days.
- Double spends no longer disconnect, so they can probe topology.
- Inbound peers can enter the white list; their timed-sync responses feed
  the gray list.
- Hidden-network peers' heights are unverified claims.
- Message rates (timed sync, ping, support flags) are not limited.
- The decoy distribution diverges from real spend ages (OSPEAD).

Each becomes a finding again if a change makes it materially worse: higher
recall, less effort, more users, or a leak moved onto the chain.

## Sources

- Amrit Kumar et al. "A Traceability
  Analysis of Monero's Blockchain." ESORICS 2017.
- ACK-J. "Lord of the Rings: An Empirical Analysis of Monero's Ring Signature
  Resilience to Artificially Intelligent Attacks." Final report, 2022.
- Xingyu Yang, Lei Xu, Liehuang Zhu. "De-anonymizing Monero: A Maximum
  Weighted Matching-Based Approach." Undated preprint, about 2025.
- Andrea Venturi et al. "ART: A Graph-based Framework for Investigating Illicit Activity in Monero via
  Address-Ring-Transaction Structures." 2025.
- Adrian Cinal et al. "Anamorphic Monero Transactions: the Threat of Bypassing Anti-Money
  Laundering Laws." ESORICS 2025, revised 2026.
- Surae Noether, Sarang Noether, Adam Mackenzie. "A Note on Chain Reactions in
  Traceability in CryptoNote 2.0." MRL-0001, 2014.
- Adam Mackenzie, Surae Noether, Monero Core Team. "Improving Obfuscation in
  the CryptoNote Protocol." MRL-0004, 2015.
- Sarang Noether, Brandon Goodell. "An Efficient Implementation of Monero
  Subaddresses." MRL-0006, 2017.
- Sarang Noether. "Sets of Spent Outputs." MRL-0007, 2018.
- Monero Research Lab meeting logs, 2017–2026 (decisions on ring size, two
  outputs, timelocks, fees, OSPEAD, black marbles, spy-node ban list and
  subnet de-duplication).
- Ruisheng Shi et al. "Eclipse Attacks on Monero's Peer-to-Peer Network." NDSS 2025.
- Yu Gao et al. "Charting the Uncharted: The Landscape of Monero Peer-to-Peer Network." 2025.
- Yu Gao et al. "Monero Peer-to-peer Network Topology Analysis." 2025.
- Yannik Kopyciok, Stefan Schmid, Friedhelm Victor. "Friend or Foe?
  Identifying Anomalous Peers in Monero's P2P Network." 2025.
- Justin Kirschner. "An Analysis of Monero's Network Topology." DAPPS 2026.
- Ruisheng Shi et al. "Deanonymizing Monero Transactions in Tor Network (ProxyMark)." 2026.
- Rucknium. "`monerosim` Spy Node Analysis." 2026.
- Ruisheng Shi et al. "Are Unreachable Nodes Truly Safe? Fully
  Eclipsing Monero's P2P Network!" ACM CCS 2026.
- SChernykh. "Header-only Synchronization Wire Format ('Header Codec') for
  Monero." Specification, 2026.
- jeffro256. "Post-Mortem of 10-Block-Old Decoy Selection Bug." 2023.
- jeffro256. "Post-Mortem of find_and_save_rings() Bug." getmonero.org, 2025.
- kayabaNerve. "Guaranteed Addresses" (2022, deprecated) and "Featured
  Addresses" (2022–2024). Gists.
- Suhyeon Lee, Hyeongyeong Kim. "Inside Qubic's Selfish Mining Campaign on
  Monero: Evidence, Tactics, and Limits." 2025.
- SChernykh. "Monero P2Pool — Architecture Reference." v4.18, 2026.
- Yannik Kopyciok, Friedhelm Victor, Stefan Schmid. "Monero's Decentralized
  P2P Exchanges: Functionality, Adoption, and Privacy Risks." 2025.
- Seyed Ali Tabatabaee et al. "One Bad Apple Spoils the Bunch: Transaction DoS in MimbleWimble Blockchains." 2021.
