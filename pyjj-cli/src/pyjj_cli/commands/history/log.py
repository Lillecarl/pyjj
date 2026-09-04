"""history subcommand: log — backed by log_graph, drawn by jj's renderer."""
import os
import sys

import pyjj
from pyjj.graph_layout import reverse_graph

from ..common import _load, _print_diff_stats, _resolve_template

# ANSI — match jj's 256-color palette where it matters.
# Only emitted when stdout is a TTY and NO_COLOR is not set.
_RESET = "\033[0m"
_BOLD = "\033[1m"
# jj log: change prefix magenta(13) bold, rest grey(8); commit prefix blue(12), rest grey; author yellow(3); timestamp cyan(14); bookmark/graph green(2)
_CHANGE_PREFIX = "\033[1m\033[38;5;13m"
_CHANGE_REST = "\033[38;5;8m"
_COMMIT_PREFIX = "\033[38;5;12m"
_COMMIT_REST = "\033[38;5;8m"
_AUTHOR_COLOR = "\033[38;5;3m"
_TIMESTAMP_COLOR = "\033[38;5;14m"
_BOOKMARK_COLOR = "\033[38;5;2m"
_GRAPH_GREEN_BOLD = "\033[1m\033[38;5;2m"


def _use_color() -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("FORCE_COLOR") is not None:
        return True
    return sys.stdout.isatty()


def _color_change_id(hex_str: str, prefix_len: int, use_color: bool) -> str:
    """A change id, highlighted at its shortest unique prefix.

    `hex_str` must be jj's reverse-hex spelling, not the raw hex the id
    carries. jj resolves only the reverse-hex form as a revset, so a
    listing that prints raw hex prints something the reader cannot paste
    back.

    Eight characters is a floor, not a width: a repository large enough
    to need nine gets nine, the way jj's `shortest(8)` does.
    """
    shown = hex_str[:max(8, prefix_len)]
    if not use_color:
        return shown
    hl = min(prefix_len if prefix_len > 0 else len(shown), len(shown))
    if hl == len(shown):
        return f"{_CHANGE_PREFIX}{shown}{_RESET}"
    return f"{_CHANGE_PREFIX}{shown[:hl]}{_CHANGE_REST}{shown[hl:]}{_RESET}"


