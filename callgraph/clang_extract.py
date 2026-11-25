# Per-TU libclang pass: function definitions, virtual calls, address-taken functions,
# lambdas, and method overrides. Output: one JSON per TU.
import json, sys, shlex, os, hashlib
import clang.cindex as ci
from clang.cindex import CursorKind as K
ROOT = sys.argv[1]            # monero checkout (absolute)
OUT = sys.argv[2]
entry = json.loads(sys.argv[3])
FUNCS = {K.FUNCTION_DECL, K.CXX_METHOD, K.CONSTRUCTOR, K.DESTRUCTOR, K.CONVERSION_FUNCTION, K.FUNCTION_TEMPLATE}
def ours(f): return f is not None and (f.startswith(ROOT + "/src/") or f.startswith(ROOT + "/contrib/epee/"))
args = entry.get("arguments") or shlex.split(entry["command"])
args = args[1:]
clean, skip = [], False
for i, a in enumerate(args):
    if skip: skip = False; continue
    if a in ("-o", "-c"): skip = a == "-o"; continue
    if a == entry["file"] or a.endswith(os.path.basename(entry["file"])) and not a.startswith("-"): continue
    if a.startswith("-fcallgraph-info") or a.startswith("-fstack-") or a in ("-fno-fat-lto-objects",): continue
    clean.append(a)
# libclang does not find GCC's C++ headers or its own resource headers by itself
GXX = os.environ.get("GXX_VERSION", "13")
clean += ["-resource-dir", os.environ.get("CLANG_RESOURCE_DIR", "/usr/lib/llvm-18/lib/clang/18"),
          f"-isystem/usr/include/c++/{GXX}", f"-isystem/usr/include/x86_64-linux-gnu/c++/{GXX}", f"-isystem/usr/include/c++/{GXX}/backward",
          "-Wno-everything", "-ferror-limit=0"]
idx = ci.Index.create()
tu = idx.parse(entry["file"], args=clean, options=ci.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES * 0)
errs = [str(d) for d in tu.diagnostics if d.severity >= 3][:5]
defs, vcalls, addr, lambdas, overrides = {}, [], [], [], {}
depcalls, virt, gaddr = [], {}, []
bases, methods = {}, []
def targets(r):
    """Referenced function cursors; overload sets / template-ids expand to every candidate."""
    if r is None: return []
    if r.kind == K.OVERLOADED_DECL_REF:
        n = ci.conf.lib.clang_getNumOverloadedDecls(r)
        return [x for x in (ci.conf.lib.clang_getOverloadedDecl(r, i) for i in range(n)) if x.kind in FUNCS]
    return [r] if r.kind in FUNCS else []
CLASSES = {K.CLASS_DECL, K.STRUCT_DECL, K.CLASS_TEMPLATE, K.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION}
def class_usr(decl):
    """USR of a class, mapping template specializations to their primary template."""
    if decl is None or decl.kind not in CLASSES: return None
    t = ci.conf.lib.clang_getSpecializedCursorTemplate(decl)
    while t is not None and t.kind in CLASSES:
        decl = t; t = ci.conf.lib.clang_getSpecializedCursorTemplate(decl)
    return decl.get_usr() or None
def type_class(ty):
    for _ in range(4):
        if ty.kind in (ci.TypeKind.POINTER, ci.TypeKind.LVALUEREFERENCE, ci.TypeKind.RVALUEREFERENCE):
            ty = ty.get_pointee(); continue
        break
    d = ty.get_declaration()
    if d is not None and d.kind == K.TYPEDEF_DECL:
        d = d.underlying_typedef_type.get_declaration()
    return class_usr(d)
class_cursors = {}
def index_classes(c, depth=0):
    for ch in c.get_children():
        if ch.kind in CLASSES and ch.is_definition():
            u = class_usr(ch)
            if u and u not in class_cursors: class_cursors[u] = ch
        if ch.kind in CLASSES or ch.kind in (K.NAMESPACE, K.UNEXPOSED_DECL, K.LINKAGE_SPEC):
            index_classes(ch, depth + 1)
