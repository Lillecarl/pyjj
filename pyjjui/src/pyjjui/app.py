"""The Textual `App` tying state, widgets, and keybindings together."""

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header

import pyjj

from . import mutations
from .screens.confirm import ConfirmScreen
from .screens.text_input import TextInputScreen
from .state import AppState
from .widgets.log_view import LogView
from .widgets.preview import Preview


class PyjjuiApp(App[None]):
    TITLE = "pyjjui"
    # Textual's default ctrl+p command palette isn't wired to anything here
    # (no custom Provider) and its footer entry crowds out the real
    # keybindings at 80 columns, garbling the footer -- found via the
    # `render` test fixture, not a real terminal.
    ENABLE_COMMAND_PALETTE = False

    CSS = """
    Horizontal > LogView {
        width: 60%;
    }
    Horizontal > Preview {
        width: 40%;
        border-left: solid $accent;
    }
    """

    BINDINGS = [
        Binding("n", "new_child", "New"),
        Binding("e", "edit", "Edit"),
        Binding("d", "describe", "Describe"),
        Binding("a", "abandon", "Abandon"),
        Binding("u", "undo", "Undo"),
        Binding("U", "redo", "Redo"),
        Binding("r", "set_revset", "Revset"),
        Binding("R", "refresh_log", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self, workspace: pyjj.Workspace, settings: pyjj.UserSettings, revset: str
    ) -> None:
        super().__init__()
        repo = workspace.load_at_head()
        self.state = AppState(workspace=workspace, settings=settings, repo=repo, revset=revset)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield LogView()
            yield Preview()
        yield Footer()

    async def on_mount(self) -> None:
        await self.action_refresh_log()

    async def action_refresh_log(self) -> None:
        nodes = await self.state.refresh()
        wc_commit = self.state.repo.resolve_single(self.state.settings, "@")
        self.query_one(LogView).update_nodes(nodes, wc_commit.id)
        self.sub_title = self.state.revset

    def on_log_view_commit_selected(self, event: LogView.CommitSelected) -> None:
        self.query_one(Preview).show_commit(event.commit, self.state.repo)

    async def action_new_child(self) -> None:
        commit = self.query_one(LogView).selected_commit
        if commit is None:
            return
        await self.state.run_mutation(mutations.new_child, commit)
        await self.action_refresh_log()

    async def action_edit(self) -> None:
        commit = self.query_one(LogView).selected_commit
        if commit is None:
            return
        await self.state.run_mutation(mutations.edit, commit)
        await self.action_refresh_log()

    @work
    async def action_describe(self) -> None:
        commit = self.query_one(LogView).selected_commit
        if commit is None:
            return
        text = await self.push_screen_wait(
            TextInputScreen("New description:", commit.description)
        )
        if text is None:
            return
        await self.state.run_mutation(mutations.describe, commit, text)
        await self.action_refresh_log()

    @work
    async def action_abandon(self) -> None:
        commit = self.query_one(LogView).selected_commit
        if commit is None:
            return
        confirmed = await self.push_screen_wait(
            ConfirmScreen(f"Abandon {commit.change_id.hex()[:8]}?")
        )
        if not confirmed:
            return
        await self.state.run_mutation(mutations.abandon, commit)
        await self.action_refresh_log()

    async def action_undo(self) -> None:
        await self.state.run_mutation(mutations.undo)
        await self.action_refresh_log()

    async def action_redo(self) -> None:
        await self.state.run_mutation(mutations.redo)
        await self.action_refresh_log()

    @work
    async def action_set_revset(self) -> None:
        revset = await self.push_screen_wait(
            TextInputScreen("Revset:", self.state.revset)
        )
        if revset is None:
            return
        self.state.revset = revset
        await self.action_refresh_log()
