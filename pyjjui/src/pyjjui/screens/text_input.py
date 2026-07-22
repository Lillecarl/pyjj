"""A generic single-line text input modal, used for `describe` and the
revset filter prompt.
"""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class TextInputScreen(ModalScreen[str | None]):
    """Dismisses with the submitted text, or `None` if cancelled (Escape)."""

    DEFAULT_CSS = """
    TextInputScreen {
        align: center middle;
    }
    TextInputScreen > Vertical {
        width: 60%;
        height: auto;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str, initial_value: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._initial_value = initial_value

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._prompt)
            yield Input(value=self._initial_value)

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)
