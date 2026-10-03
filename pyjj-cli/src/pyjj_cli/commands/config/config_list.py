"""config subcommand: config_list."""
import os
import sys

import pyjj

from ..common import (
    CommandError,
    _compile_template,
    _pyjj_template,
    settings_for,
)
from .config_set import _scope


_BUILTINS = {
    # jj's own detailed list: the winning value with its source, and
    # the file when the source has one (env and default rows have none).
    "builtin_config_list_detailed":
        "{{name}} = {{value}} # {{source}}"
        "{% if path %} {{path}}{% endif %}",
}

_DEFAULT_TEMPLATE = "{% if overridden %}# {% endif %}{{name}} = {{value}}"


def config_list(args) -> int:
    """`jj config list [NAME]`: list what the config layers set.

    Every layer of the loaded settings reports its own entries, lowest
    precedence first, so shadowing is visible instead of guessed:
    without `--include-overridden` only each key's winning value
    prints; with it the shadowed values print too (jj marks those
    rows with `# `, which the default template reproduces).
    `--include-defaults` keeps the built-in default layers, which are
    otherwise left out. A scope flag keeps just that file's layer.
    """
    prefix = getattr(args, "name", None)
    include_defaults = bool(getattr(args, "include_defaults", False))
    include_overridden = bool(getattr(args, "include_overridden", False))
    try:
        settings = settings_for(args)
        layers = settings.config_layers()
    except (pyjj.JjError, CommandError, OSError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

    scope = _scope(args)
    if scope is not None:
        layers = [layer for layer in layers if layer.source == scope]
    if not include_defaults:
        layers = [layer for layer in layers if layer.source != "default"]

    # Per key, every layer's value in precedence order; the winner is
    # the last one standing.
    by_name: dict[str, list] = {}
    for layer in layers:
        for name in sorted(layer.entries):
            if prefix and not (name == prefix or name.startswith(prefix + ".")):
                continue
            by_name.setdefault(name, []).append(layer)

    template_str = getattr(args, "template", None)
    if template_str in _BUILTINS:
        template_str = _BUILTINS[template_str]
    if not template_str:
        template_str = (
            _pyjj_template(settings, "config_list", cwd=os.getcwd())
            or _DEFAULT_TEMPLATE
        )
    try:
        template = _compile_template(template_str)
    except Exception as e:
        print(f"Error: template compile failed: {e}", file=sys.stderr)
        return 1

    shown = 0
    for name in sorted(by_name):
        hits = by_name[name]
        rows = hits if include_overridden else hits[-1:]
        for index, layer in enumerate(rows):
            try:
                print(template.render(
                    name=name,
                    value=layer.entries[name],
                    overridden=index < len(rows) - 1,
                    source=layer.source,
                    path=layer.path or "",
                ))
            except Exception as e:
                print(f"Error: template render failed: {e}", file=sys.stderr)
                return 1
            shown += 1
    if not shown:
        print("Warning: No matching config variables found", file=sys.stderr)
    return 0
