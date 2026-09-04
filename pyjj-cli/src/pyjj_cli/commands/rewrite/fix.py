"""pyjj-cli rewrite command: fix."""
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pyjj
import pyjj.hunk as hunk_mod
from ..common import (
    _start_transaction,
    CommandError,
    _checkout_if_moved,
    _finish,
    _load,
    _resolve_all,
    _resolve_in_arg_order,
    _resolve_one,
    _wc_commit,
    complete_newline,
    _run_editor,
    _changed_files,
    _run_diff_tool,
    _selection_is_empty,
    _fix_pattern_matches,
)

def fix(args) -> int:
    """`jj fix [-s REVSET] [--include-unchanged-files] [FILESETS]` — run formatters."""
    try:
        settings, ws, repo = _load(args)
        revset = getattr(args, "source", None)
        include_unchanged = bool(getattr(args, "include_unchanged", False))
        paths = getattr(args, "filesets", None) or None
        if paths == []:
            paths = None

        tx = _start_transaction(repo, settings)
        # Same as absorb: the source roots resolve inside the binding.
        files = tx.fix_enumerate(settings, revset=revset, paths=paths,
                                 include_unchanged_files=include_unchanged,
                                 check_immutable=True)
        if not files:
            # No files to fix — matches real jj's quiet no-op.
            return 0

        # Discover fix tools from config, sorted lexicographically like jj does.
        try:
            tool_names = sorted(settings.list_fix_tools())
        except AttributeError:
            # Fallback for old bindings without list_fix_tools.
            tool_names = []
        if not tool_names:
            # No tools configured — nothing to do.
            return 0

        # Build mapping of tool -> (command, patterns, enabled)
        tools = []
        for name in tool_names:
            enabled = settings.get_bool(f"fix.tools.{name}.enabled")
            if enabled is False:
                continue
            command = settings.get_string_list(f"fix.tools.{name}.command")
            if not command:
                continue
            patterns = settings.get_string_list(f"fix.tools.{name}.patterns") or []
            tools.append((name, command, patterns))

        if not tools:
            return 0

        workspace_root = ws.workspace_root
        fixes: dict[str, bytes] = {}
        for f in files:
            content = f.content
            cur = content
            for _name, command, patterns in tools:
                # Check if any pattern matches this file's path
                if patterns and not any(_fix_pattern_matches(p, f.path) for p in patterns):
                    continue
                # Substitute $path and $root in command args
                cmd = [arg.replace("$path", f.path).replace("$root", workspace_root) for arg in command]
                try:
                    proc = subprocess.run(cmd, input=cur, capture_output=True, check=False)
                except OSError as e:
                    raise CommandError(f"fix tool {_name} failed to start: {e}")
                if proc.returncode != 0:
                    raise CommandError(
                        f"fix tool {_name} exited with {proc.returncode}: "
                        f"{proc.stderr.decode(errors='replace')[:200]}"
                    )
                cur = proc.stdout
            if cur != content:
                fixes[f.key] = cur

        if not fixes:
            return 0

        summary = tx.fix_apply(settings, fixes, revset=revset, paths=paths, include_unchanged_files=include_unchanged)
        _finish(tx, f"fix {revset or 'reachable(@, mutable())'}", settings, ws, repo)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
