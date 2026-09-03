"""Where jj keeps its config files, and how to edit them in place.

Repo- and workspace-level config live *outside* the repository, under
`$XDG_CONFIG_HOME/jj/{repos,workspaces}/<id>/config.toml`. The id is a
20-hex name jj stores in `.jj/repo/config-id` (or
`.jj/working_copy/config-id`), and it is created lazily -- a repository
that has never had config set has no such file yet.
"""
import os
import secrets
import tomllib
from pathlib import Path


def config_home() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else Path.home() / ".config"


def _scoped_path(workspace_root: Path, marker: Path, kind: str) -> Path:
    """The config file for one repo or workspace, minting its id if the
    repository has never had scoped config before."""
    if marker.exists():
        config_id = marker.read_text().strip()
    else:
        config_id = secrets.token_hex(10)
        marker.parent.mkdir(parents=True, exist_ok=True)
        # Exactly the 20 hex characters, no newline: jj rejects
        # anything else with "Found an invalid config ID".
        marker.write_text(config_id)
    return config_home() / "jj" / kind / config_id / "config.toml"


def config_path(workspace_root, scope: str) -> Path:
    """`scope` is "user", "repo" or "workspace"."""
    if scope == "user":
        return config_home() / "jj" / "config.toml"
    root = Path(workspace_root)
    if scope == "repo":
        return _scoped_path(root, root / ".jj" / "repo" / "config-id", "repos")
    return _scoped_path(root, root / ".jj" / "working_copy" / "config-id",
                        "workspaces")


def read_config(path: Path) -> dict:
    if not path.exists():
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
