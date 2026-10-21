"""Rough per-function classifier for pyjj-bindings/src/*.rs.

Splits each file into fns by brace matching, tags each fn as
pymethod / pyfunction / helper, and buckets bound fns by body heuristics.
"""
import json
import re
import sys
from pathlib import Path

src = Path(sys.argv[1])
rows = []


def strip_comments(text):
    text = re.sub(r"//[^\n]*", "", text)
    return text


for path in sorted(src.glob("*.rs")):
    raw = path.read_text()
    text = strip_comments(raw)
    # find impl blocks with #[pymethods]
    pymethod_spans = []
    for m in re.finditer(r"#\[pymethods\]\s*impl[^{]*\{", text):
        start = m.end() - 1
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    pymethod_spans.append((start, i))
                    break
    for m in re.finditer(r"\bfn\s+(\w+)", text):
        name = m.group(1)
        # find body
        j = m.end()
        paren = 0
        body_start = None
        while j < len(text):
            c = text[j]
            if c == "(" or c == "<":
                paren += 1 if c == "(" else 0
            if c == ")":
                paren -= 1
            if c == ";" and paren == 0:
                break
            if c == "{" and paren == 0:
                body_start = j
                break
            j += 1
        if body_start is None:
            continue
        depth = 0
        for k in range(body_start, len(text)):
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
                if depth == 0:
                    body_end = k
                    break
        body = text[body_start + 1 : body_end]
        lines = [l for l in body.splitlines() if l.strip()]
        prefix = text[max(0, m.start() - 300) : m.start()]
        in_pm = any(s < m.start() < e for s, e in pymethod_spans)
        is_pyfn = "#[pyfunction]" in prefix.split("fn ")[-1] if "fn " in prefix else "#[pyfunction]" in prefix
        kind = "pymethod" if in_pm else ("pyfunction" if is_pyfn else "helper")
        rows.append(
            dict(
                file=path.name,
                name=name,
                kind=kind,
                body_lines=len(lines),
                block_on=body.count("block_on"),
                crate_calls=len(re.findall(r"crate::\w+::\w+\(", body)),
                spawn=("spawn_blocking_py" in body),
                with_mut=("with_mut_repo" in body),
                take_inner=("take_inner" in body),
                pydict=("PyDict" in body),
                dunder=name.startswith("__"),
            )
        )

print(json.dumps(rows))
