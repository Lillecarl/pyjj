"""Modal for arranging a target set `jj arrange` style: reorder commits
with swaps and mark some abandoned, then confirm once for the whole
batch. See `mutations.arrange()` for the actual graph surgery and
`arrange_plan.ArrangeState` for the plan model this drives.
"""

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Label

import pyjj
from pyjjui.arrange_plan import ArrangeState, PlanEntry


class ArrangeScreen(ModalScreen[list[PlanEntry] | None]):
    """Dismisses with the arrange plan, or `None` if cancelled.

    Rows follow the state's display order (children first); the
    action column shows `abandon` on marked rows. Context commits
    (parents/children outside the target set) stay in the model for
    the swap guards but are never shown and never reach the plan --
    the table is the target set only.
    """

    DEFAULT_CSS = """
    ArrangeScreen {
        align: center middle;
    }
    ArrangeScreen > Vertical {
        width: 80%;
        height: auto;
        max-height: 85%;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    ArrangeScreen DataTable {
        height: auto;
        max-height: 20;
    }
    """

    BINDINGS = [
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("J", "swap_down", "Swap down"),
        ("K", "swap_up", "Swap up"),
        ("a", "abandon", "Abandon"),
        ("p", "keep", "Keep"),
        ("c", "confirm", "Confirm"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self, state: ArrangeState, commits: dict[str, pyjj.Commit]
    ) -> None:
        super().__init__()
        self._state = state
        self._commits = commits
        self._rows: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Arrange -- swaps reorder, abandon drops on confirm")
            yield DataTable(cursor_type="row", show_header=True)
            yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("change", key="change")
        table.add_column("description", key="description")
        table.add_column("parents", key="parents")
        table.add_column("action", key="action")
        table.focus()
        self._redraw()

    def _redraw(self, keep: str | None = None) -> None:
        """Rebuild every row from the state -- arrange sets are small
        (a mutable stack, not a whole log), so a full rebuild per key
        press is cheaper than targeted cell updates here."""
        table = self.query_one(DataTable)
        selected = keep if keep in self._rows else None
        if selected is None and self._rows and table.cursor_row < len(self._rows):
            selected = self._rows[table.cursor_row]
        table.clear()
        self._rows = [
            id for id in self._state.order if id not in self._state.external
        ]
        for id in self._rows:
            commit = self._commits[id]
            parents = ", ".join(
                self._short_change(p) for p in self._state.parents[id]
            )
            table.add_row(
                commit.change_id.hex()[:8],
                commit.description.split("\n", 1)[0],
                parents,
                "abandon" if id in self._state.abandoned else "",
            )
        if selected in self._rows:
            table.move_cursor(row=self._rows.index(selected))
        elif self._rows:
            table.move_cursor(row=0)

    def _short_change(self, id: str) -> str:
        commit = self._commits.get(id)
        if commit is None:
            return id[:8]
        return commit.change_id.hex()[:8]

    def _cursor_id(self) -> str | None:
        table = self.query_one(DataTable)
        if not self._rows or table.cursor_row >= len(self._rows):
            return None
        return self._rows[table.cursor_row]

    def action_cursor_down(self) -> None:
        self.query_one(DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one(DataTable).action_cursor_up()

    def action_swap_down(self) -> None:
        """Swap with the parent (`J`), moving down the stack."""
        id = self._cursor_id()
        if id is None:
            return
        if not self._state.swap_with_parent(id):
            self.app.notify(
                "Swap needs exactly one editable parent",
                title="Cannot swap",
                severity="warning",
            )
            return
        self._redraw(keep=id)

    def action_swap_up(self) -> None:
        """Swap with the child (`K`), moving up the stack."""
        id = self._cursor_id()
        if id is None:
            return
        if not self._state.swap_with_child(id):
            self.app.notify(
                "Swap needs exactly one editable child",
                title="Cannot swap",
                severity="warning",
            )
            return
        self._redraw(keep=id)

    def action_abandon(self) -> None:
        id = self._cursor_id()
        if id is None:
            return
        self._state.set_abandoned(id, True)
        self._redraw(keep=id)

    def action_keep(self) -> None:
        id = self._cursor_id()
        if id is None:
            return
        self._state.set_abandoned(id, False)
        self._redraw(keep=id)

    def action_confirm(self) -> None:
        try:
            plan = self._state.to_plan()
        except ValueError as exc:
            self.app.notify(str(exc), title="Cannot arrange", severity="error")
            return
        self.dismiss(plan)

    def action_cancel(self) -> None:
        self.dismiss(None)


def describe_plan(
    commits: dict[str, pyjj.Commit], plan: list[PlanEntry]
) -> str:
    """One line per plan entry for the confirm gate: what moves where,
    and what goes. Parent changes read as change-id pairs, so a swap
    shows as two mirrored moves."""
    lines = []
    for entry in plan:
        commit = commits[entry.id]
        short = commit.change_id.hex()[:8]
        first = commit.description.split("\n", 1)[0]
        if entry.abandon:
            lines.append(f"abandon {short} {first}")
            continue
        dest = ", ".join(_change_of(commits, p) for p in entry.parents)
        lines.append(f"rebase {short} onto {dest} ({first})")
    return "\n".join(lines)


def _change_of(commits: dict[str, pyjj.Commit], id: str) -> str:
    commit = commits.get(id)
    if commit is None:
        return id[:8]
    return commit.change_id.hex()[:8]
