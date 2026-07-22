"""Modal for picking a `jj rebase` mode: marked commits are the source
(`LogView.marked_commits`), the cursor commit is the destination -- this
screen just asks *how* the source should land there.
"""

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Label

import pyjj


@dataclass
class RebasePlan:
    """What `RebaseScreen` dismisses with -- `mutations.rebase`'s `mode`/
    `include_descendants` args, chosen interactively instead of via CLI flags.
    """

    mode: str  # "onto" | "after" | "before"
    include_descendants: bool


class RebaseScreen(ModalScreen[RebasePlan | None]):
    """Dismisses with a `RebasePlan`, or `None` if cancelled."""

    DEFAULT_CSS = """
    RebaseScreen {
        align: center middle;
    }
    RebaseScreen > Vertical {
        width: 90%;
        height: auto;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    RebaseScreen Horizontal {
        height: auto;
        align: right middle;
        padding-top: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, sources: list[pyjj.Commit], destination: pyjj.Commit) -> None:
        super().__init__()
        self._sources = sources
        self._destination = destination

    def compose(self) -> ComposeResult:
        source_desc = ", ".join(c.change_id.hex()[:8] for c in self._sources)
        dest_desc = self._destination.change_id.hex()[:8]
        with Vertical():
            yield Label(f"Rebase {source_desc}")
            yield Label(f"relative to {dest_desc}")
            yield Checkbox(
                "Include descendants of source (-s)", id="include-descendants"
            )
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Before (-B)", id="before")
                yield Button("After (-A)", id="after")
                yield Button("Onto (-d)", id="onto", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        include_descendants = self.query_one(Checkbox).value
        self.dismiss(RebasePlan(mode=event.button.id, include_descendants=include_descendants))

    def action_cancel(self) -> None:
        self.dismiss(None)
