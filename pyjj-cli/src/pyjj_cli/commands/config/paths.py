"""Where jj keeps its config files, and how to edit them in place.

Repo- and workspace-level config live *outside* the repository, under
`$XDG_CONFIG_HOME/jj/{repos,workspaces}/<id>/`. The id is a 20-hex name
jj stores in the repository, and the directory also holds a
`metadata.binpb` recording which repository it belongs to.

**Minting the id here is not enough.** A directory without that
metadata is one jj treats as absent, so config written that way was
invisible to `jj` -- and to pyjj itself once it started loading the
layer. `pyjj_bindings.secure_config_file` makes jj create the
directory, which is the only way the two tools agree on it.
"""
import os
import tomllib
from pathlib import Path

import pyjj_bindings


def config_home() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else Path.home() / ".config"


def config_path(workspace_root, scope: str, create: bool = False):
    """`scope` is "user", "repo" or "workspace".

    **Only a caller that will write passes `create`.** Minting the id
    writes the directory and its metadata but not the config file, and
    jj refuses a directory in that state outright ("Failed to determine
    the secure config for a repo"). `config unset` on a missing key
    resolved the path and then failed, which left exactly that.

    Without `create`, a scope that has never been written returns
    `None` rather than minting anything.
    """
    if scope == "user":
        return config_home() / "jj" / "config.toml"
    root = Path(workspace_root)
    found = pyjj_bindings.secure_config_file(
        str(root), str(root / ".jj" / "repo"), scope, create)
    if not found:
        return None
    path = Path(found)
    if create and not path.exists():
        # Minting the id writes the directory and its metadata; the
        # config file is the caller's to write. Leaving the pair
        # half-made is the state jj refuses outright, so the empty
        # file goes down with the rest of it.
        write_config(path, {})
    return path


def read_config(path) -> dict:
    """A scope that has never been written reads as empty, and
    `config_path` gives `None` for one."""
    if path is None or not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def write_config(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["#:schema https://docs.jj-vcs.dev/latest/config-schema.json", ""]
    lines += _dump(data, [])
    path.write_text("\n".join(lines).rstrip("\n") + "\n")


def set_key(data: dict, dotted: str, value) -> None:
    *tables, leaf = dotted.split(".")
    node = data
    for name in tables:
        node = node.setdefault(name, {})
        if not isinstance(node, dict):
            raise ValueError(f"{dotted} is not a table")
    node[leaf] = value


def unset_key(data: dict, dotted: str) -> bool:
    *tables, leaf = dotted.split(".")
    node = data
    for name in tables:
        node = node.get(name)
        if not isinstance(node, dict):
            return False
    return node.pop(leaf, _MISSING) is not _MISSING


_MISSING = object()


def _dump(data: dict, prefix: list) -> list:
    """A TOML rendering good enough for jj's config: scalars, strings,
    string lists and nested tables. jj re-parses it, so layout only has
    to be valid, not byte-identical to what jj itself writes."""
    lines = []
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in data.items() if isinstance(v, dict)}
    if scalars and prefix:
        lines.append("[" + ".".join(prefix) + "]")
    for key, value in scalars.items():
        lines.append(f"{key} = {_value(value)}")
    if scalars:
        lines.append("")
    for key, value in tables.items():
        nested = _dump(value, prefix + [key])
        if nested:
            lines += nested
        else:
            lines += ["[" + ".".join(prefix + [key]) + "]", ""]
    return lines


def _value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
