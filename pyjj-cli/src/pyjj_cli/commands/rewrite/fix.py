"""pyjj-cli rewrite command: fix."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pyjj

from ..common import (
    CommandError,
    _finish,
    _fix_pattern_matches,
    _ignore_immutable,
    command,
    write_tx,
)

if TYPE_CHECKING:
    import argparse

@command
def fix(args: argparse.Namespace) -> int:
    """`jj fix [-s REVSET] [--include-unchanged-files] [FILESETS]` — run formatters."""
    with write_tx(args) as (settings, ws, repo, tx):
        revset = getattr(args, "source", None)
        include_unchanged = bool(getattr(args, "include_unchanged", False))
        paths = getattr(args, "filesets", None) or None
        if paths == []:
            paths = None

        # Same as absorb: the source roots resolve inside the binding.
        files = tx.fix_enumerate(settings, revset=revset, paths=paths,
                                 include_unchanged_files=include_unchanged,
                                 check_immutable=not _ignore_immutable())
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

        # Build mapping of tool -> (command, patterns, line-range-arg,
        # run-if-zero). A tool with a line-range-arg gets the changed
        # line ranges as extra arguments ($first/$last, 1-based
        # inclusive, one substituted argument per range) -- or the whole
        # file as one range under -a, which is what makes -a observable
        # at all: a tool without one always sees the whole file either
        # way, exactly as in real jj.
        tools = []
        for name in tool_names:
            enabled = settings.get_bool(f"fix.tools.{name}.enabled")
            if enabled is False:
                continue
            command = settings.get_string_list(f"fix.tools.{name}.command")
            if not command:
                continue
            patterns = settings.get_string_list(f"fix.tools.{name}.patterns") or []
            line_range_arg = settings.get_string(f"fix.tools.{name}.line-range-arg")
            run_if_zero = settings.get_bool(
                f"fix.tools.{name}.run-tool-if-zero-line-ranges")
            if run_if_zero and line_range_arg is None:
                raise CommandError(
                    "run-tool-if-zero-line-ranges can only be set when "
                    "line-range-arg is set")
            tools.append((name, command, patterns, line_range_arg,
                          bool(run_if_zero)))

        if not tools:
            return 0

        workspace_root = ws.workspace_root
        all_lines = bool(getattr(args, "all_lines", False))
        fixes: dict[str, bytes] = {}
        for f in files:
            content = f.content
            cur = content
            for _name, command, patterns, line_range_arg, run_if_zero in tools:
                # Check if any pattern matches this file's path
                if patterns and not any(_fix_pattern_matches(p, f.path) for p in patterns):
                    continue
                extra_args: list[str] = []
                if line_range_arg is not None:
                    # Ranges are computed against the tool chain's running
                    # output, not the original content -- each tool sees
                    # what the previous one left, same as real jj's fold.
                    # -a passes no base, which reads as the whole file.
                    base = None if all_lines else f.base_content
                    ranges = pyjj.changed_line_ranges(base, cur)
                    if not ranges and not run_if_zero:
                        continue
                    extra_args = [
                        line_range_arg.replace("$first", str(first)).replace(
                            "$last", str(last))
                        for first, last in ranges
                    ]
                # Substitute $path and $root in command args
                cmd = [arg.replace("$path", f.path).replace("$root", workspace_root) for arg in command]
                cmd = cmd + extra_args
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

        tx.fix_apply(settings, fixes, revset=revset, paths=paths, include_unchanged_files=include_unchanged)
        _finish(tx, f"fix {revset or 'reachable(@, mutable())'}", settings, ws, repo)
        return 0
        return 0
