# Refutation patterns

Candidate findings in this codebase die for a small number of recurring
reasons. Check the relevant ones before reporting anything — each has produced
false positives in past review work.

State in the report which of these you checked. "I confirmed the serializer
does not cap this" is evidence; silence is not.

## The serializer already bounds it

Monero's serialization layer imposes limits before application code ever sees
a value, so an "attacker-controlled count drives a huge allocation" finding is
often unreachable in practice.

Before reporting one, read the actual serializer for the type — in
`src/serialization/` and `contrib/epee/include/serialization/` — and find the
constraint on the field. Look for `FIELD`/`VARINT_FIELD` macros with explicit
checks, `*_MAX`/`*_LIMIT` constants, and any `if (n > ...) return false` in the
read path.

This is the most common way a genuine memory-safety *primitive* turns out to
have no reachable path. The primitive being real is not the finding; reaching
it is.

## Proof-dimension bugs in RingCT and Bulletproofs+

Indexing and buffer-sizing bugs in `src/ringct/` verification are frequently
fenced off because the proof's dimensions are checked before the arithmetic
that would overflow. For Bulletproofs+ the checks are split across three
places: the serializer (`BulletproofPlus` in `src/ringct/rctTypes.h`: `L`
non-empty, `L.size() == R.size()`); `expand_transaction_1` in
`src/cryptonote_basic/cryptonote_format_utils.cpp`, which requires exactly one
proof with `L.size() >= 6` and enough capacity for `vout.size()`, then rebuilds
`V` from `outPk` (`V` is not serialized); and the verifier's first pass
(`bulletproof_plus_VERIFY` in `src/ringct/bulletproofs_plus.cc`:
`V.size() <= maxM`, `L.size() == 6+logM`, `max_length < 32`) before it sizes
`maxMN`. Trace the dimension field from the wire to the arithmetic and identify
every check on the way, in all three. If the only way to reach the bug is a proof shape one
of them rejects, it is at most a hardening note.

FCMP++ proofs have no transaction type on master (`RCTType*` in
`src/ringct/rctTypes.h` ends at `RCTTypeBulletproofPlus`); the staged code in
`src/fcmp_pp` has no wire format yet to bound its inputs, so this refutation
does not apply to it.

## The config option defaults to off

Non-default is not the same as rare. Apply Modifier 4 under Severity in
`trust-boundaries.md`: the option lowers the rating only if few people run it.
Options common in real deployments do not lower it: `--restricted-rpc` and
`--rpc-restricted-bind-port` (public remote nodes), `--public-node`,
`--tx-proxy`, `--anonymous-inbound`, `monero-wallet-rpc` itself, and
`--zmq-pub` (P2Pool miners enable it; the ZMQ RPC server is on by default
unless `--no-zmq`). Options that are rare or dangerous by name do lower it:
`--dangerous-unverified-import` in `monero-blockchain-import`,
`--disable-rpc-login` on a non-loopback wallet-rpc, a debug build.

Find the default — in the option's declaration, not in documentation — and
state it, along with who runs the non-default value. Wallet and daemon both
have options that sound enabled but are not.

## The RPC handler is restricted

The daemon RPC distinguishes restricted (public) from unrestricted
(full-admin) clients. Gating happens in two places: the `!m_restricted`
conditions on `MAP_URI_AUTO_JON2_IF` / `MAP_JON_RPC_WE_IF` entries in
`src/rpc/core_rpc_server.h`, which hide a method entirely, and `m_restricted`
checks inside handlers in `src/rpc/core_rpc_server.cpp`, which cap or strip
results. A handler reachable only by an unrestricted client is generally not a
finding, because that client can already do far worse by design. Confirm the
handler's actual gating in both places before claiming remote reach — do not
assume from the method name.

**This refutation does not cover who can reach the unrestricted port.** It
answers one question only: given a client already speaking to the admin
interface deliberately, is this handler extra power. It says nothing about a
request the operator never made.

The daemon is unrestricted BY DEFAULT (`core_rpc_server::arg_restricted_rpc`
defaults to `false`; the main port binds loopback with no login unless
configured). So a page in a browser, or any other process on the machine,
issuing a cross-site or otherwise unattended request to `127.0.0.1:18081` is
not "a client that can already do far worse" — it is an attacker who was
never given the admin interface and took it. Reach of that shape is a finding,
and the severity table's `Unrestricted-RPC-only` row does not apply to it.

