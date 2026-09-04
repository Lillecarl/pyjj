"""operation subcommand: op_log."""
import sys

import pyjj
from pyjj.graph_layout import lane_prefixes, layout_keyed

from ..common import CommandError, _ago, _duration, _load, _resolve_template

# jj's own builtin template names, mapped to a Jinja equivalent so
# `pyjj op log -T builtin_op_log_oneline` keeps working like `jj` does.
# The root operation has no user, no time and nothing it did, so jj's
# builtins send it to a one-line form of its own rather than printing a
# blank description under it. Each of these ends with a newline, the
# way jj's do, so `builtin_op_log_comfortable` really does leave a blank
# line between operations.
_COMPACT = ("{% if is_root %}{{ header }}\n"
            "{% else %}{{ header }}\n{{ description }}\n"
            "{% if attributes %}{{ attributes }}\n{% endif %}{% endif %}")
_BUILTINS = {
    "builtin_op_log_compact": _COMPACT,
    "builtin_op_log_comfortable": _COMPACT + "\n",
    "builtin_op_log_oneline":
        "{% if is_root %}{{ header }}\n"
        "{% else %}{{ header }} {{ description }}"
        "{% if attributes %} {{ attributes }}{% endif %}\n{% endif %}",
}


def _header(op, root: bool) -> str:
    """The first line of an operation, jj's `format_operation` shape.

    jj joins the parts with `separate(" ", ...)`, which drops the empty
    ones -- an operation that belongs to no workspace prints no
    workspace column rather than a double space.
    """
    id_short = op.id[:12]
    if root:
        return f"{id_short} root()"
    workspace = f"{op.workspace_name}@" if op.workspace_name else ""
    time = (f"{_ago(op.end_time.millis_since_epoch)}, lasted "
            f"{_duration(op.start_time.millis_since_epoch, op.end_time.millis_since_epoch)}")
    parts = (id_short, f"{op.username}@{op.hostname}", workspace, time)
    return " ".join(part for part in parts if part)


def op_log(args) -> int:
    """`jj op log` — the repository's own history of transactions."""
    try:
        settings, ws, repo = _load(args)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

    ops = repo.operation_log()
    limit = getattr(args, "limit", None)
    # jj applies the limit after the topological ordering but before
    # reversing, so `--reversed -n 3` shows the three newest operations
    # oldest first -- not the three oldest.
    if limit:
        ops = ops[:limit]

    rows = layout_keyed(
        [(op.id, [(parent, "direct") for parent in op.parent_ids]) for op in ops]
    )
    current_id = repo.operation.id
    template = _resolve_template(settings, ws, args, "op_log", _BUILTINS)
    no_graph = getattr(args, "no_graph", False)
    reversed_order = getattr(args, "reversed", False)

    blocks = []
    for op, row in zip(ops, rows):
        root = not op.parent_ids
        current = op.id == current_id
        attributes = "\n".join(f"{key}: {value}" for key, value in op.attributes)
        if template is not None:
            rendered = template.render({
                "operation": op,
                "id": op.id,
                "id_short": op.id[:12],
                "header": _header(op, root),
                "user": f"{op.username}@{op.hostname}",
                "username": op.username,
                "hostname": op.hostname,
                "workspace_name": op.workspace_name,
                "time_ago": _ago(op.end_time.millis_since_epoch),
                "duration": _duration(op.start_time.millis_since_epoch,
                                      op.end_time.millis_since_epoch),
                "description": op.description.splitlines()[0] if op.description else "",
                "description_full": op.description,
                "attributes": attributes,
                "is_current": current,
                "is_root": root,
            })
            # A template's own trailing newline ends its last line
            # rather than starting an empty one; anything past that is a
            # blank line the template asked for.
            lines = rendered.split("\n")
            if lines and lines[-1] == "":
                lines.pop()
            body = lines or [""]
        elif root:
            # The root operation has no user, no time and nothing it
            # did. jj gives it a single line saying just that.
            body = [_header(op, root)]
        else:
            first_line = op.description.splitlines()[0] if op.description else ""
            body = [_header(op, root), first_line]
            body.extend(attributes.splitlines())
        blocks.append((row, current, body))

    if reversed_order:
        blocks = list(reversed(blocks))

    for index, (row, current, body) in enumerate(blocks):
        if no_graph:
            for line in body:
                print(line)
            continue
        header, cont = lane_prefixes(row, "@" if current else "○")
        if reversed_order:
            # Reversed, the line below a row leads to the row displayed
            # after it, which is that row's child rather than its
            # parent. The newest operation is displayed last and has no
            # child, so nothing continues below it.
            cont = "   " if index == len(blocks) - 1 else "│  "
        print(f"{header}{body[0]}")
        for line in body[1:]:
            print(f"{cont}{line}")
    return 0
