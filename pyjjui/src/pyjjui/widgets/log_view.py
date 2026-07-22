"""The main log/graph view: a `DataTable` subclass rendering `log_graph()`
nodes with graph-column glyphs (see `graph_layout.py`) plus a one-line
commit summary per row.
"""

from rich.text import Text
from textual.binding import Binding
from textual.widgets import DataTable
from textual.widgets.data_table import RowKey
from textual.message import Message

import pyjj

from ..graph_layout import GraphRow, layout


class LogView(DataTable):
    """Shows the current revset's commits as a graph, one row per commit."""

    # `j`/`k` alongside the DataTable's own up/down: jjui convention, adapted
    # -- jjui uses `l`/right to open a separate revision-details panel and
    # `h`/left to close it, but pyjjui's log and preview panes are both
    # always on screen side by side, so here `l`/`h` instead move focus
    # between them (see Preview's matching `h` binding back the other way).
    # `space`/`escape` for marking, also jjui's own convention: mark the
    # commit under the cursor for a bulk operation (abandon, merge-commit
    # creation via `n`), or clear the whole marked set.
    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("l", "focus_preview", "Preview", show=False),
        Binding("space", "toggle_mark", "Mark", show=False),
        Binding("escape", "clear_marks", "Clear marks", show=False),
    ]

    class CommitSelected(Message):
        """Posted when the highlighted row changes to a new commit."""

        def __init__(self, commit: pyjj.Commit) -> None:
            self.commit = commit
            super().__init__()

    class FocusPreview(Message):
        """Posted on `l` to ask the app to move focus to Preview -- LogView
        can't reach a sibling widget directly (Textual's "attributes down,
        messages up": siblings coordinate through their parent, not by
        querying each other), so the App handles this the same way it
        already bridges `CommitSelected` to `Preview.show_commit()`.
        """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(cursor_type="row", show_header=False, zebra_stripes=False, **kwargs)
        self._commits: list[pyjj.Commit] = []
        self._row_keys: list[RowKey] = []
        self._marked: set[pyjj.CommitId] = set()
        # Cached from the last update_nodes() call so toggling a mark can
        # redraw without re-querying jj -- rendering is pure given these.
        self._rows: list[GraphRow] = []
        self._wc_commit_id: pyjj.CommitId | None = None
        self._bookmarks_by_commit: dict[pyjj.CommitId, list[str]] = {}

    def on_mount(self) -> None:
        self.add_column("graph", key="graph")
        self.add_column("commit", key="commit")

    def update_nodes(
        self,
        nodes: list[pyjj.GraphNode],
        wc_commit_id: pyjj.CommitId | None,
        bookmarks: list[pyjj.Bookmark],
    ) -> None:
        """Recompute lane layout and redraw every row from scratch."""
        previous_change_id = (
            self._commits[self.cursor_row].change_id
            if self._commits and 0 <= self.cursor_row < len(self._commits)
            else None
        )

        self._rows = layout(nodes)
        self._wc_commit_id = wc_commit_id
        self._bookmarks_by_commit = {}
        for bookmark in bookmarks:
            for target_id in bookmark.target_ids:
                self._bookmarks_by_commit.setdefault(target_id, []).append(bookmark.name)

        current_ids = {row.node.commit.id for row in self._rows}
        self._marked &= current_ids  # drop marks on commits this refresh rewrote/abandoned away

        restored = next(
            (i for i, row in enumerate(self._rows) if row.node.commit.change_id == previous_change_id),
            0,
        )
        self._redraw(cursor_row=restored)

    def _redraw(self, cursor_row: int) -> None:
        """Rebuild every row from the cached graph/bookmarks/marks state --
        no jj I/O, just re-rendering. Used both by update_nodes() (fresh
        data) and by mark toggling (same data, different marks).
        """
        self.clear()
        self._commits = [row.node.commit for row in self._rows]
        self._row_keys = []
        for row in self._rows:
            commit_id = row.node.commit.id
            is_wc = self._wc_commit_id is not None and commit_id == self._wc_commit_id
            is_marked = commit_id in self._marked
            names = self._bookmarks_by_commit.get(commit_id, [])
            row_key = self.add_row(
                _render_glyphs(row, is_wc),
                _render_summary(row.node.commit, is_wc, is_marked, names),
            )
            self._row_keys.append(row_key)

        if not self._rows:
            return
        self.move_cursor(row=cursor_row)
        self.post_message(self.CommitSelected(self._commits[cursor_row]))

    def _update_row_mark(self, index: int) -> None:
        """Repaint just one row's summary cell after its mark state
        changed -- action_toggle_mark/action_clear_marks touch at most a
        handful of rows, so a full clear()+rebuild (_redraw) would be
        needless work; DataTable.update_cell exists for exactly this.
        """
        row = self._rows[index]
        commit_id = row.node.commit.id
        is_wc = self._wc_commit_id is not None and commit_id == self._wc_commit_id
        is_marked = commit_id in self._marked
        names = self._bookmarks_by_commit.get(commit_id, [])
        self.update_cell(
            self._row_keys[index],
            "commit",
            _render_summary(row.node.commit, is_wc, is_marked, names),
        )

    @property
    def selected_commit(self) -> pyjj.Commit | None:
        if self._commits and 0 <= self.cursor_row < len(self._commits):
            return self._commits[self.cursor_row]
        return None

    @property
    def marked_commits(self) -> list[pyjj.Commit]:
        """Just the marked commits, display order, empty if none -- unlike
        `selection`, which falls back to the cursor commit. Rebase needs
        that distinction: the cursor picks the *destination*, so it can't
        also stand in for an empty source set the way it does for
        abandon/new-child.
        """
        return [c for c in self._commits if c.id in self._marked]

    @property
    def selection(self) -> list[pyjj.Commit]:
        """The marked commits, in the log's display order, or -- if nothing
        is marked -- just the commit under the cursor. This is what bulk
        actions (abandon, new-commit-as-merge) should read instead of
        `selected_commit` directly, so marking is opt-in: an action with
        nothing marked behaves exactly as it did before marking existed.
        """
        if self._marked:
            return [c for c in self._commits if c.id in self._marked]
        commit = self.selected_commit
        return [commit] if commit is not None else []

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row is None or not (0 <= event.cursor_row < len(self._commits)):
            return
        self.post_message(self.CommitSelected(self._commits[event.cursor_row]))

    def action_focus_preview(self) -> None:
        self.post_message(self.FocusPreview())

    def action_toggle_mark(self) -> None:
        commit = self.selected_commit
        if commit is None:
            return
        if commit.id in self._marked:
            self._marked.discard(commit.id)
        else:
            self._marked.add(commit.id)
        self._update_row_mark(self.cursor_row)

    def action_clear_marks(self) -> None:
        if not self._marked:
            return
        marked_indexes = [i for i, row in enumerate(self._rows) if row.node.commit.id in self._marked]
        self._marked.clear()
        for index in marked_indexes:
            self._update_row_mark(index)