The concrete shape: `MAP_URI_AUTO_JON2_IF` in
`contrib/epee/include/net/http_server_handlers_map2.h` does not check the HTTP
method, and `epee::serialization::json::load_from_json`
(`contrib/epee/include/storages/portable_storage_from_json.h`) accepts an
empty or whitespace-only body as an empty object. A body-less cross-site `GET`
to `/stop_daemon` therefore reaches `on_stop_daemon` on a default daemon; the
`Origin` header only decides the CORS response headers
(`contrib/epee/include/net/http_protocol_handler.inl`), not whether the
handler runs. A
verifier citing this section against that shape of candidate has cited the
wrong section.

So before refuting on this basis, say which of the two it is: an operator who
opened the admin interface on purpose, or a request that arrived without one.

## No Monero client sends an empty request body

An empty HTTP request body never comes from Monero's own clients. epee's
client helpers serialise the request struct before sending:
`invoke_http_json` (`contrib/epee/include/storages/http_abstract_invoke.h`)
calls `store_t_to_json`, so the body is at least `{}`, and passes it to
`transport.invoke`; `invoke_http_json_rpc` wraps it, and `invoke_http_bin`
sends `store_t_to_binary` output. The wallet's daemon calls all go through
these.

So a change to how the daemon treats an empty body affects third-party tooling
only, not wallet-to-daemon traffic. Say which population a finding of that
shape reaches before assigning severity.

This narrows the *legitimate-client* population only. It does not refute an
attacker sending an empty body: `json::load_from_json` accepts one as `{}`
(see the previous section), so body-less requests, including cross-site
`GET`s, reach JSON URI handlers.

## Boost already throws

`boost::regex` has a complexity limit and throws when a match exceeds it, and
the exposed callers catch: the epee HTTP server's regexes
(`http_protocol_handler.inl`) run under `handle_recv`, which
`abstract_tcp_server2.inl` wraps in `CATCH_ENTRY_SWALLOW_EX`, and the one
caller-supplied pattern, `req.tag` with `req.regexp` in
`wallet_rpc_server::on_get_accounts`, is compiled and matched inside the
handler's `try`. Catastrophic-backtracking findings against `boost::regex` are
refuted by default: to report one you must show both that the limit does not
trigger and that the throw is not caught. List the users with
`grep -rln 'boost::regex' src contrib/epee` and re-check any new one.

Similar shape for `boost::asio` timeouts and Boost container bounds — check for
the library-level guard before assuming application code is the only defence.

## An existing assertion covers it

Look for `CHECK_AND_ASSERT_MES`, `CHECK_AND_ASSERT_THROW_MES`,
`THROW_WALLET_EXCEPTION_IF`, and plain `if (...) return false` in the call
chain. A macro two frames up often makes the local-looking bug unreachable.
Note that they differ in kind: `CHECK_AND_ASSERT_MES` logs and returns, the
`THROW` forms throw, and a plain `assert` compiles out of release builds
(`-DNDEBUG` in `CMakeLists.txt`) — if your refutation depends on an assertion,
say which kind it is.

## The caller already validated it

C++ makes this easy to miss: the dangerous function is a private helper with
one or two callers that both check the precondition. Use the symbol index
(`cscope -d -L3 <fn>`) to enumerate callers rather than assuming, then read each
one. A helper with no external caller is not remotely reachable.

## The type is wide enough

Before claiming integer overflow, check the actual types involved, including
any promotion. `size_t` on 64-bit does not overflow at values an attacker can
realistically supply through a size-limited message. On a 32-bit target it
may: `size_t`, `long` and pointer arithmetic are 32 bits there.

So the refutation must say whether a 32-bit target ships and check the
arithmetic there. On master the Guix release hosts (`HOSTS` in
`contrib/guix/guix-build`) are all 64-bit, but CI
(`.github/workflows/depends.yml`) still builds i686 Linux and ARMv7 Android,
and `contrib/depends` builds 32-bit hosts for anyone compiling their own.
Re-check those lists on the head you are reviewing.

## The race is actually serialized

Before reporting concurrent access, establish that two threads genuinely reach
the state at once. A great many candidates turn out to be sequenced by an
existing lock or by the refresh cycle. This matters beyond a yes/no: if an
operation is serialized, an attacker-influenced write to it is *deterministic*
rather than racy, which is a different (often stronger, sometimes weaker) claim
than the one the first pass made. Name the lock, or name the two call sites that
run concurrently.

