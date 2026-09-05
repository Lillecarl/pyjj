"""history subcommand: log — backed by log_graph, drawn by jj's renderer.

The rows are labelled spans, so the palette decides the colours rather
than a table of one escape sequence per field. jj's colours compose
along the label stack -- a change id's prefix is one colour, and the
same field under the working copy is another, with the row bold -- and
a per-field table cannot say that.

pyjj-cli's own default row diverges from jj's on purpose: the author's
name instead of an email, and a timestamp without the century. It is
the same fields in the same shape otherwise, so `-T builtin_log_compact`
prints exactly what `jj log -T builtin_log_compact` prints.
"""
import datetime
import sys

import pyjj
from pyjj.graph_layout import reverse_graph

from ...formatter import Line, render_block, separate
from ..common import (
    _commit_body_spans,
    _commit_glyph,
    _commit_header_spans,
    _commit_kind,
    _commit_root_spans,
    _immutable_ids,
    _diff_base,
    _diff_bytes,
    _diff_formats_for_log,
    _load,
    _pyjj_template,
    _resolve_template,
    _short_id,
    _short_id_spans,
    use_color,
)

# jj's own builtin template names. `builtin_log_compact` builds its
# spans directly, because a Jinja render carries no labels and a label
# is what decides a colour. The other two still map to Jinja, so they
# print jj's fields in jj's order but without its colours.
_COMPACT = "builtin_log_compact"
_BUILTINS = {
    "builtin_log_compact_full_description":
        "{{ change_id_short }} {{ author_email }} {{ datetime_full }} "
        "{{ commit_id_short }}\n{{ description_full }}",
    "builtin_log_oneline": "{{ change_id_short }} {{ description }}",
}


# What `jj log --count` refuses to be combined with: every flag that
# shapes a row, and `--count` prints no rows.
_COUNT_CONFLICTS = (
    "--patch", "--summary", "--stat", "--name-only", "--types", "--git",
    "--color-words", "--context", "--ignore-all-space",
    "--ignore-space-change", "--no-graph", "--reversed", "--template",
)


def _write(text: str) -> None:
    """One piece of output, through the byte stream.

    A row can carry a patch, and file content need not be text, so the
    spans hold it decoded with `surrogateescape` and this puts it back.
    """
    sys.stdout.buffer.write(text.encode("utf-8", "surrogateescape"))


def _local(timestamp, fmt: str) -> str:
    """A timestamp in the zone it was stamped in."""
    tz = datetime.timezone(
        datetime.timedelta(minutes=timestamp.tz_offset_minutes))
    return datetime.datetime.fromtimestamp(
        timestamp.millis_since_epoch / 1000, tz=tz).strftime(fmt)


def _spans_millennia(nodes) -> bool:
    """Whether two rows sit in different millennia.

    The default row prints a two-digit year, which reads as `26` for
    2026. That is only ambiguous when the rows straddle a millennium,
    and the root commit does not count: its epoch stamp is synthetic
    and would force four digits forever.
    """
    years = [_local(node.commit.author.timestamp, "%Y") for node in nodes
             if node.commit.parent_ids]
    if not years:
        return False
    return (min(years)[:1]) != (max(years)[:1])


