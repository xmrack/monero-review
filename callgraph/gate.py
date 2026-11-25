# Checks a callgraph.json before it is published. Names only, no line numbers, so it survives
# upstream edits; a failure means the build or a merge rule broke, not that monero changed.
# usage: gate.py <callgraph.json>     exit 1 on failure
import collections, json, re, sys
g = json.load(open(sys.argv[1]))
L = [n[1] for n in g["nodes"]]
succ = collections.defaultdict(set)
for a, b, _ in g["edges"]: succ[a].add(b)
fails = []
def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what)
    if not ok: fails.append(what)
def ids(p): return [i for i, x in enumerate(L) if re.search(p, x)]
def edge(a, b):
    """a calls b, directly or from a lambda inside a"""
    A, B = set(ids(a)), set(ids(b))
    return any(y in B for x in A for y in succ[x]) or \
        any(y in B for x in A for l in succ[x] if "{lambda" in L[l] for y in succ[l])
def reach(start):
    seen, st = set(start), list(start)
    while st:
        for y in succ[st.pop()]:
            if y not in seen: seen.add(y); st.append(y)
    return seen

check(len(g["nodes"]) >= 12000, f"function nodes {len(g['nodes'])} >= 12000")
check(len(g["edges"]) >= 38000, f"call edges {len(g['edges'])} >= 38000")
DAEMON = "daemon reply to the wallet (remote node)"
trust = collections.Counter(t for _, t, d in g["entrypoints"] if d != DAEMON)
reply = [e for e, _, d in g["entrypoints"] if d == DAEMON]
check(trust["untrusted_external"] >= 45, f"untrusted network entrypoints {trust['untrusted_external']} >= 45")
check(trust["semi_trusted_external"] >= 120, f"semi-trusted entrypoints {trust['semi_trusted_external']} >= 120")
check(len(reply) >= 20, f"daemon-reply entrypoints {len(reply)} >= 20")
guess = sorted({d for _, _, d in g["entrypoints"] if d.startswith(("C/C++ exported symbol", "Rust FFI export"))})
check(not guess, f"no trailmark heuristic entrypoints {guess}")
check(bool(reach(reply) & set(ids(r"wallet2::process_new_transaction$"))),
      "daemon replies reach wallet2::process_new_transaction")

T = r"(<[^>]*>)?"
CHAINS = [
    (r"levin::async_protocol_handler::handle_recv$", r"node_server::(notify|invoke)$"),
    (r"node_server::(notify|invoke)$", r"node_server::handle_invoke_map$"),
    (r"node_server::handle_invoke_map$", r"t_cryptonote_protocol_handler::handle_invoke_map$"),
    (r"t_cryptonote_protocol_handler::handle_invoke_map$", r"t_cryptonote_protocol_handler" + T + r"::handle_notify_new_transactions$"),
    (r"handle_notify_new_transactions$", r"core::handle_incoming_tx$"),
    (r"core::handle_incoming_tx$", r"core::add_new_tx$"),
    (r"core::add_new_tx$", r"tx_memory_pool::add_tx$"),
    (r"tx_memory_pool::add_tx$", r"tx_memory_pool::check_tx_inputs$"),
    (r"tx_memory_pool::check_tx_inputs$", r"Blockchain::check_tx_inputs$"),
    (r"simple_http_connection_handler" + T + r"::handle_recv$", r"simple_http_connection_handler" + T + r"::handle_buff_in$"),
    (r"http_custom_handler" + T + r"::handle_request$", r"core_rpc_server::handle_http_request$"),
    (r"core_rpc_server::handle_http_request$", r"core_rpc_server::handle_http_request_map$"),
    (r"core_rpc_server::handle_http_request_map$", r"core_rpc_server::on_send_raw_tx$"),
    (r"core_rpc_server::on_send_raw_tx$", r"core::handle_incoming_tx$"),
    (r"rpc::\(anonymous\)::handle_message$", r"DaemonHandler::handle$"),
]
for a, b in CHAINS: check(edge(a, b), f"edge {a} -> {b}")
check(not edge(r"make_pool_supplement_from_block_entry$", r"tx_memory_pool::add_tx$"),
      "no edge make_pool_supplement_from_block_entry -> tx_memory_pool::add_tx")

# Instantiations must not leak into each other: each server reaches only its own frame parser.
LEVIN, HTTP = r"levin::async_protocol_handler::handle_recv$", r"simple_http_connection_handler" + T + r"::handle_recv$"
for root, bad in ((r"^daemonize::t_rpc::run$", LEVIN), (r"wallet_rpc_server::run$", LEVIN),
                  (r"^daemonize::t_p2p::run$", HTTP), (r"node_server" + T + r"::run$", HTTP)):
    R = ids(root)
    check(bool(R) and not (reach(R) & set(ids(bad))), f"{root} does not reach {bad}")
disp = set(ids(r"(handle_recv|handle_invoke_map|handle_http_request_map)$"))
leaks = sorted({L[e] for e, t, _ in g["entrypoints"] if t != "trusted_internal" and e not in disp
                and reach([e]) & disp and not L[e].endswith(("::handle_handshake", "::handle_http_request"))})
check(not leaks, f"no handler entrypoint reaches a dispatcher {leaks[:5]}")
sink = set(ids(r"Blockchain::check_tx_inputs$"))
n = sum(1 for e, t, _ in g["entrypoints"] if t == "untrusted_external" and reach([e]) & sink)
check(n >= 10, f"untrusted entrypoints reaching Blockchain::check_tx_inputs {n} >= 10")
cut = {tuple(x) for x in g.get("untrusted_cut", [])}
check(any(re.search(r"COMMAND_RPC_SETBANS::request_t::_?load$", L[b]) for _, b in cut)
      and any(L[b].endswith("core_rpc_server::on_set_bans") for _, b in cut),
      "untrusted paths skip the parser and handler of a method restricted mode refuses")
semi = {L[e] for e, t, _ in g["entrypoints"] if t == "semi_trusted_external"}
check({"cryptonote::core_rpc_server::handle_http_request", "tools::wallet_rpc_server::handle_http_request"} <= semi,
      "the RPC dispatchers are semi-trusted entrypoints")
sys.exit(1 if fails else 0)
