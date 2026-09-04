"""operation subcommand: evolog — how a change evolved across rewrites."""
import sys

import pyjj

from ..common import (
    CommandError,
    _format_timestamp,
    _is_empty,
    _load,
    _resolve_all,
    _resolve_template,
    _short_id,
)


def evolog(args) -> int:
    try:
        settings, ws, repo = _load(args)
        revisions = getattr(args, "revisions", None) or ["@"]
        if isinstance(revisions, str):
            revisions = [revisions]
        commits = _resolve_all(repo, settings, revisions)
        if not commits:
            print("No revisions to show")
            return 0

        limit = getattr(args, "limit", None)
        if limit == 0:
            limit = None
        no_graph = getattr(args, "no_graph", False)
        # A squash gives a commit two predecessors, so an evolution log
        # is a graph. jj groups the rows before drawing them and takes
        # the limit afterwards; without the graph it keeps the raw walk
        # order instead.
        start = [c.id for c in commits]
        entries = (
            repo.evolution_log(start, limit=limit)
            if no_graph
            else repo.evolution_graph(start, limit=limit)
        )
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

    # jj's builtin name, mapped so `-T builtin_evolog_compact` renders
    # what jj renders: `builtin_log_compact(commit)` -- the change id
    # with its offset, the author's email, a full timestamp, the commit
    # id and the markers -- and then the operation line. The default
    # template below differs from jj on purpose; this one may not.
    builtins = {
        "builtin_evolog_compact":
            "{{ change_id_short }} {{ author_email }} {{ datetime_full }} "
            "{{ commit_id_short }}{{ hidden_marker }}"
            "\n{{ empty_marker }}{{ description }}"
            "{% if operation_id %}\n-- operation {{ operation_id }} "
            "{{ operation_description }}{% endif %}",
    }
    jinja_template = _resolve_template(settings, ws, args, "evolog", builtins)

    # The graph is drawn by jj's own renderer, which takes a row's whole
    # text at once. Rows arrive in order and it is stateful, so every
    # row goes through it, including the ones a template renders.
    renderer = None if no_graph else pyjj.GraphRenderer()
    wc_hexes = set(repo.view().values())
    for entry in entries:
        commit = entry.commit
        hex_id = commit.id.hex()
        glyph = "@" if hex_id in wc_hexes else "○"
        edges = [(edge.target.hex(), edge.edge_type) for edge in entry.edges]

        def emit(lines) -> None:
            if no_graph:
                for line in lines:
                    print(line)
                return
            sys.stdout.write(
                renderer.next_row(hex_id, edges, glyph, "\n".join(lines)))

        change = _short_id(
            commit.change_id.reverse_hex(),
            repo.shortest_change_id_prefix_len(commit.change_id, settings),
        )
        hidden = commit.is_hidden(repo)
        if hidden:
            # The offset is how a reader addresses this version: jj
            # resolves `<change id>/2` as a revset. Only a hidden
            # version carries one, since the visible one is at zero --
            # and jj prints a zero offset too, on a change whose only
            # versions are hidden.
            offset = commit.change_offset(repo)
            if offset is not None:
                change = f"{change}/{offset}"
        commit_id = _short_id(
            commit.id.hex(),
            repo.shortest_commit_id_prefix_len(commit.id, settings),
        )
        author = commit.author.name or commit.author.email or ""
        stamp = _format_timestamp(commit.committer.timestamp, century=False)
        stamp_full = _format_timestamp(commit.committer.timestamp)
        description = commit.description.splitlines()[0] if commit.description else ""
        empty_marker = "(empty) " if _is_empty(repo, commit) else ""
        operation = entry.operation

        if jinja_template is not None:
            context = {
                "commit": commit,
                "change_id": commit.change_id.reverse_hex(),
                "change_id_short": change,
                "commit_id": commit.id.hex(),
                "commit_id_short": commit_id,
                "author": author,
                "author_name": commit.author.name or "",
                "author_email": commit.author.email or "",
                "datetime": stamp,
                "datetime_full": stamp_full,
                "description": description or "(no description set)",
                "description_full": commit.description.strip() or "(no description set)",
                "hidden": hidden,
                "hidden_marker": " (hidden)" if hidden else "",
                "empty": bool(empty_marker),
                "empty_marker": empty_marker,
                "operation_id": operation.id[:12] if operation is not None else "",
                "operation_description": operation.description if operation is not None else "",
            }
            try:
                rendered = jinja_template.render(context)
            except Exception as e:
                print(f"Error: template render failed: {e}", file=sys.stderr)
                return 1
            # A template is the whole entry, as it is for `log`.
            emit(rendered.splitlines() or [""])
            continue

        lines = [f"{change} {author} {stamp} {commit_id}"
                 + (" (hidden)" if hidden else "")]
        lines.append(f"{empty_marker}{description or '(no description set)'}")
        if operation is not None:
            lines.append(
                f"-- operation {operation.id[:12]} {operation.description}".rstrip())
        emit(lines)
    return 0
