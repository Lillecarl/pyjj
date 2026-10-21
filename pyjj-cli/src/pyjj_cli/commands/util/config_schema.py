"""util subcommand: config-schema — the JSON schema for jj's config.

The file is `cli/src/config-schema.json` from the jj release pyjj pins,
which jj itself embeds and prints. A parity test compares it with the
pinned jj's output, so a stale copy fails there.
"""
import sys
from importlib.resources import files


def util_config_schema(args) -> int:
    sys.stdout.buffer.write(
        files("pyjj_cli").joinpath("data", "config-schema.json").read_bytes())
    return 0
