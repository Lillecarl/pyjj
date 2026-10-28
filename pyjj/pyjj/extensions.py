"""User extensions: Python files that pick an identity or add workflows.

The config key `pyjj.extensions` lists the files, `~` expanded:

    [pyjj]
    extensions = ["~/.config/pyjj/identity.py"]

Each file is imported once per process. It registers what it offers
with `@identity` or by subclassing `Workflow`.

**Identity is decided when a repository loads.** jj_lib takes the
author, committer and signing key from the settings a repository was
loaded with, and ignores any passed later. So the hooks run between
the repo config layers and the load, and their answer becomes a
`--config` layer under the command line's own: an explicit `--config
user.email=...` still wins.

Repo config cannot name an extension a clone brought along: jj keeps
repo config outside the repository, behind `secure_config`'s id.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from pyjj_bindings import UserSettings, Workspace

    from .session import Repo


class ExtensionError(Exception):
    """An extension failed to load, or one of its hooks raised."""


@dataclass(frozen=True)
class Identity:
    """Who commits and signs. `None` leaves a field to the config."""

    name: str | None = None
    email: str | None = None
    signing_key: str | None = None
    signing_backend: str | None = None
    sign_behavior: str | None = None

    def config(self) -> dict[str, object]:
        keys = {
            "user.name": self.name,
            "user.email": self.email,
            "signing.key": self.signing_key,
            "signing.backend": self.signing_backend,
            "signing.behavior": self.sign_behavior,
        }
        return {key: value for key, value in keys.items() if value is not None}


class IdentityContext:
    """What an identity hook gets to decide from."""

    def __init__(self, settings: UserSettings, workspace: Workspace) -> None:
        self.settings = settings
        self._workspace = workspace

    @property
    def workspace_root(self) -> Path:
        return Path(self._workspace.workspace_root)

    @property
    def repo_path(self) -> Path:
        return Path(self._workspace.repo_path)

    @cached_property
    def remotes(self) -> dict[str, str]:
        """Git remote name to fetch URL. Empty for a non-git backend."""
        try:
            urls = self._workspace.load_at_head().git_remote_urls()
        except Exception:  # noqa: BLE001 -- no git backend
            return {}
        return {name: fetch for name, fetch, _push in urls}


IdentityHook = Callable[[IdentityContext], "Identity | Mapping[str, object] | None"]

_IDENTITY_HOOKS: list[IdentityHook] = []
_WORKFLOWS: dict[str, type[Workflow]] = {}
_LOADED: set[Path] = set()


def identity(hook: IdentityHook) -> IdentityHook:
    """Register `hook`. Usable as a decorator or on a lambda.

    Hooks run in registration order; the first that returns something
    other than `None` decides. It returns an `Identity`, or a mapping
    of config keys to values for anything `Identity` does not name.
    """
    _IDENTITY_HOOKS.append(hook)
    return hook


class Workflow:
    """A command of the user's own, run as `pyjj workflow NAME`.

    Subclassing registers it. `add_arguments` declares the arguments on
    an argparse parser, which is also what the shell completes: an
    argument whose metavar is one pyjj-cli knows (`REVSET`, `BOOKMARK`,
    `REMOTE`, ...) completes like pyjj's own, and one carrying a
    `completer` attribute completes with that.
    """

    name: ClassVar[str] = ""
    help: ClassVar[str | None] = None

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if cls.name:
            _WORKFLOWS[cls.name] = cls

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Declare this workflow's arguments."""

    def run(self, repo: Repo, args: argparse.Namespace) -> int | None:
        """Do the work. `None` means exit 0."""
        raise NotImplementedError

    def pyjj(self, repo: Repo, *argv: str) -> int:
        """Run a pyjj command in this process, against `repo`.

        `repo` answers from the state it loaded; call `repo.reload()`
        to see what the command wrote.
        """
        from pyjj_cli.__main__ import main

        return main(["-R", repo.root, *argv])


def workflows() -> dict[str, type[Workflow]]:
    return dict(sorted(_WORKFLOWS.items()))


def load(settings: UserSettings) -> None:
    """Import every file `pyjj.extensions` names that is not loaded yet."""
    for entry in settings.get_string_list("pyjj.extensions") or []:
        path = Path(entry).expanduser().resolve()
        if path in _LOADED:
            continue
        _LOADED.add(path)
        digest = hashlib.sha256(bytes(path)).hexdigest()[:12]
        module_name = f"pyjj_extension_{digest}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ExtensionError(f"cannot load extension {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            del sys.modules[module_name]
            raise ExtensionError(f"extension {path} failed to load: {e!r}") from e


def identity_config(settings: UserSettings, workspace: Workspace) -> list[tuple[str, str]]:
    """The `--config` pairs the identity hooks pick for `workspace`.

    Empty when no hook answers, so the caller can leave its settings
    untouched: a rebuild reseeds the change-id RNG.
    """
    load(settings)
    if not _IDENTITY_HOOKS:
        return []
    context = IdentityContext(settings, workspace)
    for hook in _IDENTITY_HOOKS:
        try:
            answer = hook(context)
        except Exception as e:
            name = getattr(hook, "__qualname__", repr(hook))
            raise ExtensionError(f"identity hook {name} failed: {e!r}") from e
        if answer is None:
            continue
        values = answer.config() if isinstance(answer, Identity) else dict(answer)
        return [("config", f"{key}={_toml(value)}") for key, value in values.items()]
    return []


def _toml(value: object) -> str:
    # A JSON string is a valid TOML basic string, and the leading quote
    # makes the binding parse it strictly instead of falling back.
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str | os.PathLike):
        return json.dumps(os.fspath(value))
    raise ExtensionError(f"identity value {value!r} is not a string, number or bool")