def log(args) -> int:
    try:
        settings, ws, repo = _load(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    revset_expr = (getattr(args, "revisions", None)
                   or settings.get_string("revsets.log") or "all()")

    limit = getattr(args, "limit", None)
    if limit == 0:
        limit = None

    if getattr(args, "count", False):
        # jj makes `--count` exclusive with everything that shapes the
        # rows, since it prints no rows at all. clap says so in one
        # attribute; argparse cannot, so the check lives here.
        conflicting = [name for name in _COUNT_CONFLICTS
                       if getattr(args, name.lstrip("-").replace("-", "_"),
                                  None) not in (None, False)]
        if conflicting:
            print(f"Error: --count cannot be used with {conflicting[0]}",
                  file=sys.stderr)
            return 2
        try:
            found = repo.revset(settings, revset_expr)
        except pyjj.JjError as e:
            print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
            return 1
        print(len(found) if limit is None else min(len(found), limit))
        return 0

    try:
        nodes = repo.log_graph(settings, revset_expr, limit=limit)
    except pyjj.JjError as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1

    view = repo.view()
    # jj's `current_working_copy` asks about this workspace alone, which
    # is what makes a row bold. Another workspace's commit is named in
    # the row instead, and only when there is more than one.
    current_wc = view.get(ws.workspace_name)
    wc_ids = {current_wc} if current_wc else set()
    all_wc_ids = set(view.values())
    names_by_hex = {hex_id: name for name, hex_id in view.items()}
    many_workspaces = len(view) > 1

    bookmarks_by_commit: dict[str, list[str]] = {}
    for bookmark in repo.bookmarks():
        for target in bookmark.target_ids:
            bookmarks_by_commit.setdefault(target.hex(), []).append(
                bookmark.name)
    immutable = _immutable_ids(repo, settings,
                              [node.commit for node in nodes])

    # `--reversed` walks the same DAG the other way: each commit's
    # parents become its children and the order flips, which is what
    # jj's own `reverse_graph` does. Reversing the drawn rows instead
    # would leave a merge's fork pointing the wrong way.
    by_id = {node.commit.id.hex(): node for node in nodes}
    items = [
        (node.commit.id.hex(),
         [(edge.target.hex(), edge.edge_type) for edge in node.edges])
        for node in nodes
    ]
    if getattr(args, "reversed", False):
        items = reverse_graph(items)

    no_graph = getattr(args, "no_graph", False)
    # `jj log` prints a row and nothing else unless a flag asks for a
    # diff, so this pair may name no format at all.
    formats = _diff_formats_for_log(args, getattr(args, "patch", False))
    with_diff = formats != (None, None)
    paths = getattr(args, "filesets", None) or None
    coloured = use_color(settings)

    given = (getattr(args, "template", None)
             or _pyjj_template(settings, "log", cwd=ws.workspace_root))
    builtin = given == _COMPACT
    jinja_template = (None if builtin or not given
                      else _resolve_template(settings, ws, args, "log",
                                             _BUILTINS))
    short_year = not _spans_millennia(nodes)

    renderer = None if no_graph else pyjj.GraphRenderer()
    sys.stdout.flush()
    for hex_id, edges in items:
        commit = by_id[hex_id].commit
        root = not commit.parent_ids
        kind = _commit_kind(repo, commit, wc_ids, immutable)
        names = sorted(bookmarks_by_commit.get(hex_id, []))

        def emit(lines, indent: bool = True) -> None:
            """One row, buffered: renderdag takes a finished string.

            jj writes the patch into the same buffer as the row, so the
            graph column runs down beside the diff. File content is
            bytes and need not be text, so the row goes out through
            `stdout.buffer` once it carries a diff.
            """
            text = render_block(lines, "log commit", coloured)
            patch = ""
            if with_diff:
                patch = _diff_bytes(
                    args, ws, settings, _diff_base(repo, settings, commit),
                    commit, paths, formats,
                ).decode("utf-8", "surrogateescape")
            if no_graph:
                head, _, rest = text.partition("\n")
                out = head + "\n"
                for line in rest.splitlines():
                    out += f"  {line}\n" if indent else f"{line}\n"
                _write(out + patch)
                return
            glyph = render_block([[(_commit_glyph(kind), kind)]],
                                 "log commit node", coloured)
            # renderdag drops a trailing newline, so the row reads the
            # same with a patch under it as jj's own buffer does.
            _write(renderer.next_row(hex_id, edges, glyph,
                                     f"{text}\n{patch}" if patch else text))

        if jinja_template is not None:
            try:
                rendered = jinja_template.render(_context(
                    repo, settings, commit, names, short_year,
                    hex_id in all_wc_ids, hex_id in wc_ids))
            except Exception as e:
                sys.stdout.buffer.flush()
                print(f"Error: template render failed: {e}", file=sys.stderr)
                return 1
            # A template is the whole row, exactly like `jj log -T`.
            emit([Line([(line, "")], kind)
                  for line in rendered.splitlines() or [""]])
        elif builtin:
            # jj names another workspace's working copy in the row, and
            # only when the repository has more than one.
            workspaces = ([f"{names_by_hex[hex_id]}@"]
                          if many_workspaces and hex_id in all_wc_ids else [])
            if root:
                emit([Line(_commit_root_spans(repo, settings, commit),
                           "immutable")], indent=False)
            else:
                emit([Line(_commit_header_spans(repo, settings, commit,
                                                bookmarks=names,
                                                working_copies=workspaces),
                           kind),
                      Line(_commit_body_spans(repo, settings, commit), kind)],
                     indent=False)
        else:
            # pyjj-cli names the workspace on any working-copy row,
            # whether or not the repository has a second one.
            own = names + ([f"{names_by_hex[hex_id]}@"]
                           if hex_id in all_wc_ids else [])
            emit(_default_lines(repo, settings, commit, kind, sorted(own),
                                root, short_year))

    sys.stdout.buffer.flush()
    return 0


def _default_lines(repo, settings, commit, kind, names, root: bool,
                   short_year: bool):
    """pyjj-cli's own row: the author's name, and a two-digit year.

    The fields are jj's, so the labels are jj's too and the palette
    colours them the same way. The order is this project's: the two ids
    together, then who and when.
    """
    change = _short_id_spans(
        commit.change_id.reverse_hex(),
        repo.shortest_change_id_prefix_len(commit.change_id, settings),
        "change_id")
    ids = _short_id_spans(
        commit.id.hex(),
        repo.shortest_commit_id_prefix_len(commit.id, settings),
        "commit_id")
    refs = [[(name, "bookmarks name")] for name in names]
    if root:
        # The root commit has no author and no timestamp worth
        # printing: the epoch reads as a 1970 commit nobody made.
        return [Line(separate([change, [("root()", "root")], ids, *refs]),
                     "immutable")]

    author = commit.author.name or commit.author.email or ""
    stamp = _local(commit.author.timestamp,
                   "%y-%m-%d %H:%M" if short_year else "%Y-%m-%d %H:%M")
    first_line = (commit.description.splitlines()[0]
                  if commit.description else "")
    return [
        Line(separate([change, ids, *refs, [(author, "author")],
                       [(stamp, "author timestamp local format")]]), kind),
        Line([(first_line, "description first_line")] if first_line
             else [("(no description set)", "description placeholder")],
             kind),
    ]


def _context(repo, settings, commit, names, short_year, is_wc: bool,
             is_current_wc: bool) -> dict:
    """What a user's own Jinja template can name.

    `templates set` validates against this set of names, so a name that
    goes away here breaks a template a user already saved. The
    `_display` names once carried escape sequences of their own; the
    formatter colours a row now, so they are the plain text.
    """
    change = _short_id(
        commit.change_id.reverse_hex(),
        repo.shortest_change_id_prefix_len(commit.change_id, settings))
    commit_id = _short_id(
        commit.id.hex(),
        repo.shortest_commit_id_prefix_len(commit.id, settings))
    first_line = (commit.description.splitlines()[0]
                  if commit.description else "")
    fmt = "%y-%m-%d %H:%M" if short_year else "%Y-%m-%d %H:%M"
    return {
        "commit": commit,
        "change_id": commit.change_id.reverse_hex(),
        "commit_id": commit.id.hex(),
        "change_id_short": change,
        "commit_id_short": commit_id,
        "change_id_short_raw": commit.change_id.reverse_hex()[:8],
        "commit_id_short_raw": commit.id.hex()[:8],
        "author": commit.author.name or commit.author.email or "",
        "author_name": commit.author.name or "",
        "author_email": commit.author.email or "",
        "author_display": commit.author.name or commit.author.email or "",
        "description": first_line or "(no description set)",
        "description_full": commit.description.strip() or "(no description set)",
        "description_display": first_line or "(no description set)",
        "bookmarks": names,
        "bookmarks_str": " ".join(names),
        "bookmarks_display": " ".join(names),
        "datetime": _local(commit.author.timestamp, fmt),
        "datetime_display": _local(commit.author.timestamp, fmt),
        "datetime_full": _local(commit.committer.timestamp,
                                "%Y-%m-%d %H:%M:%S"),
        "is_wc": is_wc,
        "is_current_wc": is_current_wc,
        "is_root": not commit.parent_ids,
    }
