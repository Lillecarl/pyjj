"""Modal file browser for one commit's tree -- lists every path via
`Commit.list_files()` beside a pane for whichever one is highlighted,
either its raw content or (`d`) its diff against the current working
copy. `r` restores the highlighted file from this commit into the
working copy (`mutations.restore_file()`), gated by the same
confirm/"don't ask again" machinery as every other mutation -- the one
mutating action in here, everything else is look-around.
"""

from rich.console import Group, RenderableType
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Label, Static

import pyjj

from .. import mutations
from ..render.diff import render_file_diff

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
    """Shows whichever file `FilesScreen` last highlighted, in whichever
    mode (raw content or diff) is currently active. `h` moves focus back
    to the table -- see `_FileTable`'s matching `l` binding.
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

    def show(self, header: str, body: RenderableType) -> None:
        self._body.update(Group(Text(header, style="bold cyan"), Text(), body))

    def action_focus_table(self) -> None:
        self.screen.query_one(_FileTable).focus()


class FilesScreen(ModalScreen[None]):
    """Browses `commit`'s file tree. Always dismisses with `None` -- even
    `r` (restore) doesn't close it, since restoring one file and then
    continuing to look around is the expected flow.
    """

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

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("d", "toggle_diff", "Diff vs working copy"),
        Binding("r", "restore_file", "Restore into working copy"),
    ]

    def __init__(self, commit: pyjj.Commit) -> None:
        super().__init__()
        self._commit = commit
        self._paths = sorted(commit.list_files())
        self._diff_mode = False
        self._current_index = 0

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"Files in {self._commit.change_id.hex()[:8]}")
            with Horizontal():
                table = _FileTable(cursor_type="row", show_header=False)
                table.add_column("path", key="path")
                yield table
                yield ContentPane()
            yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(_FileTable)
        for path in self._paths:
            table.add_row(path, key=path)
        if self._paths:
            table.move_cursor(row=0)
            self._show_at(0)
        table.focus()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row is not None:
            self._show_at(event.cursor_row)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_toggle_diff(self) -> None:
        if not self._paths:
            return
        self._diff_mode = not self._diff_mode
        self._show_at(self._current_index)

    @work
    async def action_restore_file(self) -> None:
        if not self._paths:
            return
        path = self._paths[self._current_index]
        app = self.app
        wc_commit = app.state.repo.resolve_single(app.state.settings, "@")
        if self._commit.id == wc_commit.id:
            app.notify(
                "This commit is already the working copy",
                title="Nothing to restore",
                severity="warning",
            )
            return
        prompt = (
            f"Restore {path!r} from {self._commit.change_id.hex()[:8]} into"
            " the working copy?"
        )
        detail = render_file_diff(self._commit, wc_commit, path)
        if not await app._confirm("restore_file", prompt, detail=detail):
            return
        if await app._run_mutation(mutations.restore_file, self._commit, path):
            await app.action_refresh_log()
            self._show_at(self._current_index)

    def _show_at(self, index: int) -> None:
        self._current_index = index
        path = self._paths[index]
        pane = self.query_one(ContentPane)
        if self._diff_mode:
            app = self.app
            wc_commit = app.state.repo.resolve_single(app.state.settings, "@")
            pane.show(
                f"{path} (diff vs working copy)",
                render_file_diff(self._commit, wc_commit, path),
            )
        else:
            pane.show(path, Text(_read_text(self._commit, path)))


def _read_text(commit: pyjj.Commit, path: str) -> str:
    try:
        data = commit.read_file(path)
    except pyjj.JjError:
        return "(unreadable file -- symlink, conflict, or submodule)"
    if len(data) > _MAX_PREVIEW_BYTES:
        return "(file too large to preview)"
    return data.decode("utf-8", errors="replace")