## The divergent path does not ship

For code with multiple implementations of the same computation — interpreter
versus JIT, with and without hardware acceleration, per architecture — a
difference between paths is only a consensus break if both paths run on real
nodes. Establish which are built and used in production before assigning
severity. A divergence on an architecture or build option nobody ships is a LOW.

## The construction already constrains it

In proof systems, an operation that looks wrong in isolation is often
constrained by the surrounding protocol. Divisor arithmetic modulo the field
prime, and point-versus-negation handling, have both repeatedly looked like
breaks and turned out to be fine once the protocol's own constraints were taken
into account. Read the construction, not just the function.

## Not refutations: "nobody reaches it" and "it is not live yet"

Neither kills a candidate. If the defect is real and nothing guards it, but no
attacker path exists today (no production caller, only trusted configuration
feeds it), it holds at LOW. Staged FCMP++ code, and anything only a future hard
fork switches on, is rated on the path it will have once live. "Not
consensus-reachable today" tells a maintainer when the bug starts to matter. It
does not make the bug go away. See the finding standard in
`.claude/skills/monero-deep-review/specs/finding-spec.md`.

FCMP++ is not scheduled on master: there is no FCMP++ `HF_VERSION_*`, no
`RCTType` for it, and `git grep -n fcmp_pp -- src ':!src/fcmp_pp'` finds only
two CMake lines. Pull requests in the review queue add the callers and the
fork gating. Judge the staged code as if it were activated (Modifier 5 under
Severity in `trust-boundaries.md`).

**No caller is not a dead end.** "No caller" in these references describes
master; the head you are reviewing may differ. Grep the head first: a pull
request that adds a caller is the case to trace. Callers outside the diff are
in scope, so never leave one untraced because it is outside this pull request.
Where no caller exists on the head, treat every argument as
attacker-controlled unless the function's contract or the FCMP++ design
constrains it, and cite what does. How a future caller will use the code
is not a gap to report. It is the analysis to do.

## `CarrotOutputPairV1` skips torsion clearing by contract

