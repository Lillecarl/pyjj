"""Modal for `jj split`: choose which changed paths go into the first
(split-out) commit -- everything else becomes a second commit, a child of
the first. See `mutations.split()` for the actual graph surgery.
"""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, SelectionList


class _PathList(SelectionList):
    """`j`/`k` alongside `SelectionList`'s own up/down -- `space` (already
    bound by `SelectionList` itself) toggles a path.
    """

    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
    ]


class SplitScreen(ModalScreen[list[str] | None]):
    """Dismisses with the paths chosen for the first commit, or `None`."""

    DEFAULT_CSS = """
    SplitScreen {
        align: center middle;
    }
    SplitScreen > Vertical {
        width: 70%;
        height: auto;
        max-height: 80%;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    SplitScreen SelectionList {
        height: auto;
        max-height: 15;
    }
    SplitScreen Horizontal {
        height: auto;
        align: right middle;
        padding-top: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, paths: list[str]) -> None:
        super().__init__()
        self._paths = paths

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Select paths for the first commit -- space to toggle")
            yield _PathList(*[(path, path) for path in self._paths])
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Split", id="split", variant="primary")

    def on_mount(self) -> None:
        self.query_one(_PathList).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        self.dismiss(list(self.query_one(_PathList).selected))

    def action_cancel(self) -> None:
        self.dismiss(None)
