"""Preview pane: metadata + diff-against-first-parent for the selected commit."""

from rich.console import Group
from rich.text import Text
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Static

import pyjj

from ..render.diff import render_commit_diff


class Preview(VerticalScroll):
    """Shows the selected commit's metadata and diff against its first parent."""

    # `j`/`k` scroll the diff the same direction they'd move the log
    # selection; `h` mirrors LogView's `l` binding to move focus back the
    # other way -- see LogView's BINDINGS docstring for why this differs
    # from jjui's own open/close-a-panel meaning for the same keys.
    BINDINGS = [
        Binding("j", "scroll_down", show=False),
        Binding("k", "scroll_up", show=False),
        Binding("h", "focus_log", "Log", show=False),
    ]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._body = Static()

    def compose(self):
        yield self._body

    def show_commit(self, commit: pyjj.Commit, repo: pyjj.ReadonlyRepo) -> None:
        header = Text()
        header.append(f"{commit.change_id.hex()[:12]} ", style="bold cyan")
        header.append(f"{commit.id.hex()[:12]}\n", style="dim")
        header.append(f"{commit.author.name} <{commit.author.email}>\n", style="italic")
        header.append(f"{commit.description or '(no description set)'}\n")

        if not commit.parent_ids:
            self._body.update(header)
            return

        parent = repo.get_commit(commit.parent_ids[0])
        self._body.update(Group(header, Text(), render_commit_diff(commit, parent)))

    def action_focus_log(self) -> None:
        from .log_view import LogView  # local import: avoids a LogView<->Preview import cycle

        self.screen.query_one(LogView).focus()
