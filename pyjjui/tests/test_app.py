"""Interaction tests for `PyjjuiApp`, driven via Textual's Pilot."""

from textual.widgets import Input

from pyjjui.widgets.log_view import LogView


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
