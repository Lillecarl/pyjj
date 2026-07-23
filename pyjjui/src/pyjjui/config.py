"""Persisted "don't ask again ever" preferences for confirmation dialogs --
a small local JSON file, deliberately not a `jj` config value: this is
pyjjui-only UI preference, not something `jj` itself (or another jj
frontend) would ever read or care about.

`PYJJUI_CONFIG_DIR` overrides the directory for tests (and anyone who
wants it elsewhere); otherwise `$XDG_CONFIG_HOME/pyjjui` or
`~/.config/pyjjui`, matching the usual XDG convention on Linux.
"""

import json
import os
from pathlib import Path


def _config_dir() -> Path:
    override = os.environ.get("PYJJUI_CONFIG_DIR")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "pyjjui"


def _config_file() -> Path:
    return _config_dir() / "confirmations.json"


def load_skipped_confirmations() -> set[str]:
    """Action names (`"squash"`, `"rebase"`, etc.) with a persisted
    "don't ask again ever" -- an unreadable or missing file just means
    nothing's been skipped yet, not an error.
    """
    path = _config_file()
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return set()
    return {action for action, skipped in data.items() if skipped}


def persist_skip_confirmation(action: str) -> None:
    path = _config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, bool] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
    data[action] = True
    path.write_text(json.dumps(data, indent=2) + "\n")
