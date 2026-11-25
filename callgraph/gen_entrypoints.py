import re, sys
from pathlib import Path
src = Path(sys.argv[1])  # monero checkout
out = []
def rule(glob, names, kind, trust, asset, desc):
    names = sorted(set(names))
    if not names: return
    out.append(f'''[[entrypoint]]
file_glob = "{glob}"
name_regex = "(^|::)({'|'.join(names)})$"
kind = "{kind}"
trust = "{trust}"
asset_value = "{asset}"
description = "{desc}"
''')
def handlers(hdr, pat):
    pub, adm = [], []
    for m in re.finditer(pat, (src/hdr).read_text()):
        macro, cb = m.group(1), m.group(2)
        (adm if macro.endswith("_IF") and "!m_restricted" in m.group(0) else pub).append(cb)
    return pub, adm
RPC = r'(MAP_URI_AUTO_JON2_IF|MAP_URI_AUTO_JON2|MAP_URI_AUTO_BIN2|MAP_JON_RPC_WE_IF|MAP_JON_RPC_WE|MAP_JON_RPC)\(\s*"[^"]*"\s*,\s*(\w+)[^\n]*'
pub, adm = handlers("src/rpc/core_rpc_server.h", RPC)
adm = [a for a in adm if a not in pub]
rule("src/rpc/core_rpc_server.cpp", pub, "api", "untrusted_external", "high", "daemon RPC, restricted-mode reachable")
rule("src/rpc/core_rpc_server.cpp", adm, "api", "semi_trusted_external", "high", "daemon RPC, unrestricted only")
wpub, wadm = handlers("src/wallet/wallet_rpc_server.h", RPC)
rule("src/wallet/wallet_rpc_server.cpp", wpub+wadm, "api", "semi_trusted_external", "high", "wallet RPC")
P2P = r'(HANDLE_INVOKE_T2|HANDLE_NOTIFY_T2)\(\s*\w+\s*,\s*&\w+::(\w+)\)'
p, _ = handlers("src/p2p/net_node.h", P2P)
rule("src/p2p/net_node.inl.hpp", p, "api", "untrusted_external", "high", "P2P levin command")
p, _ = handlers("src/cryptonote_protocol/cryptonote_protocol_handler.h", P2P)
rule("src/cryptonote_protocol/cryptonote_protocol_handler.inl.hpp", p, "api", "untrusted_external", "high", "P2P cryptonote protocol notify")
rule("epee/include/net/levin_protocol_handler_async.h", ["handle_recv"], "api", "untrusted_external", "high", "levin frame parser")
rule("epee/include/net/http_protocol_handler.inl.hpp", ["handle_recv"], "api", "untrusted_external", "high", "HTTP request parser")
rule("src/rpc/daemon_handler.cpp", ["handle", "handle_message"], "api", "semi_trusted_external", "medium", "ZMQ RPC")
print("\n".join(out))
