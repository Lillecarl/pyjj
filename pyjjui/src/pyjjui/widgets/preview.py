"""Preview pane: metadata + diff-against-first-parent for the selected commit."""

from rich.console import Group
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

import pyjj

from ..render.diff import render_commit_diff


class Preview(VerticalScroll):
    """Shows the selected commit's metadata and diff against its first parent."""

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
