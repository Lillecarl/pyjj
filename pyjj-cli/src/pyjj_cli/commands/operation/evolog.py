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
        entries = repo.evolution_log([c.id for c in commits], limit=limit)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1

    # jj's builtin name, mapped so `-T builtin_evolog_compact` works.
    builtins = {
        "builtin_evolog_compact":
            "{{ change_id_short }} {{ author }} {{ datetime }} {{ commit_id_short }}"
            "{{ hidden_marker }}\n{{ empty_marker }}{{ description }}"
            "{% if operation_id %}\n-- operation {{ operation_id }} "
            "{{ operation_description }}{% endif %}",
    }
    jinja_template = _resolve_template(settings, ws, args, "evolog", builtins)

    no_graph = getattr(args, "no_graph", False)
    wc_hexes = set(repo.view().values())
    for index, entry in enumerate(entries):
        commit = entry.commit
        last = index == len(entries) - 1
        if no_graph:
            glyph, gutter = "", ""
        else:
            glyph = "@" if commit.id.hex() in wc_hexes else "○"
            gutter = "   " if last else "│  "

        change = _short_id(
            commit.change_id.reverse_hex(),
            repo.shortest_change_id_prefix_len(commit.change_id, settings),
        )
        hidden = commit.is_hidden(repo)
        if hidden:
            # The offset is how a reader addresses this version: jj
            # resolves `<change id>/2` as a revset. Only a hidden
            # version carries one, since the visible one is at zero.
            offset = commit.change_offset(repo)
            if offset:
                change = f"{change}/{offset}"
        commit_id = _short_id(
            commit.id.hex(),
            repo.shortest_commit_id_prefix_len(commit.id, settings),
        )
        author = commit.author.name or commit.author.email or ""
        stamp = _format_timestamp(commit.committer.timestamp, century=False)
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
            # A template is the whole entry, as it is for `log`: the
            # first line sits beside the glyph, the rest under it.
            lines = rendered.splitlines() or [""]
            print(f"{glyph}  {lines[0]}" if glyph else lines[0])
            for extra in lines[1:]:
                print(f"{gutter}{extra}")
            continue

        row = f"{glyph}  {change}" if glyph else change
        row += f" {author} {stamp} {commit_id}"
        if hidden:
            row += " (hidden)"
        print(row)
        print(f"{gutter}{empty_marker}{description or '(no description set)'}")
        if operation is not None:
            print(f"{gutter}-- operation {operation.id[:12]} {operation.description}".rstrip())
    return 0