def _render_glyphs(row: GraphRow, is_wc: bool) -> Text:
    lanes = {row.column}
    for edge in row.edges:
        lanes.add(edge.from_column)
        lanes.add(edge.to_column)
    width = max(lanes) + 1
    chars = [" "] * width

    for edge in row.edges:
        lo, hi = sorted((edge.from_column, edge.to_column))
        if lo == hi:
            chars[lo] = "│"
            continue
        for col in range(lo + 1, hi):
            chars[col] = "─"
        if edge.from_column == row.column:
            # This row's own edge, departing toward a lane it'll occupy in
            # later (lower) rows -- a fork opening up below this node.
            chars[edge.to_column] = "╮" if edge.to_column > edge.from_column else "╭"
        else:
            # A lane from an earlier (higher) row converging into this
            # node -- a branch closing back up above this node.
            chars[edge.from_column] = "╯" if edge.from_column > edge.to_column else "╰"

    chars[row.column] = "@" if is_wc else "○"  # ○
    text = Text("".join(chars))
    if is_wc:
        text.stylize("bold green")
    return text


def _render_summary(
    commit: pyjj.Commit, is_wc: bool, is_marked: bool, bookmark_names: list[str]
) -> Text:
    text = Text()
    text.append("✓ " if is_marked else "  ", style="bold yellow")
    change_id = commit.change_id.hex()[:8]
    first_line = commit.description.splitlines()[0] if commit.description else None
    text.append(f"{change_id} ", style="cyan")
    if bookmark_names:
        text.append(" ".join(sorted(bookmark_names)) + " ", style="bold green")
    text.append(
        first_line or "(no description set)",
        style="bold" if is_wc else ("dim italic" if first_line is None else ""),
    )
    return text
