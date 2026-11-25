# usage: gen_entrypoints.py <monero checkout> [refused.json] > entrypoints.toml
# refused.json: the daemon RPC handlers and command types restricted mode refuses.
import json, re, sys
from pathlib import Path
src = Path(sys.argv[1])  # monero checkout
out = []
refused = {"handlers": [], "commands": []}
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
def handlers(hdr, pat, cmds=None):
    pub, adm = [], []
    text = (src/hdr).read_text()
    for m in re.finditer(pat, text):
        macro, cb = m.group(1), m.group(2)
        restricted = macro.endswith("_IF") and "!m_restricted" in m.group(0)
        (adm if restricted else pub).append(cb)
        if cmds is not None and m.lastindex >= 3 and m.group(3):
            cmds.append((cb, m.group(3), restricted))
    return pub, adm
# Every MAP_URI_* and MAP_JON_RPC* registration, _IF or not; a line this does not
# parse would be a handler with no trust label, so it fails the build.
RPC = r'\b(MAP_URI_\w+|MAP_JON_RPC\w*)\(\s*"[^"]*"\s*,\s*(\w+)\s*(?:,\s*(\w+))?[^\n]*'
for hdr in ("src/rpc/core_rpc_server.h", "src/wallet/wallet_rpc_server.h"):
    text = (src/hdr).read_text()
    used = len(re.findall(r"^\s*(MAP_URI_\w+|MAP_JON_RPC\w*)\(", text, re.M))
    if used != len(re.findall(RPC, text)):
        sys.exit(f"gen_entrypoints: {hdr}: {used} MAP_ registrations, {len(re.findall(RPC, text))} parsed")
cmds = []
pub, adm = handlers("src/rpc/core_rpc_server.h", RPC, cmds)
adm = [a for a in adm if a not in pub]
refused["handlers"] = sorted(set(adm))
refused["commands"] = sorted({c for cb, c, r in cmds if r and cb in adm} - {c for cb, c, r in cmds if cb in pub})
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
if len(sys.argv) > 2:
    json.dump(refused, open(sys.argv[2], "w"))
