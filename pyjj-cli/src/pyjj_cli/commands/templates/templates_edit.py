"""templates subcommand: edit — sudoedit-style with .j2 temp file."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pyjj
from ..common import _load
from .templates_set import _validate_template


def templates_edit(args) -> int:
    try:
        settings, _, _ = _load(args)
    except pyjj.JjError as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1

    name = getattr(args, "name")
    is_repo = getattr(args, "repo", False)
    key = f"pyjj.templates.{name}"

    # Load current value for initial content
    current = None
    try:
        current = settings.get_string(key)
    except Exception:
        current = None
    if current is None:
        # Try jj config get
        result = subprocess.run(["jj", "config", "get", key], capture_output=True, text=True)
        if result.returncode == 0:
            current = result.stdout.strip()

    initial = current if current is not None else ""
    # Provide a helpful header comment for the user (like sudoedit)
    header = f"# Editing pyjj template '{name}' ({key})\n# Save and exit to apply, empty file to abort.\n# Allowed variables: change_id, commit_id, author, author_name, author_email, description, bookmarks, datetime, is_wc, ...\n\n"

    # Create temp file with .j2 suffix
    with tempfile.NamedTemporaryFile(mode="w", suffix=".j2", delete=False, prefix=f"pyjj-template-{name}-", encoding="utf-8") as tf:
        tf.write(header)
        tf.write(initial)
        tf_path = tf.name

    try:
        editor = os.environ.get("JJ_EDITOR") or os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
        # Use same herestring trick as _run_editor: split editor into args
        import shlex

        editor_args = shlex.split(editor)
        editor_args.append(tf_path)
        result = subprocess.run(editor_args)
        if result.returncode != 0:
            print(f"Editor exited with {result.returncode}, aborting", file=sys.stderr)
            return result.returncode

        new_content = Path(tf_path).read_text(encoding="utf-8")
        # Strip our header comments
        lines = [l for l in new_content.splitlines() if not l.startswith("#")]
        new_value = "\n".join(lines).strip()
        # Also strip trailing newline handling: if original had no trailing newline, keep as is

        if not new_value:
            print("Empty template, aborting (use `pyjj templates unset` to delete)", file=sys.stderr)
            return 1

        if new_value == (current or ""):
            print("No changes, aborting", file=sys.stderr)
            return 0

        ok, msg = _validate_template(new_value)
        if not ok:
            print(f"Error: template validation failed: {msg}", file=sys.stderr)
            print(f"Template left in {tf_path} for inspection", file=sys.stderr)
            return 1

        scope = "--repo" if is_repo else "--user"
        toml_value = "'''" + new_value.replace("'''", "\\'\\'\\'") + "'''"
        result = subprocess.run(["jj", "config", "set", scope, key, toml_value], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error: {result.stderr}", file=sys.stderr)
            return result.returncode
        print(f"Updated {key}")
        return 0
    finally:
        try:
            Path(tf_path).unlink(missing_ok=True)
        except Exception:
            pass
