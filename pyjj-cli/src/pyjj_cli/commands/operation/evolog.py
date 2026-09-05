"""operation subcommand: evolog — how a change evolved across rewrites."""
import sys

import pyjj
from pyjj.graph_layout import reverse_graph

from ...formatter import Line, render_block, separate
from ..common import (
    CommandError,
    _commit_body_spans,
    _commit_glyph,
    _commit_header_spans,
    _commit_kind,
    _description_diff_bytes,
    _diff_files_bytes,
    _diff_formats_for_log,
    _format_timestamp,
    _immutable_ids,
    _is_empty,
    _load,
    _pyjj_template,
    _resolve_all,
    _resolve_template,
    _short_id,
    use_color,
)


def _operation_spans(operation):
    """jj's evolog operation line: `-- operation <id> <what it did>`."""
    first_line = (operation.description.splitlines()[0]
                  if operation.description else "")
    return separate([
        [("--", "separator")],
        [("operation", "")],
        [(operation.id[:12], "operation id short")],
        [(first_line, "operation description first_line")],
    ])


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

    # `jj evolog` compares a version with the one it was rewritten
    # from, not with its parent, so `--patch` asks for an interdiff.
    # The pair may name no format at all.
    formats = _diff_formats_for_log(args, getattr(args, "patch", False))
    with_diff = formats != (None, None)

    # jj takes the limit first and reverses what is left. Without the
    # graph that is the plain order; with it, each version's
    # predecessors become its successors, which is what `reverse_graph`
    # does.
    items = [(entry.commit.id.hex(),
              [(edge.target.hex(), edge.edge_type) for edge in entry.edges])
             for entry in entries]
    if getattr(args, "reversed", False):
        items = (list(reversed(items)) if no_graph
                 else reverse_graph(items))
    by_id = {entry.commit.id.hex(): entry for entry in entries}

    # `builtin_evolog_compact` means the same thing on both sides, so
    # pyjj-cli builds its spans itself rather than resolving it to a
    # Jinja string: a Jinja render carries no labels, and a label is
    # what decides a colour. The default below differs from jj on
    # purpose -- a name instead of an email, and a shorter stamp -- but
    # it is the same fields in the same order, so it shares the code.
    given = getattr(args, "template", None) or _pyjj_template(
        settings, "evolog", cwd=ws.workspace_root)
    builtin = given == "builtin_evolog_compact"
    jinja_template = (None if builtin or not given
                      else _resolve_template(settings, ws, args, "evolog"))

    # The graph is drawn by jj's own renderer, which takes a row's whole
    # text at once. Rows arrive in order and it is stateful, so every
    # row goes through it, including the ones a template renders.
    renderer = None if no_graph else pyjj.GraphRenderer()
    coloured = use_color(settings)
    # jj's `current_working_copy` asks about this workspace alone,
    # which is what makes a row bold and its glyph an `@`.
    current_wc = repo.view().get(ws.workspace_name)
    wc_hexes = {current_wc} if current_wc else set()
    immutable = _immutable_ids(repo, settings,
                               [entry.commit for entry in entries])
    sys.stdout.flush()
    for hex_id, edges in items:
        entry = by_id[hex_id]
        commit = entry.commit
        kind = _commit_kind(repo, commit, wc_hexes, immutable)
        operation = entry.operation

        def emit(lines) -> None:
            """One row, buffered: renderdag takes a finished string.

            The patch goes into the same buffer as the row, so the
            graph column runs down beside it, exactly as `log` does.
            """
            text = render_block(lines, "evolog", coloured)
            patch = "" if not with_diff else _patch_bytes(
                args, ws, settings, repo, entry, formats,
            ).decode("utf-8", "surrogateescape")
            if no_graph:
                _write(text + "\n" + patch)
                return
            glyph = render_block([[(_commit_glyph(kind), kind)]],
                                 "evolog commit node", coloured)
            # renderdag drops a trailing newline, so a row with a patch
            # under it reads the same as jj's own buffer.
            _write(renderer.next_row(hex_id, edges, glyph,
                                     f"{text}\n{patch}" if patch else text))

        if jinja_template is not None:
            try:
                rendered = jinja_template.render(
                    _context(repo, settings, commit, operation))
            except Exception as e:
                sys.stdout.buffer.flush()
                print(f"Error: template render failed: {e}", file=sys.stderr)
                return 1
            # A template is the whole entry, as it is for `log`.
            emit([[(line, "")] for line in rendered.splitlines() or [""]])
            continue

        if builtin:
            header = _commit_header_spans(repo, settings, commit, kw="commit")
        else:
            header = _commit_header_spans(
                repo, settings, commit, kw="commit",
                author=commit.author.name or commit.author.email or "",
                timestamp=_format_timestamp(commit.committer.timestamp,
                                            century=False))
        lines = [Line(header, kind),
                 Line(_commit_body_spans(repo, settings, commit,
                                         kw="commit"), kind)]
        if operation is not None:
            lines.append(Line(_operation_spans(operation)))
        emit(lines)
    sys.stdout.buffer.flush()
    return 0


