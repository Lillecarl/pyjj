"""config subcommand: gc — drop config directories whose repo is gone.

Mirrors `cli/src/commands/config/gc.rs`. Repo-level config lives outside
the repository, so deleting a repository leaves its config behind. This
finds those leftovers and offers to remove them.

The metadata that records which repo a directory belongs to is a
protobuf, so reading it goes through the binding rather than being
decoded here -- see `pyjj-bindings/src/secure_config.rs`.
"""
import os
import sys
from pathlib import Path

import pyjj


def _missing_repo_configs(root: Path):
    """`(config_dir, repo_path)` for every directory whose repo is gone.

    Sorted by directory name, as jj sorts them.
    """
    if not root.exists():
        return []
    missing = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        repo_path = pyjj.repo_config_repo_path(str(entry))
        if repo_path is None:
            continue
        try:
            exists = Path(repo_path).exists()
        except OSError:
            # jj treats an unverifiable path as still present, rather
            # than proposing to delete a config it cannot check.
            exists = True
        if not exists:
            missing.append((entry, Path(repo_path)))
    return missing


def config_gc(args) -> int:
    root = pyjj.repo_configs_root_dir()
    if root is None:
        print("Error: No config directory found", file=sys.stderr)
        return 1

    try:
        missing = _missing_repo_configs(Path(root))
    except OSError as e:
        print(f"Error: Failed to read {root}: {e}", file=sys.stderr)
        return 1

    print("Missing repo configs (repo path no longer exists):")
    if not missing:
        print("  (none)")
        return 0
    for config_dir, repo_path in missing:
        print(f"  {config_dir}")
        print(f"    repo path: {repo_path}")

    answer = ""
    try:
        answer = input(
            f"Delete {len(missing)} missing repo config directories? (y/N) ")
    except EOFError:
        # No one to ask: take the default, which is to delete nothing.
        pass
    if answer.strip().lower() not in ("y", "yes"):
        print("Aborted; nothing was deleted.")
        return 0

    deleted = 0
    for config_dir, _repo_path in missing:
        try:
            pyjj.remove_repo_config_dir(str(config_dir))
        except pyjj.JjError as e:
            print(f"Warning: {getattr(e, 'message', e)}", file=sys.stderr)
        else:
            deleted += 1
    print(f"Deleted {deleted} config directories.")
    return 0
