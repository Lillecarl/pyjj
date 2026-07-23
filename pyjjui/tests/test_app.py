"""Interaction tests for `PyjjuiApp`, driven via Textual's Pilot."""

from pathlib import Path

from textual.coordinate import Coordinate
from textual.widgets import Checkbox, DataTable, Input, SelectionList

from pyjjui import config
from pyjjui.screens.files import ContentPane
from pyjjui.screens.oplog import DiffPane
from pyjjui.widgets.log_view import LogView
from pyjjui.widgets.preview import Preview

from . import testutils


def _row_of(log_view: LogView, change_id) -> int:
    return next(i for i, commit in enumerate(log_view._commits) if commit.change_id == change_id)


def _pane_text(pane) -> str:
    """Reads back a `Static`-backed pane's rendered lines -- there's no
    public way to get plain text out of a mounted `Static` short of
    rendering it line by line the way the compositor would.
    """
    body = pane._body
    return "\n".join(body.render_line(y).text for y in range(body.size.height))


async def test_log_view_shows_the_seeded_commits(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        render(app)
        log_view = app.query_one(LogView)
        descriptions = {c.description for c in log_view._commits}
        assert {"A", "B"} <= descriptions


async def test_new_child_creates_a_commit_and_it_appears_after_refresh(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        before = log_view.row_count
        render(app, "before")

        await pilot.press("n")
        await pilot.pause()
        render(app, "after")

        assert log_view.row_count == before + 1


async def test_undo_after_a_mutation_restores_prior_state(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        before = log_view.row_count

        await pilot.press("n")
        await pilot.pause()
        assert log_view.row_count == before + 1

        await pilot.press("u")
        await pilot.pause()
        render(app, "after-undo")
        assert log_view.row_count == before


async def test_navigation_keeps_a_valid_selection(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)

        await pilot.press("down")
        await pilot.pause()
        render(app, "after-down")

        assert log_view.selected_commit is not None


async def test_jk_move_the_log_selection_same_as_arrows(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)

        await pilot.press("j")
        await pilot.pause()
        after_j = log_view.selected_commit
        render(app, "after-j")
        assert after_j is not None

        await pilot.press("k")
        await pilot.pause()
        render(app, "after-k")

        assert log_view.selected_commit == log_view._commits[0]
        assert after_j == log_view._commits[1]


async def test_l_and_h_move_focus_between_log_and_preview(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        preview = app.query_one(Preview)
        assert log_view.has_focus

        await pilot.press("l")
        await pilot.pause()
        render(app, "focus-preview")
        assert preview.has_focus

        await pilot.press("h")
        await pilot.pause()
        render(app, "focus-log")
        assert log_view.has_focus


async def test_jk_scroll_the_preview_pane_once_focused(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        preview = app.query_one(Preview)

        await pilot.press("l")
        await pilot.pause()
        assert preview.has_focus

        # Nothing to assert about scroll *position* with this little content
        # in the seeded demo repo -- this is really about `j`/`k` reaching
        # Preview's scroll actions at all (and not, say, leaking through to
        # LogView) without raising.
        await pilot.press("j")
        await pilot.press("k")
        await pilot.pause()
        render(app, "after-jk-scroll")


async def test_invalid_revset_shows_an_error_instead_of_crashing(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        before_count = log_view.row_count
        before_revset = app.state.revset

        await pilot.press("r")
        await pilot.pause()
        app.screen.query_one(Input).value = 'file("flake.nix")'
        await pilot.press("enter")
        await pilot.pause()
        render(app, "after-bad-revset")

        # The app is still alive and usable, showing an error notification
        # rather than a traceback, and reverted to the last-good revset
        # instead of getting stuck on one that always fails to parse.
        assert app.state.revset == before_revset
        assert log_view.row_count == before_count
        assert len(app._notifications) >= 1


async def test_bookmark_set_creates_a_named_bookmark(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        await pilot.press("down")  # move onto A, away from the working copy
        await pilot.pause()
        target = log_view.selected_commit

        await pilot.press("b")
        await pilot.pause()
        app.screen.query_one(Input).value = "release"
        await pilot.press("enter")
        await pilot.pause()
        render(app, "after-bookmark-set")

        bookmark = app.state.repo.get_bookmark("release")
        assert bookmark is not None
        assert bookmark.target_ids == [target.id]


async def test_space_marks_the_cursor_commit_shown_with_a_checkmark(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        target = log_view.selected_commit

        await pilot.press("space")
        await pilot.pause()
        render(app, "after-mark")

        assert log_view.selection == [target]


async def test_space_again_unmarks_the_commit(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        cursor_commit = log_view.selected_commit

        await pilot.press("space")
        await pilot.press("space")
        await pilot.pause()
        render(app, "after-toggle-off")

        # With nothing marked, selection() falls back to the cursor commit --
        # same as if space had never been pressed.
        assert log_view.selection == [cursor_commit]


async def test_escape_clears_all_marks(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)

        await pilot.press("space")
        await pilot.press("down")
        await pilot.press("space")
        await pilot.pause()
        assert len(log_view.selection) == 2

        await pilot.press("escape")
        await pilot.pause()
        render(app, "after-clear-marks")

        assert len(log_view.selection) == 1


async def test_marking_two_commits_and_pressing_n_creates_a_merge_commit(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        before = log_view.row_count

        await pilot.press("space")
        first = log_view.selected_commit
        await pilot.press("down")
        await pilot.press("space")
        second = log_view.selected_commit
        await pilot.pause()
        render(app, "two-marked")

        await pilot.press("n")
        await pilot.pause()
        render(app, "after-merge")

        assert log_view.row_count == before + 1
        new_wc = app.state.repo.resolve_single(app.state.settings, "@")
        assert set(new_wc.parent_ids) == {first.id, second.id}
        # Creating the merge commit clears the marks that fed it.
        assert log_view.selection == [log_view.selected_commit]


async def test_marking_two_commits_and_abandoning_removes_both(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        before = log_view.row_count

        await pilot.press("down")  # off the working copy, onto A
        await pilot.press("space")
        first = log_view.selected_commit
        await pilot.press("down")
        await pilot.press("space")
        second = log_view.selected_commit
        await pilot.pause()

        await pilot.press("a")
        await pilot.pause()
        render(app, "confirm-multi-abandon")
        await pilot.click("#confirm")
        await pilot.pause()
        render(app, "after-multi-abandon")

        assert log_view.row_count == before - 2
        remaining_ids = {c.id for c in log_view._commits}
        assert first.id not in remaining_ids
        assert second.id not in remaining_ids


async def test_rebase_without_marks_shows_a_warning_instead_of_a_modal(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()

        await pilot.press("m")
        await pilot.pause()
        render(app, "no-marks-warning")

        assert len(app.screen_stack) == 1  # no modal pushed
        assert len(app._notifications) >= 1


async def test_rebase_onto_reparents_the_marked_commit(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)

        a = app.state.repo.resolve_single(app.state.settings, "description(exact:'A')")
        root = app.state.repo.get_commit(a.parent_ids[0])
        new_repo, c = testutils.new_child(
            app.state.workspace, app.state.repo, app.state.settings, root, "C"
        )
        app.state.repo = new_repo
        await app.action_refresh_log()
        await pilot.pause()

        b = app.state.repo.resolve_single(app.state.settings, "description(exact:'B')")
        log_view.move_cursor(row=_row_of(log_view, c.change_id))
        await pilot.press("space")
        log_view.move_cursor(row=_row_of(log_view, b.change_id))
        await pilot.pause()
        render(app, "marked-c-cursor-on-b")

        await pilot.press("m")
        await pilot.pause()
        render(app, "rebase-modal")
        await pilot.click("#onto")
        await pilot.pause()
        render(app, "rebase-confirm")
        await pilot.click("#confirm")
        await pilot.pause()
        render(app, "after-rebase-onto")

        rebased_c = app.state.repo.revset(app.state.settings, "description(exact:'C')")[0]
        assert rebased_c.parent_ids == [b.id]
        assert log_view.selection == [log_view.selected_commit]  # marks cleared


async def test_rebase_modal_cancel_leaves_history_unchanged(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        before = log_view.row_count

        await pilot.press("space")  # mark the working copy commit
        await pilot.press("down")
        await pilot.pause()

        await pilot.press("m")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        render(app, "after-cancel")

        assert log_view.row_count == before


async def test_abandon_requires_confirmation(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        before = log_view.row_count

        await pilot.press("a")
        await pilot.pause()
        render(app, "confirm-modal")
        # A confirmation modal should now be on the screen stack; cancel it.
        await pilot.press("escape")
        await pilot.pause()

        assert log_view.row_count == before


async def test_s_squashes_the_cursor_commit_into_its_parent(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        before = log_view.row_count

        a = app.state.repo.resolve_single(app.state.settings, "description(exact:'A')")
        # Squashing @ itself would spawn a fresh empty child in its place
        # (net row count unchanged) -- move the cursor onto A instead.
        log_view.move_cursor(row=_row_of(log_view, a.change_id))
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()
        render(app, "squash-confirm")
        assert app.screen.query_one("#detail") is not None  # diff preview, not just the bare prompt
        await pilot.click("#confirm")
        await pilot.pause()
        render(app, "after-squash")

        assert log_view.row_count == before - 1
        # A's own commit disappears -- checking by description would false-
        # positive, since the squashed-into destination inherits A's message
        # (destination had none of its own).
        visible_ids = {c.id for c in app.state.repo.revset(app.state.settings, "all()")}
        assert a.id not in visible_ids


async def test_y_duplicates_the_cursor_commit(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        before = log_view.row_count

        a = app.state.repo.resolve_single(app.state.settings, "description(exact:'A')")
        log_view.move_cursor(row=_row_of(log_view, a.change_id))
        await pilot.pause()

        await pilot.press("y")
        await pilot.pause()
        render(app, "duplicate-confirm")
        await pilot.click("#confirm")
        await pilot.pause()
        render(app, "after-duplicate")

        assert log_view.row_count == before + 1
        duplicates = app.state.repo.revset(app.state.settings, "description(exact:'A')")
        assert len(duplicates) == 2


async def test_y_duplicates_all_marked_commits(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        before = log_view.row_count

        a = app.state.repo.resolve_single(app.state.settings, "description(exact:'A')")
        b = app.state.repo.resolve_single(app.state.settings, "description(exact:'B')")
        log_view.move_cursor(row=_row_of(log_view, a.change_id))
        await pilot.press("space")
        log_view.move_cursor(row=_row_of(log_view, b.change_id))
        await pilot.press("space")
        await pilot.pause()

        await pilot.press("y")
        await pilot.pause()
        render(app, "duplicate-multi-confirm")
        await pilot.click("#confirm")
        await pilot.pause()
        render(app, "after-duplicate-multi")

        assert log_view.row_count == before + 2
        assert log_view.selection == [log_view.selected_commit]  # marks cleared


async def test_o_restores_to_a_past_operation(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        before = log_view.row_count

        a = app.state.repo.resolve_single(app.state.settings, "description(exact:'A')")
        log_view.move_cursor(row=_row_of(log_view, a.change_id))
        await pilot.press("space")
        await pilot.press("a")
        await pilot.pause()
        await pilot.click("#confirm")
        await pilot.pause()
        assert log_view.row_count == before - 1

        await pilot.press("o")
        await pilot.pause()
        render(app, "oplog-modal")
        table = app.screen.query_one(DataTable)
        table.move_cursor(row=1)  # the operation right before the abandon
        await pilot.press("enter")
        await pilot.pause()
        render(app, "restore-confirm")
        assert app.screen.query_one("#detail") is not None  # diff preview, not just the bare prompt
        await pilot.click("#confirm")
        await pilot.pause()
        render(app, "after-restore")

        assert log_view.row_count == before
        assert len(app.state.repo.revset(app.state.settings, "description(exact:'A')")) == 1


async def test_o_cancel_from_the_oplog_screen_leaves_history_unchanged(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        before = log_view.row_count

        await pilot.press("o")
        await pilot.pause()
        render(app, "oplog-modal-for-cancel")
        await pilot.press("escape")
        await pilot.pause()

        assert len(app.screen_stack) == 1
        assert log_view.row_count == before


async def test_oplog_hjkl_navigates_the_table_and_switches_focus_to_the_diff_pane(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()

        await pilot.press("o")
        await pilot.pause()
        table = app.screen.query_one(DataTable)

        await pilot.press("j")
        await pilot.pause()
        assert table.cursor_row == 1
        await pilot.press("k")
        await pilot.pause()
        assert table.cursor_row == 0

        await pilot.press("l")
        await pilot.pause()
        render(app, "oplog-diff-focused")
        assert app.screen.query_one(DiffPane).has_focus

        await pilot.press("h")
        await pilot.pause()
        assert table.has_focus


async def test_oplog_space_marks_a_diff_base_without_crashing(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()

        await pilot.press("o")
        await pilot.pause()
        table = app.screen.query_one(DataTable)

        await pilot.press("space")
        await pilot.pause()
        render(app, "oplog-marked")
        assert table.get_cell_at(Coordinate(0, 0)) == "✓"

        await pilot.press("down")
        await pilot.pause()
        render(app, "oplog-marked-diff")
        # Marking row 1 moves the mark, clearing row 0's checkmark.
        assert table.get_cell_at(Coordinate(0, 0)) == "✓"

        await pilot.press("up")
        await pilot.pause()
        await pilot.press("space")  # toggling the already-marked row clears it
        await pilot.pause()
        assert table.get_cell_at(Coordinate(0, 0)) == ""


async def test_x_splits_the_cursor_commit_by_selected_paths(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        before = log_view.row_count

        root = Path(app.state.workspace.workspace_root)
        (root / "a.txt").write_text("a\n")
        (root / "b.txt").write_text("b\n")
        new_repo, _stats = await app.state.workspace.snapshot_async(app.state.settings)
        app.state.repo = new_repo
        await app.action_refresh_log()
        await pilot.pause()

        target = app.state.repo.resolve_single(app.state.settings, "@")
        log_view.move_cursor(row=_row_of(log_view, target.change_id))
        await pilot.pause()

        await pilot.press("x")
        await pilot.pause()
        render(app, "split-modal")
        selection_list = app.screen.query_one(SelectionList)
        selection_list.highlighted = 0
        await pilot.press("space")  # select a.txt for the first commit
        await pilot.pause()
        render(app, "split-modal-selected")
        await pilot.click("#split")
        await pilot.pause()
        render(app, "split-confirm")
        await pilot.click("#confirm")
        await pilot.pause()
        render(app, "after-split")

        assert log_view.row_count == before + 1
        first = app.state.repo.resolve_single(app.state.settings, target.change_id.reverse_hex())
        second = app.state.repo.resolve_single(app.state.settings, "@")
        assert first.file_exists("a.txt")
        assert not first.file_exists("b.txt")
        assert second.parent_ids == [first.id]
        assert second.file_exists("a.txt")
        assert second.file_exists("b.txt")


async def test_x_without_a_single_parent_shows_a_warning(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)

        a = app.state.repo.resolve_single(app.state.settings, "description(exact:'A')")
        b = app.state.repo.resolve_single(app.state.settings, "description(exact:'B')")
        tx = app.state.repo.start_transaction(app.state.settings)
        builder = tx.new_commit(app.state.settings, [a.id, b.id])
        builder.set_description("merge")
        merge_commit = builder.write(app.state.repo)
        tx.edit(app.state.workspace.workspace_name, merge_commit)
        tx.rebase_descendants()
        app.state.repo = tx.commit("merge")
        await app.action_refresh_log()
        await pilot.pause()

        log_view.move_cursor(row=_row_of(log_view, merge_commit.change_id))
        await pilot.press("x")
        await pilot.pause()
        render(app, "split-merge-warning")

        assert len(app.screen_stack) == 1  # no modal pushed
        assert len(app._notifications) >= 1


async def test_x_cancel_from_the_split_screen_leaves_history_unchanged(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        before = log_view.row_count

        root = Path(app.state.workspace.workspace_root)
        (root / "a.txt").write_text("a\n")
        new_repo, _stats = await app.state.workspace.snapshot_async(app.state.settings)
        app.state.repo = new_repo
        await app.action_refresh_log()
        await pilot.pause()

        target = app.state.repo.resolve_single(app.state.settings, "@")
        log_view.move_cursor(row=_row_of(log_view, target.change_id))
        await pilot.press("x")
        await pilot.pause()
        render(app, "split-modal-for-cancel")
        await pilot.press("escape")
        await pilot.pause()

        assert len(app.screen_stack) == 1
        assert log_view.row_count == before


async def test_x_cancel_at_the_split_confirm_step_leaves_history_unchanged(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        before = log_view.row_count

        root = Path(app.state.workspace.workspace_root)
        (root / "a.txt").write_text("a\n")
        new_repo, _stats = await app.state.workspace.snapshot_async(app.state.settings)
        app.state.repo = new_repo
        await app.action_refresh_log()
        await pilot.pause()

        target = app.state.repo.resolve_single(app.state.settings, "@")
        log_view.move_cursor(row=_row_of(log_view, target.change_id))
        await pilot.press("x")
        await pilot.pause()
        selection_list = app.screen.query_one(SelectionList)
        selection_list.highlighted = 0
        await pilot.press("space")
        await pilot.click("#split")
        await pilot.pause()
        render(app, "split-confirm-for-cancel")
        await pilot.click("#cancel")
        await pilot.pause()

        assert len(app.screen_stack) == 1
        assert log_view.row_count == before
        assert app.state.repo.resolve_single(app.state.settings, "@").id == target.id


async def test_d_describes_the_cursor_commit_after_confirmation(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)

        await pilot.press("down")  # move onto A, away from the working copy
        await pilot.pause()
        target = log_view.selected_commit

        await pilot.press("d")
        await pilot.pause()
        app.screen.query_one(Input).value = "A renamed"
        await pilot.press("enter")
        await pilot.pause()
        render(app, "describe-confirm")
        await pilot.click("#confirm")
        await pilot.pause()
        render(app, "after-describe")

        renamed = app.state.repo.resolve_single(app.state.settings, "description(exact:'A renamed')")
        assert renamed.change_id == target.change_id


async def test_d_cancel_at_confirm_leaves_description_unchanged(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)

        await pilot.press("down")
        await pilot.pause()
        target = log_view.selected_commit

        await pilot.press("d")
        await pilot.pause()
        app.screen.query_one(Input).value = "A renamed"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.click("#cancel")
        await pilot.pause()

        assert len(app.screen_stack) == 1
        assert app.state.repo.revset(app.state.settings, "description(exact:'A renamed')") == []
        unchanged = app.state.repo.get_commit(target.id)
        assert unchanged.description == target.description


async def test_s_cancel_at_confirm_leaves_history_unchanged(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        before = log_view.row_count

        a = app.state.repo.resolve_single(app.state.settings, "description(exact:'A')")
        log_view.move_cursor(row=_row_of(log_view, a.change_id))
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()
        render(app, "squash-confirm-for-cancel")
        await pilot.click("#cancel")
        await pilot.pause()

        assert len(app.screen_stack) == 1
        assert log_view.row_count == before
        assert len(app.state.repo.revset(app.state.settings, "description(exact:'A')")) == 1


async def test_m_cancel_at_confirm_leaves_history_unchanged(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)

        a = app.state.repo.resolve_single(app.state.settings, "description(exact:'A')")
        root = app.state.repo.get_commit(a.parent_ids[0])
        new_repo, c = testutils.new_child(
            app.state.workspace, app.state.repo, app.state.settings, root, "C"
        )
        app.state.repo = new_repo
        await app.action_refresh_log()
        await pilot.pause()
        before = log_view.row_count

        b = app.state.repo.resolve_single(app.state.settings, "description(exact:'B')")
        log_view.move_cursor(row=_row_of(log_view, c.change_id))
        await pilot.press("space")
        log_view.move_cursor(row=_row_of(log_view, b.change_id))
        await pilot.pause()

        await pilot.press("m")
        await pilot.pause()
        await pilot.click("#onto")
        await pilot.pause()
        render(app, "rebase-confirm-for-cancel")
        await pilot.click("#cancel")
        await pilot.pause()

        assert len(app.screen_stack) == 1
        assert log_view.row_count == before
        rebased_c = app.state.repo.revset(app.state.settings, "description(exact:'C')")[0]
        assert rebased_c.parent_ids == [root.id]


async def test_y_cancel_at_confirm_leaves_history_unchanged(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        before = log_view.row_count

        a = app.state.repo.resolve_single(app.state.settings, "description(exact:'A')")
        log_view.move_cursor(row=_row_of(log_view, a.change_id))
        await pilot.pause()

        await pilot.press("y")
        await pilot.pause()
        render(app, "duplicate-confirm-for-cancel")
        await pilot.click("#cancel")
        await pilot.pause()

        assert len(app.screen_stack) == 1
        assert log_view.row_count == before


async def test_confirm_screen_remember_checkboxes_are_mutually_exclusive(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)
        a = app.state.repo.resolve_single(app.state.settings, "description(exact:'A')")
        log_view.move_cursor(row=_row_of(log_view, a.change_id))
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()
        session_cb = app.screen.query_one("#remember-session", Checkbox)
        ever_cb = app.screen.query_one("#remember-ever", Checkbox)

        session_cb.value = True
        await pilot.pause()
        assert session_cb.value is True
        assert ever_cb.value is False

        ever_cb.value = True
        await pilot.pause()
        render(app, "both-checked-then-mutually-exclusive")
        assert ever_cb.value is True
        assert session_cb.value is False

        await pilot.click("#cancel")
        await pilot.pause()


async def test_squash_dont_ask_again_this_session_skips_future_squash_confirms(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)

        a = app.state.repo.resolve_single(app.state.settings, "description(exact:'A')")
        root_change_id = app.state.repo.get_commit(a.parent_ids[0]).change_id
        log_view.move_cursor(row=_row_of(log_view, a.change_id))
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()
        app.screen.query_one("#remember-session", Checkbox).value = True
        await pilot.click("#confirm")
        await pilot.pause()
        render(app, "after-first-squash-with-remember-session")

        # A fresh, non-working-copy target for the second squash -- squashing
        # @ itself spawns a replacement empty child instead of shrinking the
        # row count, which would muddy what this test is actually checking.
        # root's own commit id changed (A got squashed into it), so re-
        # resolve it by change id rather than reusing the pre-squash Commit.
        # testutils.new_child() always checks out the commit it creates, so
        # a second child ("D") is built on top of "C" to push @ off of "C"
        # before squashing it.
        root = app.state.repo.resolve_single(app.state.settings, root_change_id.reverse_hex())
        new_repo, c = testutils.new_child(
            app.state.workspace, app.state.repo, app.state.settings, root, "C"
        )
        new_repo, _d = testutils.new_child(
            app.state.workspace, new_repo, app.state.settings, c, "D"
        )
        app.state.repo = new_repo
        await app.action_refresh_log()
        await pilot.pause()
        before = log_view.row_count
        log_view.move_cursor(row=_row_of(log_view, c.change_id))
        await pilot.pause()

        await pilot.press("s")  # no modal this time
        await pilot.pause()
        render(app, "after-second-squash-no-modal")

        assert len(app.screen_stack) == 1
        assert log_view.row_count == before - 1
        # Session-only: never written to the persisted config file.
        assert config.load_skipped_confirmations() == set()


async def test_squash_dont_ask_again_ever_persists_the_skip(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)

        a = app.state.repo.resolve_single(app.state.settings, "description(exact:'A')")
        log_view.move_cursor(row=_row_of(log_view, a.change_id))
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()
        app.screen.query_one("#remember-ever", Checkbox).value = True
        await pilot.click("#confirm")
        await pilot.pause()
        render(app, "after-squash-with-remember-ever")

        assert config.load_skipped_confirmations() == {"squash"}
        assert not app.state.should_confirm("squash")
        assert len(app.state.repo.revset(app.state.settings, "description(exact:'A')")) == 1


async def test_f_browses_the_cursor_commit_files(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)

        root = Path(app.state.workspace.workspace_root)
        (root / "a.txt").write_text("hello\n")
        (root / "b.txt").write_text("world\n")
        new_repo, _stats = await app.state.workspace.snapshot_async(app.state.settings)
        app.state.repo = new_repo
        await app.action_refresh_log()
        await pilot.pause()

        target = app.state.repo.resolve_single(app.state.settings, "@")
        log_view.move_cursor(row=_row_of(log_view, target.change_id))
        await pilot.pause()

        await pilot.press("f")
        await pilot.pause()
        render(app, "files-modal")

        table = app.screen.query_one(DataTable)
        assert table.row_count == 2
        content = app.screen.query_one(ContentPane)
        assert "hello" in _pane_text(content)

        await pilot.press("j")
        await pilot.pause()
        assert table.cursor_row == 1
        assert "world" in _pane_text(content)

        await pilot.press("l")
        await pilot.pause()
        render(app, "files-content-focused")
        assert content.has_focus

        await pilot.press("h")
        await pilot.pause()
        assert table.has_focus

        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1


async def test_d_toggles_diff_view_and_r_restores_a_file(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)

        root = Path(app.state.workspace.workspace_root)
        (root / "a.txt").write_text("old\n")
        new_repo, _stats = await app.state.workspace.snapshot_async(app.state.settings)
        app.state.repo = new_repo
        await app.action_refresh_log()
        await pilot.pause()
        historic = app.state.repo.resolve_single(app.state.settings, "@")

        await pilot.press("n")  # new child -- working copy moves off `historic`
        await pilot.pause()

        (root / "a.txt").write_text("new\n")
        new_repo, _stats = await app.state.workspace.snapshot_async(app.state.settings)
        app.state.repo = new_repo
        await app.action_refresh_log()
        await pilot.pause()

        log_view.move_cursor(row=_row_of(log_view, historic.change_id))
        await pilot.pause()

        await pilot.press("f")
        await pilot.pause()
        content = app.screen.query_one(ContentPane)
        assert "old" in _pane_text(content)

        await pilot.press("d")
        await pilot.pause()
        render(app, "files-diff-mode")
        diff_text = _pane_text(content)
        assert "-new" in diff_text
        assert "+old" in diff_text

        await pilot.press("r")
        await pilot.pause()
        render(app, "restore-file-confirm")
        assert app.screen.query_one("#detail") is not None
        await pilot.click("#confirm")
        await pilot.pause()
        render(app, "after-restore-file")

        assert len(app.screen_stack) == 2  # FilesScreen stays open
        new_wc = app.state.repo.resolve_single(app.state.settings, "@")
        assert new_wc.read_file("a.txt") == b"old\n"

        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1


async def test_r_on_the_working_copy_itself_just_notifies(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)

        root = Path(app.state.workspace.workspace_root)
        (root / "a.txt").write_text("hello\n")
        new_repo, _stats = await app.state.workspace.snapshot_async(app.state.settings)
        app.state.repo = new_repo
        await app.action_refresh_log()
        await pilot.pause()

        target = app.state.repo.resolve_single(app.state.settings, "@")
        log_view.move_cursor(row=_row_of(log_view, target.change_id))
        await pilot.pause()

        await pilot.press("f")
        await pilot.pause()

        await pilot.press("r")
        await pilot.pause()
        render(app, "restore-file-noop-notice")

        assert len(app.screen_stack) == 2  # no confirm modal was pushed
        assert len(app._notifications) >= 1


async def test_space_marks_multiple_files_and_r_restores_them_in_one_transaction(app, render):
    async with app.run_test() as pilot:
        await pilot.pause()
        log_view = app.query_one(LogView)

        root = Path(app.state.workspace.workspace_root)
        (root / "a.txt").write_text("old-a\n")
        (root / "b.txt").write_text("old-b\n")
        new_repo, _stats = await app.state.workspace.snapshot_async(app.state.settings)
        app.state.repo = new_repo
        await app.action_refresh_log()
        await pilot.pause()
        historic = app.state.repo.resolve_single(app.state.settings, "@")

        await pilot.press("n")  # new child -- working copy moves off `historic`
        await pilot.pause()

        (root / "a.txt").write_text("new-a\n")
        (root / "b.txt").write_text("new-b\n")
        new_repo, _stats = await app.state.workspace.snapshot_async(app.state.settings)
        app.state.repo = new_repo
        await app.action_refresh_log()
        await pilot.pause()

        log_view.move_cursor(row=_row_of(log_view, historic.change_id))
        await pilot.pause()

        await pilot.press("f")
        await pilot.pause()
        table = app.screen.query_one(DataTable)
        assert table.row_count == 2  # a.txt, b.txt

        await pilot.press("space")
        await pilot.pause()
        assert table.get_cell_at(Coordinate(0, 0)) == "✓"

        await pilot.press("j")
        await pilot.press("space")
        await pilot.pause()
        render(app, "files-two-marked")
        assert table.get_cell_at(Coordinate(1, 0)) == "✓"

        before_ops = len(app.state.repo.operation_log())

        await pilot.press("r")
        await pilot.pause()
        render(app, "restore-two-files-confirm")
        await pilot.click("#confirm")
        await pilot.pause()
        render(app, "after-restore-two-files")

        new_wc = app.state.repo.resolve_single(app.state.settings, "@")
        assert new_wc.read_file("a.txt") == b"old-a\n"
        assert new_wc.read_file("b.txt") == b"old-b\n"
        # one transaction for the whole batch, not one per file
        assert len(app.state.repo.operation_log()) == before_ops + 1
        # marks are cleared after a successful restore
        assert table.get_cell_at(Coordinate(0, 0)) == ""
        assert table.get_cell_at(Coordinate(1, 0)) == ""