`fcmp_pp::curve_trees::output_to_tuple` does not clear torsion for a
`CarrotOutputPairV1`, which looks like a small-order point reaching
`point_to_ed_derivatives`. That is the type's contract: the comment above
`struct CarrotOutputPairV1` in `src/fcmp_pp/fcmp_pp_types.h` ("No torsion")
makes torsion-freeness a precondition on whoever constructs one, and
`output_checked_for_torsion` in `src/fcmp_pp/fcmp_pp_types.cpp` returns true
for it. The only checks left in `output_to_tuple` do not cover the case: the
torsion re-check is a plain `assert` under `!defined(NDEBUG)` (see "An existing
assertion covers it"), and the release-build check rejects only the identity.

Nothing in the tree constructs a `CarrotOutputPairV1` -- check with
`git grep -n CarrotOutputPairV1` -- so no untrusted point reaches the skip
today. Two limits:

- **It expires when a constructor appears.** Code that wraps outputs in a
  `CarrotOutputPairV1` must first check BOTH the output pubkey and the
  commitment for torsion. A pull request adding one without both checks is a
  finding; retarget the candidate at that code and re-run the grep on the head
  you are reviewing.
- **Per "Not refutations" above, rate on the live path.** Once outputs flow
  into this type, an unchecked point is rated as the consensus or wallet
  defect it becomes, not as staged code.

## It is test-only code

Changes under `tests/` do not ship. They matter if they also modify non-test
code, or if they remove a guard:

- A pull request that deletes or weakens a test guarding a consensus rule or a
  past bug (`tests/core_tests`, unit tests that encode consensus behaviour, a
  regression test) is not dismissed as test-only. It removes the guard on that
  rule, and the next change that breaks the rule passes CI. Say which rule
  loses its test.
- Weakening a fuzz harness (`tests/fuzz`) is a coverage loss to note, worth a
  LOW note, not a vulnerability report.

## A wrong return value the API tells the caller not to trust

A function that returns the wrong boolean is a bug. It is a SECURITY finding
only if something acts on the boolean and does damage. Three questions settle
it, and all three have to go your way:

1. **Does any state change behind the wrong answer?** No funds moved, no file
   written, no key touched means the caller was misinformed and nothing else
   happened. A wrong answer with no act behind it is a correctness bug.
2. **Does the API document a second check the caller is required to make?**
   The wallet API in `src/wallet/api/wallet2_api.h` pairs many calls with
   `status()` and `errorString()`, and says so in the header. A caller that
   skips a documented check is a caller with a bug, and you are then reporting
   somebody else's hypothetical code rather than this tree.
3. **Is there an in-tree caller that actually gets hurt?** Find it. "An
   external consumer might" is not a path, and neither is a shape a user
   reaches by mistyping an address, because there is no attacker in it.

MEASURED: `PendingTransactionImpl::commit` was proposed as reporting
success after broadcasting nothing. It died on all three questions at once:
nothing is broadcast so no state moves, the header documents the `status()`
check that catches it (in `src/wallet/api/wallet2_api.h` the doc comments on
`createTransactionMultDest`, `createTransaction` and
`createSweepUnmixableTransaction` all say "caller is responsible to check
PendingTransaction::status()"), and the only in-tree caller,
`WalletImpl::submitTransaction` in `src/wallet/api/wallet.cpp`, builds its own pending transaction through
`load_tx` and never holds an errored empty object.

The mechanism on master: in `src/wallet/api/pending_transaction.cpp` the only
`m_status = Status_Ok` assignments are in the `PendingTransactionImpl`
constructor and the save-to-file success branch of `commit`. The broadcast
branch of `commit` sets `m_status` only from its `catch` blocks, so an empty
`m_pending_tx` returns `true` off the constructor's optimistic initial value.
Re-read the function on the head you are reviewing before citing it.

Where it dies here it is usually still worth telling a maintainer, because the
author did not mean to write it. That is what `## Needs human review` is for:
no severity, no vote, and the input that tells the two versions apart. Refuting
a security claim is not the same as deciding the code is fine.

## Nothing in the tree calls it, so the operator has to

A defect in a public-API method that no in-tree code reaches is not a defect an
attacker reaches either. Somebody has to call it, and the only somebodies are
the wallet's own operator driving an embedding application -- the GUI, Feather,
a mobile wallet -- none of which are in this repository. A hostile daemon can
widen the window once the call is in flight; it cannot start the call.

So say who has to act. "The operator must invoke this" is a real narrowing and
belongs in **Needs:**; it is usually the difference between a MEDIUM and a LOW,
and occasionally between a finding and a note.

MEASURED: a race was proposed in `WalletImpl::scanTransactions`,
which calls `scan_tx` outside the refresh lock so that `detach_blockchain` can
erase `m_transfers` while the refresh thread holds a reference into it. The
mechanism holds. The reach does not: `grep -rn scanTransactions src tests
utils` on master returns four lines and every one is a declaration or the
definition -- the definition in `src/wallet/api/wallet.cpp`, the override in
`src/wallet/api/wallet.h`, and the pure virtual with its doc comment in
`src/wallet/api/wallet2_api.h`. No caller exists.

Two limits, and both matter:

- **`wallet2_api.h` is a PUBLIC header.** External wallets do call these
  methods, so this refutes attacker-reachability, never "the code is fine". A
  crash an operator can trigger in the GUI is still worth telling a maintainer
  about, under `## Needs human review` or as a LOW.
- **This one goes stale the moment somebody adds a caller**, which is exactly
  the kind of thing a pull request does. Re-run the grep on the head you are
  reviewing. Do not cite this entry as though it were a standing fact; a
  refutation that has quietly expired is how a real finding gets suppressed.

## The lying daemon's chain view does not survive the resync

A remote node can feed a wallet a false chain, and findings that rest on the
wallet then holding wrong heights, wrong indices or wrong outputs have to say
what happens next. What happens next is usually `wallet2::detach_blockchain`
(`src/wallet/wallet2.cpp`), reached from `wallet2::handle_reorg` when the
wallet resyncs against an honest daemon. From the fork height upward
it erases the transfers, their key images and public keys, the payments, the
confirmed transactions and the background-sync records, and crops
`m_blockchain`; for transfers it keeps, it resets spent/frozen status
(`set_unspent`, `thaw`) where `m_spent_height` is at or above the fork and
pops `m_uses` entries from it. The false view is not corrected in place; it is
deleted.

So a corruption that lives only in state at or above the fork height is
transient, and the finding needs to say what damage is done before the detach
lands -- a spent key image, a leaked address, funds moved. "The wallet believes
something wrong for a while" is not by itself an impact.

MEASURED: pending multisig rescan state is applied by transfer index,
so a reorg during the rescan was proposed as writing a composite key image
built from another output. The wrong indices only arise from a lying daemon's
chain view, and the resync erases it (`m_transfers.erase` in
`detach_blockchain`).

The index is not entirely unchecked. `wallet2::update_multisig_rescan_info`
calls `get_multisig_composite_key_image(n, new_info)` before changing the
transfer, and `multisig::generate_multisig_composite_key_image`
(`src/multisig/multisig.cpp`) returns false when the distinct component count
(`used.size()`) differs from `combinations_count(N-M+1, N)`; the wallet
wrapper turns that into a `wallet_internal_error`. For M < N that catches a
different output at the index, because local components shared with
importers stop deduplicating. For N-of-N no component is shared, the count
still matches, and a wrong-output key image is installed unchecked -- that
case still rests on the resync above. And a throw inside
`process_new_transaction` (call sites guarded by
`m_multisig_rescan_info.front().size() >= m_transfers.size()`) leaves
`m_multisig_rescan_info` installed, because it is cleared only at the end of
`wallet2::refresh`.

Three limits:

- **Only at or above the fork height.** State the daemon influenced below the
  point the wallet detaches to is untouched, and so is anything already written
  outside `wallet2`'s own containers -- a key image published to the network,
  a file on disk, a txid revealed to the node.
- **It needs the wallet to actually resync against an honest daemon.** A wallet
  that keeps talking to the hostile node never reorgs and never detaches. If
  the finding's damage lands while still connected, this refutation does not
  touch it.
- **`detach_blockchain` is not guaranteed to complete.** It throws
  `wallet_internal_error` on a key image or public key it cannot find
  ("key image not found", "public key not found"), and `handle_reorg` throws before
  calling it at all when the reorg height is below `m_blockchain.offset()`
  (message "Daemon claims reorg below last checkpoint"; the offset is where
  the wallet trimmed its hash chain, via `m_blockchain.trim` in
  `fast_refresh` at a compiled-in checkpoint, `trim_hashchain` or
  `import_blockchain`).
  A state you can drive into one of those throws is a finding about the detach
  itself, not something the detach refutes.

## Every key-image import with `check_spent` needs a trusted daemon

`wallet2::import_key_images` passes raw daemon `res.status` through
`THROW_ON_RPC_RESPONSE_ERROR_GENERIC` rather than `get_rpc_status`, which
looks like untrusted daemon text reaching the user. It is not reachable from
an untrusted daemon: the RPCs run only when `check_spent` is set, and every
entry point either refuses to run unless the daemon is trusted or clears
`check_spent` when it is not:

- `simple_wallet::import_key_images` in `src/simplewallet/simplewallet.cpp`
  (`if (!m_wallet->is_trusted_daemon())`);
- `on_import_key_images` in `src/wallet/wallet_rpc_server.cpp`
  (`if (!m_wallet->is_trusted_daemon())`);
- `WalletImpl::importKeyImages` in `src/wallet/api/wallet.cpp`
  (`if (!trustedDaemon())`);
- `wallet2::cold_key_image_sync` in `src/wallet/wallet2.cpp`, reached from
  simplewallet and `wallet_api`, which runs with any daemon but passes
  `is_trusted_daemon()` as `check_spent`;
- `WalletImpl::createWatchOnly` in `src/wallet/api/wallet.cpp`, which passes
  `check_spent = false`.

`check_spent` defaults to `true` in the declaration in `src/wallet/wallet2.h`,
so a new caller that omits it is the case to look for. And `get_rpc_status`
(`src/rpc/core_rpc_server_commands_defs.h`) returns a trusted daemon's status
unchanged, so routing those sites through it changes nothing. Re-check these
entry points on the head you are reviewing (`grep -rn 'import_key_images'
src/simplewallet src/wallet`); a new one that sets `check_spent` without a
trusted daemon reopens this.

---

None of this means "do not report". It means the report must name the guard you
checked and explain why it does not hold. A finding that survives an honest
attempt at each applicable refutation above is worth a security engineer's
time. One that has not been through this is not.
