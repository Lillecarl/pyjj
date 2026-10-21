"""Add the `*_async` siblings to the stub maturin generates.

`_async.py` installs them at import time, so pyo3's introspection cannot
see them. Each one gets the sync method's parameters and returns an
awaitable of its result. Usage: `python3 stub_async.py ASYNC_PY STUB_PYI`;
the stub is rewritten in place.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def _tables(source: str) -> dict[str, dict[str, tuple[str, ...]]]:
    """`INSTANCE_METHODS` and `STATIC_METHODS`, read without importing."""
    tables: dict[str, dict[str, tuple[str, ...]]] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            tables[node.target.id] = ast.literal_eval(node.value)  # type: ignore[arg-type]
    return tables


def _sibling(method: ast.FunctionDef, cls: str, static: bool) -> str:
    returns = ast.unparse(method.returns) if method.returns else "None"
    decorator = "    @staticmethod\n" if static else ""
    return (
        f"{decorator}    async def {method.name}_async({ast.unparse(method.args)}) -> {returns}:\n"
        f'        """Async sibling of `{cls}.{method.name}()`, run in a worker thread."""\n'
    )


def add_siblings(stub: str, async_source: str) -> str:
    tables = _tables(async_source)
    wanted = {
        (cls, name): static
        for key, static in (("INSTANCE_METHODS", False), ("STATIC_METHODS", True))
        for cls, names in tables[key].items()
        for name in names
    }
    lines = stub.splitlines(keepends=True)
    inserts: list[tuple[int, str]] = []
    for node in ast.parse(stub).body:
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and (node.name, item.name) in wanted:
                static = wanted.pop((node.name, item.name))
                if item.end_lineno is None:
                    raise ValueError(f"{node.name}.{item.name}: no end line")
                inserts.append((item.end_lineno, _sibling(item, node.name, static)))
    if wanted:
        missing = ", ".join(f"{cls}.{name}" for cls, name in sorted(wanted))
        raise ValueError(f"not in the stub: {missing}")
    for line, text in sorted(inserts, reverse=True):
        lines.insert(line, text)
    return "".join(lines)


def main() -> None:
    async_py, stub_pyi = (Path(arg) for arg in sys.argv[1:3])
    stub_pyi.write_text(add_siblings(stub_pyi.read_text(), async_py.read_text()))


if __name__ == "__main__":
    main()
