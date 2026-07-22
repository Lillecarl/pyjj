"""Interaction tests for `PyjjuiApp`, driven via Textual's Pilot."""

from textual.widgets import Input

from pyjjui.widgets.log_view import LogView
from pyjjui.widgets.preview import Preview

from . import testutils


def _row_of(log_view: LogView, change_id) -> int:
    return next(i for i, commit in enumerate(log_view._commits) if commit.change_id == change_id)


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
