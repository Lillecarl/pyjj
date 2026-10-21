"""GIL audit: which bound fns reach blocking jj-lib work, and which detach.

Crude name-based call graph over pyjj-bindings/src/*.rs.
Blocking signal: pollster/tokio block_on, std::fs, process spawn, or
jj-lib sync store/repo calls that read the backend.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

src = Path(sys.argv[1])
BLOCK = re.compile(
    r"block_on|\bfs::|std::fs|Command::new|\.get_commit\(|\.get_tree\(|"
    r"\.root_tree\(|\.parents\(|\.evaluate\(|load_at_head|\.load_at\(|"
    r"\.commit\(\"|\.commit\(|\.reload_at|\.write_tree|\.write\(|"
    r"git::|snapshot|check_out|read_file|ReadonlyRepo|Workspace::load"
)
rows = []
for path in sorted(src.glob("*.rs")):
    text = re.sub(r"//[^\n]*", "", path.read_text())
    spans = []
    for m in re.finditer(r"#\[pymethods\]\s*impl[^{]*\{", text):
        s = m.end() - 1
        d = 0
        for i in range(s, len(text)):
            d += text[i] == "{"
            d -= text[i] == "}"
            if d == 0:
                spans.append((s, i))
                break
    for m in re.finditer(r"\bfn\s+(\w+)", text):
        name = m.group(1)
        j = m.end()
        p = 0
        bs = None
        while j < len(text):
            c = text[j]
            p += c == "("
            p -= c == ")"
            if c == ";" and p == 0:
                break
            if c == "{" and p == 0:
                bs = j
                break
            j += 1
        if bs is None:
            continue
        d = 0
        for k in range(bs, len(text)):
            d += text[k] == "{"
            d -= text[k] == "}"
            if d == 0:
                be = k
                break
        body = text[bs + 1 : be]
        sig = text[m.start() : bs]
        prefix = text[max(0, m.start() - 400) : m.start()]
        last = prefix.rsplit("fn ", 1)[-1]
        in_pm = any(s < m.start() < e for s, e in spans)
        is_pyfn = "#[pyfunction]" in last
        line = text[: m.start()].count("\n") + 1
        rows.append(
            dict(
                file=path.name,
                line=line,
                name=name,
                bound=in_pm or is_pyfn,
                body=body,
                sig=sig,
                direct=bool(BLOCK.search(body)),
                detach=(".detach(" in body or "allow_threads" in body),
                aio=("spawn_blocking_py" in body),
                py=("py: Python" in sig or "Python<'" in sig),
            )
        )

helpers = defaultdict(list)
for r in rows:
    if not r["bound"]:
        helpers[r["name"]].append(r)
calls = {}
for i, r in enumerate(rows):
    names = set(re.findall(r"\b(\w+)\s*(?:::<[^>]*>)?\(", r["body"]))
    calls[i] = [h for n in names if n in helpers for h in helpers[n] if h is not r]

memo = {}


def blocks(r, stack=()):
    key = id(r)
    if key in memo:
        return memo[key]
    if key in stack:
        return False
    res = r["direct"] or any(
        blocks(h, stack + (key,)) for h in calls[rows.index(r)]
    )
    memo[key] = res
    return res


out = []
for r in rows:
    if not r["bound"] or r["name"].startswith("__"):
        continue
    out.append(
        dict(
            file=r["file"],
            line=r["line"],
            name=r["name"],
            blocks=blocks(r),
            detach=r["detach"],
            aio=r["aio"],
        )
    )
json.dump(out, open(sys.argv[2], "w"), indent=0)
by = defaultdict(lambda: [0, 0, 0, 0])
for o in out:
    b = by[o["file"]]
    b[0] += 1
    b[1] += o["blocks"]
    b[2] += o["blocks"] and not o["detach"] and not o["aio"]
    b[3] += o["detach"]
print("file bound blocking blocking_with_gil detached")
for f, b in sorted(by.items()):
    print(f, *b)
print("TOTAL", *[sum(b[i] for b in by.values()) for i in range(4)])
