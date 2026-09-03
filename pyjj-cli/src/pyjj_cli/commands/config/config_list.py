"""config subcommand: config_list."""
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

import pyjj
import pyjj.hunk as hunk_mod
from ..common import (
    CommandError,
    _checkout_if_moved,
    _finish,
    _load,
    _resolve_all,
    _resolve_in_arg_order,
    _resolve_one,
    _restore_view_command,
    _wc_commit,
    complete_newline,
    join_message_paragraphs,
    _run_editor,
    _changed_files,
    _run_diff_tool,
    _selection_is_empty,
    _merge_marker_len,
    _run_merge_tool,
    _fix_pattern_matches,
)

def config_list(args) -> int:
    try:
        settings = pyjj.UserSettings()
        # For now, just show a few known keys if prefix is given, else nothing
        # We don't have a way to list all config keys via bindings, so we just
        # try to get the requested prefix as a string and list if it's set
        prefix = getattr(args, "name", None)
        if prefix:
            val = settings.get_string(prefix)
            if val is not None:
                print(f'{prefix} = "{val}"')
            else:
                # Try as table? We don't have table listing, so just print nothing
                pass
        else:
            # No prefix: list is not yet supported to enumerate all
            print("Error: config list without prefix not yet supported", file=sys.stderr)
            return 2
        return 0
    except pyjj.JjError as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
