"""A generic yes/no confirmation modal, used before every mutation that
touches an existing commit (see `AppState.should_confirm()`/`app.py`'s
`_confirm()` helper).
"""

from dataclasses import dataclass

from rich.console import RenderableType
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Label, Static


@dataclass
class ConfirmResult:
    """`confirmed` is the yes/no answer. `remember` is `None` unless
    `confirmed` is `True` and a "don't ask again" box was checked --
    `"session"` (until the app quits) or `"ever"` (persisted, see
    `pyjjui.config`).
    """

    confirmed: bool
    remember: str | None = None


class ConfirmScreen(ModalScreen[ConfirmResult]):
    """Dismisses with a `ConfirmResult`."""

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }
    ConfirmScreen > Vertical {
        width: 60%;
        height: auto;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    ConfirmScreen Checkbox {
        width: auto;
        border: none;
        padding-top: 1;
    }
    ConfirmScreen Horizontal {
        height: auto;
        align: right middle;
        padding-top: 1;
    }
    ConfirmScreen #detail {
        height: 15;
        border: round $border-blurred;
        padding: 0 1;
        margin-top: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        message: str,
        remember_key: str | None = None,
        detail: RenderableType | None = None,
    ) -> None:
        super().__init__()
        self._message = message
        self._remember_key = remember_key
        self._detail = detail

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._message)
            if self._detail is not None:
                with VerticalScroll(id="detail"):
                    yield Static(self._detail)
            if self._remember_key is not None:
                yield Checkbox("Don't ask again this session", id="remember-session")
                yield Checkbox("Don't ask again ever", id="remember-ever")
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Confirm", id="confirm", variant="error")

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        # Mutually exclusive: "ever" already implies "session", so checking
        # one un-checks the other rather than letting both be checked
        # (which would carry no extra meaning over "ever" alone).
        if not event.value or self._remember_key is None:
            return
        other_id = "remember-ever" if event.checkbox.id == "remember-session" else "remember-session"
        other = self.query_one(f"#{other_id}", Checkbox)
        if other.value:
            other.value = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        confirmed = event.button.id == "confirm"
        remember = None
        if confirmed and self._remember_key is not None:
            if self.query_one("#remember-ever", Checkbox).value:
                remember = "ever"
            elif self.query_one("#remember-session", Checkbox).value:
                remember = "session"
        self.dismiss(ConfirmResult(confirmed, remember))

    def action_cancel(self) -> None:
        self.dismiss(ConfirmResult(False))