def field_class(owner, name, seen=None):
    seen = seen or set()
    if owner is None or owner in seen: return None
    seen.add(owner)
    cur = class_cursors.get(owner)
    if cur is None: return None
    for ch in cur.get_children():
        if ch.kind in (K.FIELD_DECL, K.VAR_DECL) and ch.spelling == name:
            return type_class(ch.type)
    for ch in cur.get_children():
        if ch.kind == K.CXX_BASE_SPECIFIER:
            for r in ch.get_children():
                if r.kind in (K.TEMPLATE_REF, K.TYPE_REF) and r.referenced is not None:
                    got = field_class(class_usr(r.referenced), name, seen)
                    if got: return got
    return None
def expr_class(e, enclosing):
    """Class of an expression's (pointee) type, resolving dependent member chains via field types."""
    for _ in range(6):
        if e is None: return None
        if e.kind == K.UNEXPOSED_EXPR:
            nxt = next(iter(e.get_children()), None)
            if nxt is None: break
            e = nxt; continue
        break
    r = type_class(e.type) if e.type.kind != ci.TypeKind.INVALID else None
    if r: return r
    if e.kind == K.CXX_THIS_EXPR: return enclosing
    if e.referenced is not None and e.referenced.kind in (K.FIELD_DECL, K.VAR_DECL, K.PARM_DECL):
        r = type_class(e.referenced.type)
        if r: return r
    if e.kind == K.MEMBER_REF_EXPR:
        ids = [t.spelling for t in e.get_tokens() if t.kind == ci.TokenKind.IDENTIFIER]
        if not ids: return None
        sub = next(iter(e.get_children()), None)
        owner = expr_class(sub, enclosing) if sub is not None else enclosing
        return field_class(owner, ids[-1])
    return None
cur_class = []
def loc(c):
    l = c.location; return (l.file.name if l.file else None, l.line, l.column)
def visit(c, fn):
    k = c.kind
    if k in CLASSES and c.is_definition() and ours(loc(c)[0]):
        cu = class_usr(c)
        for ch in c.get_children():
            if ch.kind == K.CXX_BASE_SPECIFIER:
                b = None
                for r in ch.get_children():
                    if r.kind in (K.TEMPLATE_REF, K.TYPE_REF) and r.referenced is not None:
                        b = class_usr(r.referenced) or (r.referenced.get_usr() if r.referenced.kind in CLASSES else None)
                        if r.kind == K.TEMPLATE_REF: break
                b = b or type_class(ch.type)
                if b and cu: bases.setdefault(cu, []).append(b)
    if k in (K.CXX_METHOD, K.FUNCTION_TEMPLATE, K.DESTRUCTOR) and c.is_definition():
        owner = class_usr(c.semantic_parent) if c.semantic_parent is not None else None
        if owner: methods.append([owner, c.spelling, c.get_usr()])
    if k in FUNCS or k == K.LAMBDA_EXPR:
        f, line, col = loc(c)
        if k == K.LAMBDA_EXPR:
            key = f"lambda:{f}:{line}:{col}"
            if fn: lambdas.append([fn, key, f, line])
            defs[key] = [f, line, c.extent.end.line]
            fn = key
        elif c.is_definition():
            fn = c.get_usr()
            defs[fn] = [f, c.extent.start.line, c.extent.end.line]
            if k == K.CXX_METHOD and c.is_virtual_method():
                pass
        if k in (K.CXX_METHOD, K.DESTRUCTOR) and (c.is_virtual_method() or any(
                ch.kind in (K.CXX_OVERRIDE_ATTR, K.CXX_FINAL_ATTR) for ch in c.get_children())):
            virt[c.get_usr()] = [c.spelling, class_usr(c.semantic_parent) if c.semantic_parent is not None else None]
        if k == K.CXX_METHOD:
            n = ci.c_uint(0); arr = ci.POINTER(ci.Cursor)()
            ci.conf.lib.clang_getOverriddenCursors(c, ci.byref(arr), ci.byref(n))
            if n.value:
                overrides.setdefault(c.get_usr(), []).extend(arr[i].get_usr() for i in range(n.value))
                ci.conf.lib.clang_disposeOverriddenCursors(arr)
    elif fn and k == K.CALL_EXPR and c.referenced is None:
        # dependent call in a template: libclang gives no name; take the callee's last identifier token
        ch = next(iter(c.get_children()), None)
        name = c.spelling
        if ch is not None and not name:
            ids = [t.spelling for t in ch.get_tokens() if t.kind == ci.TokenKind.IDENTIFIER]
            name = ids[-1] if ids else ""
        recv = None
        if ch is not None and ch.kind == K.MEMBER_REF_EXPR:
            base = next(iter(ch.get_children()), None)
            recv = expr_class(base, cur_class[-1] if cur_class else None) if base is not None else (cur_class[-1] if cur_class else None)
        if name: depcalls.append([fn, name, loc(c)[1], recv])
    elif fn and k == K.CALL_EXPR:
        r = c.referenced
        if r is not None and r.kind == K.CXX_METHOD and r.is_virtual_method():
            # qualified calls (Base::f()) are non-virtual; detect via '::' immediately before the name token
            toks = [t.spelling for t in c.get_tokens()][:64]
            qual = any(toks[i] == "::" and toks[i+1] == r.spelling for i in range(len(toks)-1))
            if not qual:
                vcalls.append([fn, r.get_usr(), r.spelling, loc(c)[1]])
    elif not fn and k in (K.DECL_REF_EXPR, K.MEMBER_REF_EXPR):
        for r in targets(c.referenced):
            gaddr.append([r.get_usr(), r.spelling, loc(c)[0], loc(c)[1]])
    elif fn and k in (K.DECL_REF_EXPR, K.MEMBER_REF_EXPR):
        for r in targets(c.referenced):
            addr.append([fn, r.get_usr(), r.spelling, loc(c)[1], loc(c)[2], loc(c)[0]])
    pushed = False
    if k in CLASSES:
        cur_class.append(class_usr(c)); pushed = True
    elif k in FUNCS and c.semantic_parent is not None and c.semantic_parent.kind in CLASSES:
        cur_class.append(class_usr(c.semantic_parent)); pushed = True
    for ch in c.get_children():
        f = ch.location.file
        if fn is None and f is not None and not ours(f.name) and ch.kind not in (K.NAMESPACE, K.UNEXPOSED_DECL, K.LINKAGE_SPEC):
            continue
        visit(ch, fn)
    if pushed: cur_class.pop()
