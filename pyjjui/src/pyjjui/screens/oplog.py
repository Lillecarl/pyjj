"""Modal browsing the operation log (`jj op log`) to pick a past operation
to restore to -- `Transaction.restore_operation()` equivalent, distinct
from the single-step `u`/`U` undo/redo already bound elsewhere (this can
jump straight to any operation, not just one step back/forward).
"""

from datetime import datetime, timezone

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label

import pyjj


class OpLogScreen(ModalScreen[pyjj.Operation | None]):
    """Dismisses with the selected `Operation` to restore to, or `None`."""

    DEFAULT_CSS = """
    OpLogScreen {
        align: center middle;
    }
    OpLogScreen > Vertical {
        width: 90%;
        height: 80%;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    OpLogScreen DataTable {
        height: 1fr;
        margin-top: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, operations: list[pyjj.Operation]) -> None:
        super().__init__()
        self._operations = operations

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Operation log -- enter to restore, escape to cancel")
            table = DataTable(cursor_type="row", show_header=False)
            table.add_column("time")
            table.add_column("description")
            yield table

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        for op in self._operations:
            table.add_row(_format_time(op), op.description or "(no description)")
        if self._operations:
            table.move_cursor(row=0)
        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.dismiss(self._operations[event.cursor_row])

    def action_cancel(self) -> None:
        self.dismiss(None)


def _format_time(op: pyjj.Operation) -> str:
    when = datetime.fromtimestamp(op.end_time.millis_since_epoch / 1000, tz=timezone.utc)
    return when.strftime("%Y-%m-%d %H:%M:%S")
