"""Read-only modal file browser for one commit's tree -- lists every path
via `Commit.list_files()` beside a content pane for whichever one is
highlighted. Always dismisses with `None`: there's nothing to pick here,
just a way to look around a commit's tree without leaving the log view.
"""

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label, Static

import pyjj

# Binary/very large files aren't worth dumping into the pane.
_MAX_PREVIEW_BYTES = 512 * 1024


class _FileTable(DataTable):
    """`j`/`k` alongside `DataTable`'s own up/down, `l` to move focus into
    the content pane -- same hjkl convention as `LogView`/`Preview` and
    `OpLogScreen`'s `_OpTable`/`DiffPane`.
    """

    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("l", "focus_content", "View", show=False),
    ]

    def action_focus_content(self) -> None:
        self.screen.query_one(ContentPane).focus()


class ContentPane(VerticalScroll):
    """Shows whichever file `FilesScreen` last highlighted. `h` moves focus
    back to the table -- see `_FileTable`'s matching `l` binding.
    """

    BINDINGS = [
        Binding("j", "scroll_down", show=False),
        Binding("k", "scroll_up", show=False),
        Binding("h", "focus_table", "Files", show=False),
    ]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._body = Static()

    def compose(self) -> ComposeResult:
        yield self._body

    def show_file(self, path: str, text: str) -> None:
        body = Text()
        body.append(f"{path}\n\n", style="bold cyan")
        body.append(text)
        self._body.update(body)

    def action_focus_table(self) -> None:
        self.screen.query_one(_FileTable).focus()


class FilesScreen(ModalScreen[None]):
    """Browses `commit`'s file tree. Always dismisses with `None`."""

    DEFAULT_CSS = """
    FilesScreen {
        align: center middle;
    }
    FilesScreen > Vertical {
        width: 95%;
        height: 90%;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    FilesScreen Horizontal {
        height: 1fr;
        margin-top: 1;
    }
    FilesScreen _FileTable {
        width: 40%;
    }
    FilesScreen ContentPane {
        width: 60%;
        border-left: solid $border-blurred;
        padding-left: 1;
    }
    FilesScreen ContentPane:focus {
        border-left: solid $border;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, commit: pyjj.Commit) -> None:
        super().__init__()
        self._commit = commit
        self._paths = sorted(commit.list_files())

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(
                f"Files in {self._commit.change_id.hex()[:8]} -- escape to close"
            )
            with Horizontal():
                table = _FileTable(cursor_type="row", show_header=False)
                table.add_column("path", key="path")
                yield table
                yield ContentPane()

    def on_mount(self) -> None:
        table = self.query_one(_FileTable)
        for path in self._paths:
            table.add_row(path, key=path)
        if self._paths:
            table.move_cursor(row=0)
            self._show_file(0)
        table.focus()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row is not None:
            self._show_file(event.cursor_row)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _show_file(self, index: int) -> None:
        path = self._paths[index]
        self.query_one(ContentPane).show_file(path, _read_text(self._commit, path))


def _read_text(commit: pyjj.Commit, path: str) -> str:
    try:
        data = commit.read_file(path)
    except pyjj.JjError:
        return "(unreadable file -- symlink, conflict, or submodule)"
    if len(data) > _MAX_PREVIEW_BYTES:
        return "(file too large to preview)"
    return data.decode("utf-8", errors="replace")
