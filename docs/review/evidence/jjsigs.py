"""Extract multi-line `pub fn` signatures from jj-lib source and bucket them."""
import collections
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
sigs = []
for p in root.rglob("*.rs"):
    if "/tests" in str(p) or p.name.startswith("test"):
        continue
    t = re.sub(r"//[^\n]*", "", p.read_text())
    # drop #[cfg(test)] mod tests { ... } roughly: cut at "mod tests"
    cut = t.find("#[cfg(test)]\nmod tests")
    if cut != -1:
        t = t[:cut]
    for m in re.finditer(r"\bpub (?:async )?fn \w+", t):
        end = m.end()
        depth = 0
        while end < len(t):
            c = t[end]
            if c in "(<[":
                depth += 1
            elif c in ")>]":
                depth -= 1
            elif c in "{;" and depth <= 0:
                break
            end += 1
        sigs.append((p.name, " ".join(t[m.start():end].split())))

feat = collections.Counter()
clean = 0
for f, s in sigs:
    tags = []
    if s.startswith("pub async fn"):
        tags.append("async")
    if re.search(r"fn \w+<", s):
        tags.append("generic")
    if re.search(r"\bimpl \w", s):
        tags.append("impl_trait")
    if "dyn " in s:
        tags.append("dyn")
    if re.search(r"'[a-z_]+\b(?!')", s.replace("'static", "")):
        tags.append("lifetime")
    if re.search(r"Fn(Mut|Once)?\(", s):
        tags.append("closure")
    if "&mut self" in s or "&mut MutableRepo" in s:
        tags.append("mut")
    if re.search(r"Stream|Iterator", s):
        tags.append("stream_iter")
    for t_ in tags:
        feat[t_] += 1
    if not tags:
        clean += 1
print("total pub fn (non-test, incl. non-reachable modules):", len(sigs))
print("no async/generic/impl/dyn/lifetime/closure/mut/stream:", clean)
for k, v in feat.most_common():
    print(f"  {k}: {v}")
