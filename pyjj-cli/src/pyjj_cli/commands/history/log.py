"""history subcommand: log — now backed by log_graph + shared graph_layout."""
import os
import sys

import pyjj
from pyjj.graph_layout import layout

from ..common import _load

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
    shown = hex_str[:8]
    if not use_color:
        return shown
    hl = min(prefix_len if prefix_len > 0 else len(shown), len(shown))
    if hl == len(shown):
        return f"{_CHANGE_PREFIX}{shown}{_RESET}"
    return f"{_CHANGE_PREFIX}{shown[:hl]}{_CHANGE_REST}{shown[hl:]}{_RESET}"


def _color_commit_id(hex_str: str, prefix_len: int, use_color: bool) -> str:
    shown = hex_str[:8]
    if not use_color:
        return shown
    hl = min(prefix_len if prefix_len > 0 else len(shown), len(shown))
    if hl == len(shown):
        return f"{_COMMIT_PREFIX}{shown}{_RESET}"
    return f"{_COMMIT_PREFIX}{shown[:hl]}{_COMMIT_REST}{shown[hl:]}{_RESET}"


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

    rows = layout(nodes)

    no_graph = getattr(args, "no_graph", False)
    show_patch = getattr(args, "patch", False)
    use_color = _use_color()
    template_str = getattr(args, "template", None)
    # pyjj.templates.* with Jinja — if no --template, check config `pyjj.templates.log`
    if not template_str:
        try:
            template_str = settings.get_string("pyjj.templates.log")
        except Exception:
            template_str = None
    # If --template is a bare name like `my-cool`, try `pyjj.templates.<name>` before treating as raw Jinja
    if template_str and "{{" not in template_str and " " not in template_str and "\n" not in template_str:
        try:
            from_config = settings.get_string(f"pyjj.templates.{template_str}")
            if from_config:
                template_str = from_config
        except Exception:
            pass

    # Compile Jinja template if --template given. We expose a Pythonic context
    # (commit, change_id, commit_id, author, author_email, description, bookmarks,
    # is_wc, datetime) — most well-known templating language in Python, so users
    # can do `pyjj log -T '{{ author }} {{ description }}'` etc. Builtin jj names
    # like `builtin_log_compact` are mapped to a Jinja equivalent.
    jinja_template = None
    builtin_templates = {
        "builtin_log_compact": "{{ change_id_short }} {{ commit_id_short }} {{ author }} {{ datetime }} {{ description }}",
        "builtin_log_compact_full_description": "{{ change_id_short }} {{ commit_id_short }} {{ author }} {{ datetime }}\n{{ description }}",
        "builtin_log_oneline": "{{ change_id_short }} {{ description }}",
    }
    if template_str:
        # jj allows `jj log -T builtin_*` — map it, else treat as raw Jinja
        template_str = builtin_templates.get(template_str, template_str)
        try:
            from jinja2 import Environment, StrictUndefined

            env = Environment(undefined=StrictUndefined, autoescape=False)
            # Filter to color prefix like jj does, usable as {{ commit_id|short(2) }}
            def _short_filter(value, n=8):
                return value[:n] if isinstance(value, str) else value

            env.filters["short"] = _short_filter
            jinja_template = env.from_string(template_str)
        except Exception as e:
            print(f"Error: invalid template: {e}", file=sys.stderr)
            return 1

    # Decide year display: 26 not 2026, unless visible range spans two millennia
    # (e.g. 1999 and 2026 are 1xxx vs 2xxx → show 4-digit to disambiguate).
    # Ignore root() (1970 epoch) — it's synthetic and would force 4-digit forever.
    spans_millennia = False
    if rows:
        try:
            import datetime

            years = []
            for r in rows:
                if not r.node.commit.parent_ids:  # root
                    continue
                ts = r.node.commit.author.timestamp
                tz = datetime.timezone(datetime.timedelta(minutes=ts.tz_offset_minutes))
                dt = datetime.datetime.fromtimestamp(ts.millis_since_epoch / 1000, tz=tz)
                years.append(dt.year)
            if years:
                spans_millennia = (min(years) // 1000) != (max(years) // 1000)
        except Exception:
            spans_millennia = False

    for row in rows:
        commit = row.node.commit
        hex_id = commit.id.hex()
        is_wc = hex_id in wc_ids
        is_current_wc = current_wc_hex is not None and hex_id == current_wc_hex
        is_root = not commit.parent_ids  # root() has no parents
        # Only current workspace is @; other workspaces are ○ but still show workspace name
        raw_glyph = "@" if is_current_wc else ("◆" if is_root else "○")
        # Only current wc gets green glyph/description — matches jj
        is_green = is_current_wc
        glyph = f"{_GRAPH_GREEN_BOLD}{raw_glyph}{_RESET}" if use_color and is_green else raw_glyph

        # Graph prefix for first row (commit line)
        if no_graph:
            graph_prefix = ""
            cont_prefix = ""
        else:
            glyphs = _render_glyphs_plain(row)
            chars = list(glyphs)
            if row.column >= len(chars):
                chars.extend([" "] * (row.column - len(chars) + 1))
            chars[row.column] = raw_glyph
            graph_prefix = "".join(chars) + " "
            if use_color:
                # Color the glyph like jj does (bold green for @)
                if is_wc:
                    graph_prefix = graph_prefix.replace(raw_glyph, f"{_GRAPH_GREEN_BOLD}{raw_glyph}{_RESET}", 1)
            # Second row (description) — vertical continuation of lanes
            cont_chars = []
            for i in range(row.width):
                if i == row.column:
                    cont_chars.append("│")
                elif i < len(glyphs) and glyphs[i] != " ":
                    cont_chars.append("│")
                else:
                    active = any(e.from_column == i or e.to_column == i for e in row.edges)
                    cont_chars.append("│" if active else " ")
            while cont_chars and cont_chars[-1] == " " and len(cont_chars) > row.column + 1:
                cont_chars.pop()
            cont_prefix = "".join(cont_chars) + " "

        # IDs with shortest-prefix highlight — magenta for change, blue for commit, rest grey
        try:
            c_len = repo.shortest_change_id_prefix_len(commit.change_id)
        except Exception:
            c_len = 8
        try:
            k_len = repo.shortest_commit_id_prefix_len(commit.id)
        except Exception:
            k_len = 8
        change_disp = _color_change_id(commit.change_id.hex(), c_len, use_color)
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
                c_len = repo.shortest_change_id_prefix_len(commit.change_id)
            except Exception:
                c_len = 8
            try:
                k_len = repo.shortest_commit_id_prefix_len(commit.id)
            except Exception:
                k_len = 8
            ctx = {
                "commit": commit,
                "change_id": commit.change_id.hex(),
                "commit_id": commit.id.hex(),
                "change_id_short": _color_change_id(commit.change_id.hex(), c_len, use_color),
                "commit_id_short": _color_commit_id(commit.id.hex(), k_len, use_color),
                "change_id_short_raw": commit.change_id.hex()[:8],
                "commit_id_short_raw": commit.id.hex()[:8],
                "author": author,
                "author_name": author_name,
                "author_email": author_email,
                "author_display": author_disp,
                "description": desc_raw,
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
            # Template may contain newlines — print with graph prefix on first line,
            # continuation prefix on subsequent lines.
            lines = rendered.splitlines() or [""]
            print(f"{graph_prefix}{lines[0]}")
            for extra in lines[1:]:
                if not no_graph:
                    print(f"{cont_prefix}{extra}")
                else:
                    print(f"  {extra}")
            # Still show second row description if template didn't already include it?
            # If template was single-line, we already printed second row? No — template replaces line1 only.
            # Keep our two-row desc unless template explicitly covered it (heuristic: if template contains 'description', skip).
            if "description" not in (template_str or ""):
                if not no_graph:
                    cont_prefix_disp = f"{_BOOKMARK_COLOR}{cont_prefix.rstrip()}{_RESET} " if use_color and is_green and cont_prefix.strip() else cont_prefix
                    desc_disp = f"{_BOOKMARK_COLOR}{desc_raw}{_RESET}" if use_color and is_green else desc_raw
                    if use_color and is_green:
                        print(f"{cont_prefix_disp}{desc_disp}")
                    else:
                        print(f"{cont_prefix}{desc_raw}")
                else:
                    print(f"  {desc_raw}")
        else:
            # Default two-row like jj but with username (name) not email — user says name is better
            author_part = f" {author_disp}" if author else ""
            datetime_part = f" {datetime_disp}" if datetime_str else ""
            line1 = f"{graph_prefix}{change_disp} {commit_disp}{bm_str}{author_part}{datetime_part}"
            print(line1)
            if not no_graph:
                cont_prefix_disp = f"{_BOOKMARK_COLOR}{cont_prefix.rstrip()}{_RESET} " if use_color and is_green and cont_prefix.strip() else cont_prefix
                desc_disp = f"{_BOOKMARK_COLOR}{desc}{_RESET}" if use_color and is_green else desc
                if use_color and is_green:
                    print(f"{cont_prefix_disp}{desc_disp}")
                else:
                    print(f"{cont_prefix}{desc}")
            else:
                print(f"  {desc_raw}")

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
