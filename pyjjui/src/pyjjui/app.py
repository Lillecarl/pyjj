"""The Textual `App` tying state, widgets, and keybindings together."""

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header

import pyjj

from . import mutations
from .screens.confirm import ConfirmScreen
from .screens.rebase import RebaseScreen
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
        /* $border/$border-blurred + the background-tint: same focus
           convention Textual's own Input/DataTable use, not one invented
           here -- respects whatever theme (dark/light/custom) is active
           instead of a hardcoded color pair. */
        border-left: solid $border-blurred;
    }
    Horizontal > Preview:focus {
        border-left: solid $border;
        background-tint: $foreground 5%;
    }
    """

    BINDINGS = [
        Binding("n", "new_child", "New"),
        Binding("e", "edit", "Edit"),
        Binding("d", "describe", "Describe"),
        Binding("a", "abandon", "Abandon"),
        Binding("m", "rebase", "Rebase"),
        Binding("b", "bookmark_set", "Bookmark"),
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

    async def action_refresh_log(self) -> bool:
        """Reload the repo and redraw the log. Returns whether it succeeded --
        callers that need to undo a state change on failure (e.g.
        `action_set_revset` reverting to the last-good revset) check this;
        others just fire-and-forget it.
        """
        try:
            nodes = await self.state.refresh()
        except pyjj.JjError as exc:
            self.notify(str(exc), title="Refresh failed", severity="error", timeout=8)
            return False
        wc_commit = self.state.repo.resolve_single(self.state.settings, "@")
        bookmarks = self.state.repo.bookmarks()
        self.query_one(LogView).update_nodes(nodes, wc_commit.id, bookmarks)
        self.sub_title = self.state.revset
        return True

    async def _run_mutation(self, fn: object, *args: object) -> bool:
        """Run a mutation, notifying and swallowing failure instead of
        crashing the whole app -- jj operations fail for user-reachable
        reasons (nothing to undo, describing an immutable commit, etc.),
        not just programming errors, so this boundary needs to survive them.
        """
        try:
            await self.state.run_mutation(fn, *args)
        except pyjj.JjError as exc:
            self.notify(str(exc), title="Action failed", severity="error", timeout=8)
            return False
        return True

    def on_log_view_commit_selected(self, event: LogView.CommitSelected) -> None:
        self.query_one(Preview).show_commit(event.commit, self.state.repo)

    def on_log_view_focus_preview(self, event: LogView.FocusPreview) -> None:
        self.query_one(Preview).focus()

    def on_preview_focus_log(self, event: Preview.FocusLog) -> None:
        self.query_one(LogView).focus()

    async def action_new_child(self) -> None:
        """`n` -- new commit on top of the cursor commit, or a merge commit
        if 2+ commits are marked (LogView.selection covers both).
        """
        log_view = self.query_one(LogView)
        parents = log_view.selection
        if not parents:
            return
        if await self._run_mutation(mutations.new_child, parents):
            log_view.action_clear_marks()
            await self.action_refresh_log()

    async def action_edit(self) -> None:
        commit = self.query_one(LogView).selected_commit
        if commit is None:
            return
        if await self._run_mutation(mutations.edit, commit):
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
        if await self._run_mutation(mutations.describe, commit, text):
            await self.action_refresh_log()

    @work
    async def action_abandon(self) -> None:
        log_view = self.query_one(LogView)
        commits = log_view.selection
        if not commits:
            return
        if len(commits) > 1:
            prompt = f"Abandon {len(commits)} commits?"
        else:
            prompt = f"Abandon {commits[0].change_id.hex()[:8]}?"
        confirmed = await self.push_screen_wait(ConfirmScreen(prompt))
        if not confirmed:
            return
        if await self._run_mutation(mutations.abandon, commits):
            log_view.action_clear_marks()
            await self.action_refresh_log()

    @work
    async def action_rebase(self) -> None:
        """`m` -- rebase the marked commits (`space`) onto/around the
        cursor commit. Marks stay the *source* here (never falling back to
        the cursor the way `LogView.selection` does for abandon/new-child)
        because the cursor is needed free, to pick the destination.
        """
        log_view = self.query_one(LogView)
        sources = log_view.marked_commits
        if not sources:
            self.notify(
                "Mark commits to rebase first (space), then move the cursor"
                " to the destination and press m",
                title="Nothing marked",
                severity="warning",
            )
            return
        destination = log_view.selected_commit
        if destination is None:
            return
        plan = await self.push_screen_wait(RebaseScreen(sources, destination))
        if plan is None:
            return
        if await self._run_mutation(
            mutations.rebase, sources, destination, plan.mode, plan.include_descendants
        ):
            log_view.action_clear_marks()
            await self.action_refresh_log()

    async def action_undo(self) -> None:
        if await self._run_mutation(mutations.undo):
            await self.action_refresh_log()

    async def action_redo(self) -> None:
        if await self._run_mutation(mutations.redo):
            await self.action_refresh_log()

    @work
    async def action_set_revset(self) -> None:
        revset = await self.push_screen_wait(
            TextInputScreen("Revset:", self.state.revset)
        )
        if revset is None:
            return
        previous_revset = self.state.revset
        self.state.revset = revset
        if not await self.action_refresh_log():
            self.state.revset = previous_revset

    @work
    async def action_bookmark_set(self) -> None:
        commit = self.query_one(LogView).selected_commit
        if commit is None:
            return
        name = await self.push_screen_wait(TextInputScreen("Bookmark name:"))
        if not name:
            return
        if await self._run_mutation(mutations.set_bookmark, commit, name):
            await self.action_refresh_log()