def _write(text: str) -> None:
    """One piece of output, through the byte stream.

    A row can carry a patch, and file content need not be text, so the
    spans hold it decoded with `surrogateescape` and this puts it back.
    """
    sys.stdout.buffer.write(text.encode("utf-8", "surrogateescape"))


def _patch_bytes(args, ws, settings, repo, entry, formats) -> bytes:
    """What `jj evolog --patch` prints under one version.

    jj compares the version with the ones it was rewritten from, and
    rebases those onto its parents first so an unrelated change to the
    parents stays out of the diff. A squash gives a version more than
    one predecessor, and the first version has none: its description
    and its files then read as added.
    """
    predecessors = [repo.get_commit(pid) for pid in entry.predecessor_ids]
    # jj merges the predecessors' descriptions the way it merges their
    # trees: the descriptions as the sides, an empty string between
    # each pair as the base. One predecessor is the common case and
    # merges to itself; none leaves an empty description, so the whole
    # of this version's description reads as added. Two rarely resolve,
    # and the diff then starts from the conflict itself.
    descriptions = [p.description for p in predecessors]
    if not descriptions:
        before = ""
    elif len(descriptions) == 1:
        before = descriptions[0]
    else:
        before = repo.materialize_merge(
            [b""] * (len(descriptions) - 1),
            [d.encode("utf-8", "surrogateescape") for d in descriptions],
            settings,
        ).decode("utf-8", "surrogateescape")
    files = repo.interdiff_files(predecessors, entry.commit, settings, None)
    return (_description_diff_bytes(args, before, entry.commit.description,
                                    use_color(settings), formats)
            + _diff_files_bytes(args, ws, files, settings, formats))


def _context(repo, settings, commit, operation) -> dict:
    """What a user's own Jinja template can name."""
    change = _short_id(
        commit.change_id.reverse_hex(),
        repo.shortest_change_id_prefix_len(commit.change_id, settings),
    )
    hidden = commit.is_hidden(repo)
    if hidden:
        offset = commit.change_offset(repo)
        if offset is not None:
            change = f"{change}/{offset}"
    empty_marker = "(empty) " if _is_empty(repo, commit) else ""
    description = commit.description.splitlines()[0] if commit.description else ""
    return {
        "commit": commit,
        "change_id": commit.change_id.reverse_hex(),
        "change_id_short": change,
        "commit_id": commit.id.hex(),
        "commit_id_short": _short_id(
            commit.id.hex(),
            repo.shortest_commit_id_prefix_len(commit.id, settings)),
        "author": commit.author.name or commit.author.email or "",
        "author_name": commit.author.name or "",
        "author_email": commit.author.email or "",
        "datetime": _format_timestamp(commit.committer.timestamp,
                                      century=False),
        "datetime_full": _format_timestamp(commit.committer.timestamp),
        "description": description or "(no description set)",
        "description_full": commit.description.strip() or "(no description set)",
        "hidden": hidden,
        "hidden_marker": " (hidden)" if hidden else "",
        "empty": bool(empty_marker),
        "empty_marker": empty_marker,
        "operation_id": operation.id[:12] if operation is not None else "",
        "operation_description": (operation.description
                                  if operation is not None else ""),
    }