def _color_commit_id(hex_str: str, prefix_len: int, use_color: bool) -> str:
    """A commit id, highlighted at its shortest unique prefix, with the
    same eight-character floor as `_color_change_id`."""
    shown = hex_str[:max(8, prefix_len)]
    if not use_color:
        return shown
    hl = min(prefix_len if prefix_len > 0 else len(shown), len(shown))
    if hl == len(shown):
        return f"{_COMMIT_PREFIX}{shown}{_RESET}"
    return f"{_COMMIT_PREFIX}{shown[:hl]}{_COMMIT_REST}{shown[hl:]}{_RESET}"


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

    # Working-copy commits for glyph/description color — support multiple workspaces
    try:
        view = repo.view()
        wc_ids = set(view.values())
        wc_names_by_hex = {hex_id: name for name, hex_id in view.items()}
        # Also handle current workspace explicitly for @ vs ○ distinction if needed
        current_wc_hex = view.get(ws.workspace_name)
    except Exception:
        wc_ids = set()
        wc_names_by_hex = {}
        current_wc_hex = None

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
    reversed_order = getattr(args, "reversed", False)
    if reversed_order:
        items = reverse_graph(items)

    no_graph = getattr(args, "no_graph", False)
    show_patch = getattr(args, "patch", False)
    show_stat = getattr(args, "stat", False)
    use_color = _use_color()

    # jj's own builtin template names, mapped to a Jinja equivalent so
    # `pyjj log -T builtin_log_oneline` keeps working like `jj log` does.
    builtin_templates = {
        "builtin_log_compact": "{{ change_id_short }} {{ commit_id_short }} {{ author }} {{ datetime }}\n{{ description }}",
        "builtin_log_compact_full_description": "{{ change_id_short }} {{ commit_id_short }} {{ author }} {{ datetime }}\n{{ description_full }}",
        "builtin_log_oneline": "{{ change_id_short }} {{ description }}",
    }

    jinja_template = _resolve_template(settings, ws, args, "log", builtin_templates)

    # Decide year display: 26 not 2026, unless visible range spans two millennia
    # (e.g. 1999 and 2026 are 1xxx vs 2xxx → show 4-digit to disambiguate).
    # Ignore root() (1970 epoch) — it's synthetic and would force 4-digit forever.
    spans_millennia = False
    if nodes:
        try:
            import datetime

            years = []
            for node in nodes:
                if not node.commit.parent_ids:  # root
                    continue
                ts = node.commit.author.timestamp
                tz = datetime.timezone(datetime.timedelta(minutes=ts.tz_offset_minutes))
                dt = datetime.datetime.fromtimestamp(ts.millis_since_epoch / 1000, tz=tz)
                years.append(dt.year)
            if years:
                spans_millennia = (min(years) // 1000) != (max(years) // 1000)
        except Exception:
            spans_millennia = False

    renderer = pyjj.GraphRenderer() if not no_graph else None
    for hex_id, edges in items:
        commit = by_id[hex_id].commit
        is_wc = hex_id in wc_ids
        is_current_wc = current_wc_hex is not None and hex_id == current_wc_hex
        is_root = not commit.parent_ids  # root() has no parents
        # Only current workspace is @; other workspaces are ○ but still show workspace name
        raw_glyph = "@" if is_current_wc else ("◆" if is_root else "○")
        # Only current wc gets green glyph/description — matches jj
        is_green = is_current_wc
        glyph = f"{_GRAPH_GREEN_BOLD}{raw_glyph}{_RESET}" if use_color and is_green else raw_glyph

        # The graph is drawn by jj's own renderer, which takes the whole
        # row's text at once and decides where it sits among the lines it
        # draws. So each branch below builds its lines and emits one row.
        def emit(lines):
            if no_graph:
                print(lines[0])
                for extra in lines[1:]:
                    print(f"  {extra}")
                return
            sys.stdout.write(
                renderer.next_row(hex_id, edges, raw_glyph, "\n".join(lines)))

        # IDs with shortest-prefix highlight — magenta for change, blue for commit, rest grey
        try:
            c_len = repo.shortest_change_id_prefix_len(commit.change_id, settings)
        except Exception:
            c_len = 8
        try:
            k_len = repo.shortest_commit_id_prefix_len(commit.id, settings)
        except Exception:
            k_len = 8
        change_disp = _color_change_id(commit.change_id.reverse_hex(), c_len, use_color)
        commit_disp = _color_commit_id(commit.id.hex(), k_len, use_color)

        bm_names = bm_by_commit.get(hex_id, [])
        ws_name = wc_names_by_hex.get(hex_id) if is_wc else None
        if ws_name and ws_name not in bm_names:
            bm_names = bm_names + [f"{ws_name}@"]
        # Keep raw for template context, and colored for default rendering
        bm_str_raw = " ".join(sorted(bm_names))
        if bm_names:
            bm_str = " " + bm_str_raw
            if use_color:
                bm_str = f" {_BOOKMARK_COLOR}{bm_str.strip()}{_RESET}"
                bm_str = " " + bm_str.strip()
        else:
            bm_str = ""

        # Author: username (name) is default like we do (jj shows email, we think name is better);
        # template can pick either via {{ author }} vs {{ author_email }}.
        try:
            author_name = commit.author.name or ""
            author_email = commit.author.email or ""
            author = author_name or author_email
        except Exception:
            author_name = author_email = author = ""
        author_disp = f"{_AUTHOR_COLOR}{author}{_RESET}" if use_color and author else author

        try:
            ts = commit.author.timestamp if hasattr(commit.author, "timestamp") else commit.committer.timestamp
            import datetime

            millis = ts.millis_since_epoch
            tz_min = ts.tz_offset_minutes
            tz = datetime.timezone(datetime.timedelta(minutes=tz_min))
            dt = datetime.datetime.fromtimestamp(millis / 1000, tz=tz)
            if spans_millennia:
                datetime_str = dt.strftime("%Y-%m-%d %H:%M")
            else:
                datetime_str = dt.strftime("%y-%m-%d %H:%M")
        except Exception:
            datetime_str = ""
            dt = None
        datetime_disp = f"{_TIMESTAMP_COLOR}{datetime_str}{_RESET}" if use_color and datetime_str else datetime_str

        first_line = commit.description.splitlines()[0] if commit.description else None
        desc_raw = first_line or "(no description set)"
        desc = f"{_BOOKMARK_COLOR}{desc_raw}{_RESET}" if use_color and is_green else desc_raw

        # If --template given, render it via Jinja2. Context exposes both raw and
        # colored short ids, plus author/email/description/bookmarks.
        if jinja_template is not None:
            # Build colored and raw shorts for template to pick
            try:
                c_len = repo.shortest_change_id_prefix_len(commit.change_id, settings)
            except Exception:
                c_len = 8
            try:
                k_len = repo.shortest_commit_id_prefix_len(commit.id, settings)
            except Exception:
                k_len = 8
            ctx = {
                "commit": commit,
                "change_id": commit.change_id.reverse_hex(),
                "commit_id": commit.id.hex(),
                "change_id_short": _color_change_id(commit.change_id.reverse_hex(), c_len, use_color),
                "commit_id_short": _color_commit_id(commit.id.hex(), k_len, use_color),
                "change_id_short_raw": commit.change_id.reverse_hex()[:8],
                "commit_id_short_raw": commit.id.hex()[:8],
                "author": author,
                "author_name": author_name,
                "author_email": author_email,
                "author_display": author_disp,
                "description": desc_raw,
                "description_full": commit.description.strip() or "(no description set)",
                "description_display": desc,
                "bookmarks": bm_names,
                "bookmarks_str": bm_str_raw,
                "bookmarks_display": bm_str.strip() if bm_str else "",
                "datetime": datetime_str,
                "datetime_display": datetime_disp,
                "is_wc": is_wc,
                "is_current_wc": is_current_wc,
                "is_root": is_root,
            }
            try:
                rendered = jinja_template.render(ctx)
            except Exception as e:
                print(f"Error: template render failed: {e}", file=sys.stderr)
                return 1
            # A template is the whole row, exactly like `jj log -T`. Do not
            # append a description line: the template says what to print,
            # and a template that wants the description asks for it. The
            # two-row default lives in the no-template branch below.
            emit(rendered.splitlines() or [""])
        elif is_root:
            # jj gives the root commit a row of its own: it has no author
            # and no timestamp worth printing, and the epoch reads as a
            # 1970 commit that nobody made. `root()` says what it is.
            emit([f"{change_disp} root() {commit_disp}{bm_str}"])
        else:
            # Default two-row like jj but with username (name) not email — user says name is better
            author_part = f" {author_disp}" if author else ""
            datetime_part = f" {datetime_disp}" if datetime_str else ""
            emit([
                f"{change_disp} {commit_disp}{bm_str}{author_part}{datetime_part}",
                desc if not no_graph else desc_raw,
            ])

        if show_stat:
            # `--stat` reads file content, so it only runs when asked.
            parent = (repo.get_commit(commit.parent_ids[0])
                      if commit.parent_ids else None)
            if parent is not None:
                _print_diff_stats(parent.diff_stats(commit, settings))

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
