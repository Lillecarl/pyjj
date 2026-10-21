"""For bound methods that forward to an in-crate helper, report the helper's body size."""
import json, re, sys, collections
from pathlib import Path
rows = json.load(open(sys.argv[1]))
helpers = {(r["file"][:-3], r["name"]): r["body_lines"] for r in rows if r["kind"] == "helper"}
src = Path(sys.argv[2])
out = collections.Counter()
detail = []
for f in sorted(src.glob("*.rs")):
    t = f.read_text()
    for m in re.finditer(r"crate::(\w+)::(\w+)\(", t):
        pass
for r in rows:
    if r["kind"] == "helper" or r["crate_calls"] == 0:
        continue
    t = (src / r["file"]).read_text()
    i = t.find(f"fn {r['name']}")
    body = t[i : i + 3000]
    end = body.find("\n    }\n")
    body = body[: end if end > 0 else 3000]
    calls = re.findall(r"crate::(\w+)::(\w+)\(", body)
    sizes = [helpers.get(c, 0) for c in calls]
    tot = sum(sizes)
    bucket = "b" if tot <= 8 else ("c" if tot > 15 else "b/c")
    out[bucket] += 1
    detail.append((r["file"], r["name"], calls, tot))
print(out)
for d in sorted(detail, key=lambda x: x[3])[:15]: print(d)
