"""history subcommand: log — now backed by log_graph + shared graph_layout."""
import os
import sys

import pyjj
from pyjj.graph_layout import layout

from ..common import _load

# ANSI for prefix highlight — matches jj's "unique prefix in bold" idea.
# Only emitted when stdout is a TTY and NO_COLOR is not set.
_BLUE_BOLD = "\033[1;34m"
_CYAN_BOLD = "\033[1;36m"
_RESET = "\033[0m"


def _use_color() -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("FORCE_COLOR") is not None:
        return True
    return sys.stdout.isatty()


def _color_prefix(hex_str: str, prefix_len: int, color: str) -> str:
    """Color the shortest-unique prefix of a hex id."""
    if prefix_len <= 0 or prefix_len > len(hex_str):
        prefix_len = len(hex_str)
    # jj highlights the *shortest* unique prefix; we show 8 chars, highlight first N.
    # If prefix > 8, the whole 8 is highlighted (still unique within 8).
    shown = hex_str[:8]
    hl = min(prefix_len, len(shown))
    if hl == len(shown):
        return f"{color}{shown}{_RESET}"
    return f"{color}{shown[:hl]}{_RESET}{shown[hl:]}"


def _render_glyphs_plain(row) -> str:
    """Plain-text version of pyjjui.widgets.log_view._render_glyphs."""
    lanes = {row.column}
    for edge in row.edges:
        lanes.add(edge.from_column)
        lanes.add(edge.to_column)
    width = max(lanes) + 1 if lanes else 1
    chars = [" "] * width
    for edge in row.edges:
        lo, hi = sorted((edge.from_column, edge.to_column))
        if lo == hi:
            chars[lo] = "│"
            continue
        for col in range(lo + 1, hi):
            chars[col] = "─"
        if edge.from_column == row.column:
            chars[edge.to_column] = "╮" if edge.to_column > edge.from_column else "╭"
        else:
            chars[edge.from_column] = "╯" if edge.from_column > edge.to_column else "╰"
    # glyph for this row's own commit — will be overwritten below with @/○/◆
    return "".join(chars)


def log(args) -> int:
    try:
        settings, ws, repo = _load(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    revset_expr = getattr(args, "revisions", None)
    # Fall back to revsets.log from config (pyjjui does same), else show all
    if not revset_expr:
        revset_expr = settings.get_string("revsets.log")
    if not revset_expr:
        revset_expr = "all()"

    limit = getattr(args, "limit", None)
    # pyjj's log -n default is 10 via Flag.LIMIT; 0 means unlimited?
    # Pass through as-is; log_graph handles None as no limit.
    # If limit is 0, treat as None (show all) to match jj.
    if limit == 0:
        limit = None

    try:
        nodes = repo.log_graph(settings, revset_expr, limit=limit)
    except pyjj.JjError as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1

    # Working-copy commit id for glyph choice
    try:
        view = repo.view()
        wc_hex = view.get(ws.workspace_name)
        wc_id = pyjj.CommitId(wc_hex) if wc_hex else None
    except Exception:
        wc_id = None

    # Bookmarks for summary
    try:
        bookmarks = repo.bookmarks()
        bm_by_commit: dict[str, list[str]] = {}
        for bm in bookmarks:
            for tid in bm.target_ids:
                # target_ids are CommitId objects; hex for key
                key = tid.hex() if hasattr(tid, "hex") else str(tid)
                bm_by_commit.setdefault(key, []).append(bm.name)
    except Exception:
        bm_by_commit = {}

    rows = layout(nodes)

    no_graph = getattr(args, "no_graph", False)
    show_patch = getattr(args, "patch", False)

    for row in rows:
        commit = row.node.commit
        is_wc = wc_id is not None and commit.id == wc_id
        is_root = not commit.parent_ids  # root() has no parents
        glyph = "@" if is_wc else ("◆" if is_root else "○")

        # Graph prefix for first row (commit line)
        if no_graph:
            graph_prefix = ""
            cont_prefix = ""
        else:
            glyphs = _render_glyphs_plain(row)
            chars = list(glyphs)
            if row.column >= len(chars):
                chars.extend([" "] * (row.column - len(chars) + 1))
            chars[row.column] = glyph
            graph_prefix = "".join(chars) + " "
            # Second row (description) — vertical continuation of lanes
            # Use │ for the commit's own lane and for any other active lane.
            cont_chars = []
            for i in range(row.width):
                if i == row.column:
                    cont_chars.append("│")
                elif i < len(glyphs) and glyphs[i] != " ":
                    cont_chars.append("│")
                else:
                    # Keep lane if it was active (had an edge) — check row.edges
                    active = any(e.from_column == i or e.to_column == i for e in row.edges)
                    cont_chars.append("│" if active else " ")
            # Trim trailing spaces but keep at least column+1 width for alignment
            while cont_chars and cont_chars[-1] == " " and len(cont_chars) > row.column + 1:
                cont_chars.pop()
            cont_prefix = "".join(cont_chars) + " "

        # IDs with shortest-prefix highlight
        use_color = _use_color()
        if use_color:
            try:
                c_len = repo.shortest_change_id_prefix_len(commit.change_id)
            except Exception:
                c_len = 8
            try:
                k_len = repo.shortest_commit_id_prefix_len(commit.id)
            except Exception:
                k_len = 8
            change_disp = _color_prefix(commit.change_id.hex(), c_len, _CYAN_BOLD)
            commit_disp = _color_prefix(commit.id.hex(), k_len, _BLUE_BOLD)
        else:
            change_disp = commit.change_id.hex()[:8]
            commit_disp = commit.id.hex()[:8]

        bm_names = bm_by_commit.get(commit.id.hex(), [])
        bm_str = (" " + " ".join(sorted(bm_names))) if bm_names else ""

        # Author + datetime without year (MM-DD HH:MM), like jj but without the 2k year
        try:
            author = commit.author.name or commit.author.email
        except Exception:
            author = ""
        try:
            ts = commit.author.timestamp if hasattr(commit.author, "timestamp") else commit.committer.timestamp
            # millis_since_epoch + tz_offset_minutes
            import datetime

            millis = ts.millis_since_epoch
            tz_min = ts.tz_offset_minutes
            tz = datetime.timezone(datetime.timedelta(minutes=tz_min))
            dt = datetime.datetime.fromtimestamp(millis / 1000, tz=tz)
            # No year — MM-DD HH:MM
            datetime_str = dt.strftime("%m-%d %H:%M")
        except Exception:
            datetime_str = ""

        # Two-row default like jj: first row has ids+author+datetime, second has description
        first_line = commit.description.splitlines()[0] if commit.description else None
        desc = first_line or "(no description set)"
        # First row: graph + change + commit + bookmarks + author + datetime
        author_part = f" {author}" if author else ""
        datetime_part = f" {datetime_str}" if datetime_str else ""
        line1 = f"{graph_prefix}{change_disp} {commit_disp}{bm_str}{author_part}{datetime_part}"
        print(line1)
        # Second row: continuation graph + description (no ids)
        if not no_graph:
            print(f"{cont_prefix}{desc}")
        else:
            print(f"  {desc}")

        if show_patch:
            if commit.parent_ids:
                try:
                    parent = repo.get_commit(commit.parent_ids[0])
                    for e in parent.diff(commit):
                        print(f"  {e.status:8} {e.path}")
                except Exception:
                    pass
            else:
                try:
                    for p in commit.list_files():
                        print(f"  added    {p}")
                except Exception:
                    pass

    return 0
