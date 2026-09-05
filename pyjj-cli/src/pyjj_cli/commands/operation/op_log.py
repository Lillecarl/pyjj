"""operation subcommand: op_log."""
import sys

import pyjj
from pyjj.graph_layout import reverse_graph

from ...formatter import render_block, separate
from ..common import (
    CommandError,
    _ago,
    _diff_formats_for_log,
    _duration,
    _load,
    _pyjj_template,
    _resolve_template,
    use_color,
)
from .op_diff import print_operation_diff

# jj's own builtin template names. These carry labels, and a label
# decides a colour, so pyjj-cli builds their spans itself rather than
# resolving them to a Jinja string. `comfortable` is `compact` plus a
# blank line, which is one empty line at the end of the block.
_SHAPES = {
    "builtin_op_log_compact": "compact",
    "builtin_op_log_comfortable": "comfortable",
    "builtin_op_log_oneline": "oneline",
}


def _shape(settings, ws, args, name: str):
    """Either one of jj's builtin shapes, or a Jinja template.

    A builtin name wins over the Jinja path wherever it appears, on the
    command line or under `pyjj.templates.<name>`. With neither, the
    default is what jj's own default is: `builtin_op_log_compact`.
    """
    given = getattr(args, "template", None)
    if not given:
        given = _pyjj_template(settings, name, cwd=ws.workspace_root)
        if not given:
            return "compact", None
    if given in _SHAPES:
        return _SHAPES[given], None
    return None, _resolve_template(settings, ws, args, name)


def _fields(op) -> list[tuple[str, tuple[str, ...]]]:
    """The header fields of an operation, jj's `format_operation` shape.

    jj joins these with `separate(" ", ...)`, which drops the empty
    ones -- an operation that belongs to no workspace prints no
    workspace column rather than a double space. Each field carries the
    label its own colour rule names.
    """
    parts: list[list[tuple[str, tuple[str, ...]]]] = [
        [(op.id[:12], ("id", "short"))],
        [(f"{op.username}@{op.hostname}", ("user",))],
    ]
    if op.workspace_name:
        parts.append([(f"{op.workspace_name}@", ("workspace_name",))])
    parts.append([
        (_ago(op.end_time.millis_since_epoch), ("time", "end", "ago")),
        (", lasted ", ("time",)),
        (_duration(op.start_time.millis_since_epoch,
                   op.end_time.millis_since_epoch), ("time", "duration")),
    ])
    return separate(parts)


def _op_lines(op, shape: str) -> list[list[tuple[str, tuple[str, ...]]]]:
    """One operation's lines, as labelled spans, without the graph."""
    if not op.parent_ids:
        # The root operation has no user, no time and nothing it did.
        # jj gives it a single line saying just that.
        return [[(op.id[:12], ("id", "short")), (" ", ()),
                 ("root()", ("root",))]]
    first_line = op.description.splitlines()[0] if op.description else ""
    description = [[(first_line, ("description", "first_line"))]]
    attributes = [[(f"{key}: {value}", ("attributes",))]
                  for key, value in op.attributes]
    if shape == "oneline":
        return [separate([_fields(op), *description, *attributes])]
    lines = [_fields(op), *description, *attributes]
    if shape == "comfortable":
        lines.append([])
    return lines


def _jinja_lines(op, current: bool, template):
    """A user template's output, as one unlabelled span per line."""
    attributes = "\n".join(f"{key}: {value}" for key, value in op.attributes)
    root = not op.parent_ids
    rendered = template.render({
        "operation": op,
        "id": op.id,
        "id_short": op.id[:12],
        "header": "".join(text for text, _labels in (
            [(op.id[:12], ()), (" ", ()), ("root()", ())] if root
            else _fields(op))),
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
    # A template's own trailing newline ends its last line rather than
    # starting an empty one; anything past that is a blank line the
    # template asked for.
    lines = rendered.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [[(line, ())] for line in lines or [""]]


def render_operation(op, current: bool, shape, template, prefix: str,
                     coloured: bool) -> str:
    """One operation's block, ready to print or to hand to the graph.

    `prefix` is the command's own label -- `op_log` or `op_show` -- and
    it heads every span, the way jj's `template.labeled([...])` does.
    The block has no trailing newline; the caller supplies it.
    """
    base = (prefix, "operation")
    if current:
        base += ("current_operation",)
    if template is not None:
        lines = _jinja_lines(op, current, template)
    else:
        lines = _op_lines(op, shape)
    return render_block(lines, base, coloured)


def render_node(current: bool, prefix: str, coloured: bool) -> str:
    """The graph glyph of an operation, jj's `op_log_node` template.

    The glyph is its own render: jj labels it `node` under the command,
    and the label sits before `current_operation` rather than after it,
    so the two stacks pick different rules.
    """
    if current:
        line = [("@", ("current_operation",))]
    else:
        line = [("○", ())]
    return render_block([line], (prefix, "operation", "node"), coloured)


def _op_diff_text(args, settings, ws, repo, op) -> str:
    """One operation's own diff, as the text that sits under its row.

    `jj op log --op-diff` shows what each operation changed, compared
    with its parents -- the same body `op show` prints. `--patch` asks
    for it too, and adds the diff of every changed commit.
    """
    import io

    buffer = io.StringIO()
    print_operation_diff(args, settings, ws, repo, op.parents(), op,
                         heading=False, prefix="op_log", out=buffer)
    return buffer.getvalue()


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

    current_id = repo.operation.id
    shape, template = _shape(settings, ws, args, "op_log")
    coloured = use_color(settings)
    by_id = {op.id: op for op in ops}
    items = [(op.id, [(parent, "direct") for parent in op.parent_ids])
             for op in ops]
    if getattr(args, "reversed", False):
        items = reverse_graph(items)

    # `--op-diff` shows what each operation changed, and `--patch`
    # implies it -- so does any other diff-format flag, since a format
    # with nothing to format would print nothing at all.
    formats = _diff_formats_for_log(args, getattr(args, "patch", False))
    with_diff = getattr(args, "op_diff", False) or formats != (None, None)

    def body(op_id: str) -> str:
        if not with_diff:
            return ""
        return _op_diff_text(args, settings, ws, repo, by_id[op_id])

    if getattr(args, "no_graph", False):
        for op_id, _edges in items:
            sys.stdout.write(render_operation(
                by_id[op_id], op_id == current_id, shape, template,
                "op_log", coloured) + "\n")
            sys.stdout.write(body(op_id))
        return 0

    renderer = pyjj.GraphRenderer()
    for op_id, edges in items:
        # An edge to an operation outside the set is not drawn: under
        # `--limit` the oldest row shown still has a parent, and jj
        # leaves its lane running rather than closing it.
        current = op_id == current_id
        text = render_operation(by_id[op_id], current, shape, template,
                                "op_log", coloured)
        patch = body(op_id)
        sys.stdout.write(renderer.next_row(
            op_id, edges, render_node(current, "op_log", coloured),
            f"{text}\n{patch}" if patch else text))
    return 0
