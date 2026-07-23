"""Modal browsing the operation log (`jj op log`) to pick a past operation
to restore to -- `Transaction.restore_operation()` equivalent, distinct
from the single-step `u`/`U` undo/redo already bound elsewhere (this can
jump straight to any operation, not just one step back/forward).

Also shows a diff pane alongside the list: by default the diff between
the current repo's working copy and the highlighted operation's, or --
if a second entry is marked with `space` -- between that marked entry and
the highlighted one, so two arbitrary points in history can be compared
without restoring to either first.
"""

from datetime import datetime, timezone

from rich.console import Group
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label, Static
from textual.widgets.data_table import RowKey

import pyjj

from ..render.diff import render_commit_diff
from .files import FilesScreen


class _OpTable(DataTable):
    """`j`/`k` alongside DataTable's own up/down, `l` to move focus into
    the diff pane -- same hjkl convention as `LogView`/`Preview`.
    """

    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("l", "focus_diff", "Diff", show=False),
    ]

    def action_focus_diff(self) -> None:
        self.screen.query_one(DiffPane).focus()


class DiffPane(VerticalScroll):
    """Shows the diff for whatever `OpLogScreen` last computed. `h` moves
    focus back to the table -- see `_OpTable`'s matching `l` binding.
    """

    BINDINGS = [
        Binding("j", "scroll_down", show=False),
        Binding("k", "scroll_up", show=False),
        Binding("h", "focus_table", "Log", show=False),
    ]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._body = Static()

    def compose(self) -> ComposeResult:
        yield self._body

    def show_diff(self, header: str, after: pyjj.Commit, before: pyjj.Commit) -> None:
        self._body.update(Group(Text(header, style="bold"), Text(), render_commit_diff(after, before)))

    def action_focus_table(self) -> None:
        self.screen.query_one(_OpTable).focus()


class OpLogScreen(ModalScreen[pyjj.Operation | None]):
    """Dismisses with the selected `Operation` to restore to, or `None`."""

    DEFAULT_CSS = """
    OpLogScreen {
        align: center middle;
    }
    OpLogScreen > Vertical {
        width: 95%;
        height: 90%;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    OpLogScreen Horizontal {
        height: 1fr;
        margin-top: 1;
    }
    OpLogScreen _OpTable {
        width: 45%;
    }
    OpLogScreen DiffPane {
        width: 55%;
        border-left: solid $border-blurred;
        padding-left: 1;
    }
    OpLogScreen DiffPane:focus {
        border-left: solid $border;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("space", "toggle_mark", "Mark as diff base", show=False),
        Binding("f", "files", "Files", show=False),
    ]

    def __init__(
        self,
        repo: pyjj.ReadonlyRepo,
        settings: pyjj.UserSettings,
        operations: list[pyjj.Operation],
    ) -> None:
        super().__init__()
        self._repo = repo
        self._settings = settings
        self._operations = operations
        self._marked_index: int | None = None
        self._row_keys: list[RowKey] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(
                "Operation log -- enter to restore, space to mark a diff"
                " base, f to browse files, escape to cancel"
            )
            with Horizontal():
                table = _OpTable(cursor_type="row", show_header=False)
                table.add_column("mark", key="mark")
                table.add_column("time", key="time")
                table.add_column("description", key="description")
                yield table
                yield DiffPane()

    def on_mount(self) -> None:
        table = self.query_one(_OpTable)
        for op in self._operations:
            row_key = table.add_row("", _format_time(op), op.description or "(no description)")
            self._row_keys.append(row_key)
        if self._operations:
            table.move_cursor(row=0)
            self._show_diff(0)
        table.focus()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row is not None:
            self._show_diff(event.cursor_row)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.dismiss(self._operations[event.cursor_row])

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_toggle_mark(self) -> None:
        table = self.query_one(_OpTable)
        row = table.cursor_row
        if not self._operations:
            return
        if self._marked_index is not None:
            table.update_cell(self._row_keys[self._marked_index], "mark", "")
        self._marked_index = None if self._marked_index == row else row
        if self._marked_index is not None:
            table.update_cell(self._row_keys[self._marked_index], "mark", "✓")
        self._show_diff(row)

    @work
    async def action_files(self) -> None:
        """`f` -- browse the highlighted operation's working-copy tree in
        the same `FilesScreen` the main log's `f` binding opens. Diffing/
        restoring inside it always compares against/writes into the
        *live* working copy (`FilesScreen` reads `self.app.state` for
        that), regardless of which historic operation it was opened from
        here.
        """
        if not self._operations:
            return
        op = self._operations[self.query_one(_OpTable).cursor_row]
        commit = self._repo.load_at_operation(op).resolve_single(self._settings, "@")
        await self.app.push_screen_wait(FilesScreen(commit))

    def _show_diff(self, index: int) -> None:
        op = self._operations[index]
        after = self._repo.load_at_operation(op).resolve_single(self._settings, "@")

        if self._marked_index is not None and self._marked_index != index:
            base_op = self._operations[self._marked_index]
            before = self._repo.load_at_operation(base_op).resolve_single(self._settings, "@")
            header = f"diff: {_format_time(base_op)} (marked) -> {_format_time(op)}"
        else:
            before = self._repo.resolve_single(self._settings, "@")
            header = f"diff: current -> {_format_time(op)}"

        self.query_one(DiffPane).show_diff(header, after, before)


def _format_time(op: pyjj.Operation) -> str:
    when = datetime.fromtimestamp(op.end_time.millis_since_epoch / 1000, tz=timezone.utc)
    return when.strftime("%Y-%m-%d %H:%M:%S")