# record call sites so address-taken refs that are actually callees can be dropped
callpos = set()
def calls(c):
    if c.kind == K.CALL_EXPR:
        # keyed with the callee's name: every cursor in one macro expansion shares a location
        ch = next(iter(c.get_children()), None)
        while ch is not None and ch.kind == K.UNEXPOSED_EXPR:
            ch = next(iter(ch.get_children()), None)
        if ch is not None and ch.kind in (K.DECL_REF_EXPR, K.MEMBER_REF_EXPR, K.OVERLOADED_DECL_REF):
            f_ = ch.location.file.name if ch.location.file else None
            for r in targets(ch.referenced) or ([c.referenced] if c.referenced is not None else []):
                callpos.add((f_, ch.location.line, ch.location.column, r.spelling))
    for ch in c.get_children():
        f = ch.location.file
        if f is not None and not ours(f.name) and ch.kind not in (K.NAMESPACE, K.UNEXPOSED_DECL, K.LINKAGE_SPEC):
            continue
        calls(ch)
index_classes(tu.cursor); visit(tu.cursor, None); calls(tu.cursor)
addr = [a[:5] for a in addr if (a[5], a[3], a[4], a[2]) not in callpos and not a[2].startswith("operator")]
h = hashlib.sha1(entry["file"].encode()).hexdigest()[:12]
json.dump({"file": entry["file"], "errors": errs,
           "defs": {k: v for k, v in defs.items() if ours(v[0])} | {k: v for k, v in defs.items() if not ours(v[0]) and False},
           "all_defs": defs, "vcalls": vcalls, "addr": addr, "lambdas": lambdas, "overrides": overrides,
           "depcalls": depcalls, "virtual": virt, "global_addr": gaddr,
           "bases": bases, "methods": methods},
          open(f"{OUT}/{h}.json", "w"))
print(entry["file"], len(defs), len(vcalls), len(addr), len(errs))
