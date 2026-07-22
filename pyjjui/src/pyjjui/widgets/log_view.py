"""The main log/graph view: a `DataTable` subclass rendering `log_graph()`
nodes with graph-column glyphs (see `graph_layout.py`) plus a one-line
commit summary per row.
"""

from rich.text import Text
from textual.widgets import DataTable
from textual.message import Message

import pyjj

from ..graph_layout import GraphRow, layout


class LogView(DataTable):
    """Shows the current revset's commits as a graph, one row per commit."""

    class CommitSelected(Message):
        """Posted when the highlighted row changes to a new commit."""

        def __init__(self, commit: pyjj.Commit) -> None:
            self.commit = commit
            super().__init__()

    def __init__(self, **kwargs: object) -> None:
        super().__init__(cursor_type="row", show_header=False, zebra_stripes=False, **kwargs)
        self._commits: list[pyjj.Commit] = []

    def on_mount(self) -> None:
        self.add_column("graph", key="graph")
        self.add_column("commit", key="commit")

    def update_nodes(
        self, nodes: list[pyjj.GraphNode], wc_commit_id: pyjj.CommitId | None
    ) -> None:
        """Recompute lane layout and redraw every row from scratch."""
        previous_change_id = (
            self._commits[self.cursor_row].change_id
            if self._commits and 0 <= self.cursor_row < len(self._commits)
            else None
        )

        rows = layout(nodes)
        self.clear()
        self._commits = [row.node.commit for row in rows]
        for row in rows:
            is_wc = wc_commit_id is not None and row.node.commit.id == wc_commit_id
            self.add_row(_render_glyphs(row, is_wc), _render_summary(row.node.commit, is_wc))

        if not rows:
            return
        restored = next(
            (i for i, c in enumerate(self._commits) if c.change_id == previous_change_id), 0
        )
        self.move_cursor(row=restored)
        self.post_message(self.CommitSelected(self._commits[restored]))

    @property
    def selected_commit(self) -> pyjj.Commit | None:
        if self._commits and 0 <= self.cursor_row < len(self._commits):
            return self._commits[self.cursor_row]
        return None

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row is None or not (0 <= event.cursor_row < len(self._commits)):
            return
        self.post_message(self.CommitSelected(self._commits[event.cursor_row]))


def _render_glyphs(row: GraphRow, is_wc: bool) -> Text:
    lanes = {row.column}
    for edge in row.edges:
        lanes.add(edge.from_column)
        lanes.add(edge.to_column)
    width = max(lanes) + 1
    chars = [" "] * width
    for lane in lanes:
        chars[lane] = "│"  # │
    chars[row.column] = "@" if is_wc else "○"  # ○
    text = Text("".join(chars))
    if is_wc:
        text.stylize("bold green")
    return text


def _render_summary(commit: pyjj.Commit, is_wc: bool) -> Text:
    change_id = commit.change_id.hex()[:8]
    first_line = commit.description.splitlines()[0] if commit.description else None
    text = Text(f"{change_id} ", style="cyan")
    text.append(
        first_line or "(no description set)",
        style="bold" if is_wc else ("dim italic" if first_line is None else ""),
    )
    return text
