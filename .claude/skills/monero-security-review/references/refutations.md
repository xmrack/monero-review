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
fenced off because the proof's dimensions are validated during deserialization,
long before the arithmetic that would overflow. Trace the dimension field from
the wire to the arithmetic and identify every check on the way. If the only
way to reach the bug is a proof shape the deserializer rejects, it is at most a
hardening note.

## The config option defaults to off

A path reachable only when a non-default option is enabled is at most MEDIUM,
and usually LOW. Find the default — in the option's declaration, not in
documentation — and state it. Wallet and daemon both have options that sound
enabled but are not.

## The RPC handler is restricted

`src/rpc/core_rpc_server.cpp` distinguishes restricted (public) from
unrestricted (full-admin) clients. A handler reachable only by an unrestricted
client is generally not a finding, because that client can already do far worse
by design. Confirm the handler's actual gating before claiming remote reach —
do not assume from the method name.

## Boost already throws

`boost::regex` has a complexity limit and throws when a match exceeds it, and
callers in this codebase generally catch. Catastrophic-backtracking findings
against `boost::regex` are refuted by default: to report one you must show both
that the limit does not trigger and that the throw is not caught.

Similar shape for `boost::asio` timeouts and Boost container bounds — check for
the library-level guard before assuming application code is the only defence.

## An existing assertion covers it

Look for `CHECK_AND_ASSERT_MES`, `CHECK_AND_ASSERT_THROW_MES`,
`THROW_WALLET_EXCEPTION_IF`, and plain `if (...) return false` in the call
chain. A macro two frames up often makes the local-looking bug unreachable.
Note that some of these compile out or only log depending on build flags — if
your refutation depends on an assertion, say which kind it is.

## The caller already validated it

C++ makes this easy to miss: the dangerous function is a private helper with
one or two callers that both check the precondition. Use the symbol index
(`cscope -d -L3 <fn>`) to enumerate callers rather than assuming, then read each
one. A helper with no external caller is not remotely reachable.

## The type is wide enough

Before claiming integer overflow, check the actual types involved, including
any promotion. `size_t` on 64-bit does not overflow at values an attacker can
realistically supply through a size-limited message.

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

## It is test-only code

Changes under `tests/` do not ship. They matter only if they also modify
non-test code, or if they weaken a fuzz harness in a way that would hide future
bugs — the latter is worth a LOW note, not a vulnerability report.

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

MEASURED, on 11185: `PendingTransactionImpl::commit` was proposed as reporting
success after broadcasting nothing. The new `m_status = Status_Ok` at
`src/wallet/api/pending_transaction.cpp:162` genuinely does overwrite a prior
`Status_Error` on an empty `m_pending_tx`. It died on all three questions at
once: nothing is broadcast so no state moves, `src/wallet/api/wallet2_api.h:858`
documents the `status()` check that catches it, and the only in-tree caller,
`WalletImpl::submitTransaction` at `src/wallet/api/wallet.cpp:1289`, builds its
own pending transaction through `load_tx` and never holds an errored empty
object.

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

MEASURED, on 11185: a race was proposed in `WalletImpl::scanTransactions`,
which calls `scan_tx` outside the refresh lock so that `detach_blockchain` can
erase `m_transfers` while the refresh thread holds a reference into it. The
mechanism holds. The reach does not: `grep -rn scanTransactions src tests
utils` on master returns four lines and every one is a declaration or the
definition -- `src/wallet/api/wallet.cpp:1293`, `src/wallet/api/wallet.h:176`,
and the pure virtual with its doc comment at
`src/wallet/api/wallet2_api.h:957` and `:961`. No caller exists.

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
(`src/wallet/wallet2.cpp:4371`), reached from `wallet2::handle_reorg` (`:4470`)
when the wallet resyncs against an honest daemon. From the fork height upward
it erases the transfers, their key images and public keys, the payments, the
confirmed transactions and the background-sync records, and crops
`m_blockchain`. The false view is not corrected in place; it is deleted.

So a corruption that lives only in state at or above the fork height is
transient, and the finding needs to say what damage is done before the detach
lands -- a spent key image, a leaked address, funds moved. "The wallet believes
something wrong for a while" is not by itself an impact.

MEASURED, on 11185: pending multisig rescan state is applied by transfer index
with no check on which output sits at that index, so a reorg during the rescan
was proposed as writing a composite key image built from another output. The
wrong indices only arise from a lying daemon's chain view, and the resync
erases it (`src/wallet/wallet2.cpp:4433`). The code is identical in
`origin/base`.

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
  (`src/wallet/wallet2.cpp:4414`, `:4421`), and `handle_reorg` throws before
  calling it at all when the daemon claims a reorg below the last checkpoint.
  A state you can drive into one of those throws is a finding about the detach
  itself, not something the detach refutes.

---

None of this means "do not report". It means the report must name the guard you
checked and explain why it does not hold. A finding that survives an honest
attempt at each applicable refutation above is worth a security engineer's
time. One that has not been through this is not.
