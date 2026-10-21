"""Classify jj-lib's public functions/methods from rustdoc JSON.

Buckets per fn (first match wins):
  async        header.is_async
  closure      an input is impl Fn*/dyn Fn*/generic bound by Fn*
  generic      fn has type params (non-lifetime) or impl Trait in args/ret
  dyn          dyn Trait anywhere in sig
  lifetime     named lifetime (not 'static) in sig, or returns a borrowed ref
  simple       none of the above
Also reports how many 'simple' ones use only 'plain' types (primitives,
String/str/Path/PathBuf, Option/Vec/slices/Result/Box/Arc of those, plus self).
"""
import collections
import json
import sys

d = json.load(open(sys.argv[1]))
print("format_version", d.get("format_version"))
idx = d["index"]
crate_id = d["root"]
crate_name_id = idx[str(crate_id)]["crate_id"] if str(crate_id) in idx else 0

PLAIN = {"String", "str", "Path", "PathBuf", "Option", "Vec", "Result", "Box", "Arc", "Self", "bool"}


def walk(t, acc):
    if t is None:
        return
    if isinstance(t, dict):
        for k, v in t.items():
            if k == "generic":
                if v != "Self":
                    acc["generic"] += 1
            elif k == "impl_trait":
                acc["impl"] += 1
                for b in v:
                    tb = b.get("trait_bound") if isinstance(b, dict) else None
                    if tb and tb["trait"].get("path", "").split("::")[-1] in ("Fn", "FnMut", "FnOnce"):
                        acc["closure"] += 1
                walk(v, acc)
            elif k == "dyn_trait":
                acc["dyn"] += 1
                for tr in v.get("traits", []):
                    if tr["trait"].get("path", "").split("::")[-1] in ("Fn", "FnMut", "FnOnce"):
                        acc["closure"] += 1
                walk(v, acc)
            elif k == "borrowed_ref":
                lt = v.get("lifetime")
                if lt and lt != "'static":
                    acc["lifetime"] += 1
                walk(v, acc)
            elif k == "resolved_path":
                name = v.get("path", "").split("::")[-1]
                acc["paths"].add(name)
                args = v.get("args") or {}
                ab = args.get("angle_bracketed") if isinstance(args, dict) else None
                if ab:
                    for a in ab.get("args", []):
                        if isinstance(a, dict) and "lifetime" in a and a["lifetime"] != "'static":
                            acc["lifetime"] += 1
                walk(v, acc)
            elif k == "primitive":
                acc["paths"].add(v)
            else:
                walk(v, acc)
    elif isinstance(t, list):
        for x in t:
            walk(x, acc)


# Reachable public items: those listed in "paths" with crate_id == 0, plus
# methods of impls on such types.
local_types = {k for k, v in d["paths"].items() if v["crate_id"] == 0}
fns = []
for iid, it in idx.items():
    if it.get("crate_id") != 0:
        continue
    inner = it.get("inner", {})
    if "impl" in inner:
        imp = inner["impl"]
        if imp.get("trait") is not None or imp.get("is_synthetic") or imp.get("blanket_impl"):
            continue
        for mid in imp["items"]:
            m = idx.get(str(mid))
            if m and "function" in m.get("inner", {}) and m.get("visibility") == "public":
                fns.append(m)
    elif "function" in inner and it.get("visibility") == "public" and iid in local_types:
        fns.append(it)

# dedupe
seen = set()
uniq = []
for f in fns:
    if f["id"] in seen:
        continue
    seen.add(f["id"])
    uniq.append(f)
fns = uniq

b = collections.Counter()
plain_simple = 0
selfmut = 0
for f in fns:
    fn = f["inner"]["function"]
    acc = collections.Counter()
    acc["paths"] = set()
    walk(fn["sig"], acc)
    gparams = [p for p in fn["generics"]["params"] if "type" in p["kind"]]
    lparams = [p for p in fn["generics"]["params"] if "lifetime" in p["kind"]]
    inputs = fn["sig"]["inputs"]
    if inputs and inputs[0][0] == "self":
        t = inputs[0][1]
        if isinstance(t, dict) and "borrowed_ref" in t and t["borrowed_ref"].get("is_mutable"):
            selfmut += 1
    if fn["header"]["is_async"]:
        k = "async"
    elif acc["closure"] or any(
        any(
            isinstance(bd, dict) and "trait_bound" in bd
            and bd["trait_bound"]["trait"].get("path", "").split("::")[-1] in ("Fn", "FnMut", "FnOnce")
            for bd in p["kind"]["type"].get("bounds", [])
        )
        for p in gparams
    ):
        k = "closure"
    elif gparams or acc["impl"]:
        k = "generic"
    elif acc["dyn"]:
        k = "dyn"
    elif acc["lifetime"] or lparams:
        k = "lifetime"
    else:
        k = "simple"
        if acc["paths"] <= PLAIN | {"u8", "u16", "u32", "u64", "usize", "i32", "i64", "f64", "char"}:
            plain_simple += 1
    b[k] += 1
total = len(fns)
print("reachable public fns+inherent methods:", total)
for k, v in b.most_common():
    print(f"  {k:9} {v:5}  {v / total:.0%}")
print("  of simple, only plain std types:", plain_simple)
print("  &mut self receivers:", selfmut)
traits = sum(1 for k, v in d["paths"].items() if v["crate_id"] == 0 and v["kind"] == "trait")
print("public traits:", traits)
