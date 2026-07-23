"""Tests for AppState.should_confirm()/remember_skip(): the "don't ask
again" bookkeeping app.py's _confirm() helper reads/writes.
"""

from pyjjui import config
from pyjjui.state import AppState


def _state(workspace, settings, seeded_repo, revset="all()"):
    return AppState(workspace=workspace, settings=settings, repo=seeded_repo, revset=revset)


def test_should_confirm_is_true_by_default(workspace, settings, seeded_repo):
    state = _state(workspace, settings, seeded_repo)

    assert state.should_confirm("squash")


def test_remember_skip_session_only_affects_this_state(workspace, settings, seeded_repo):
    state = _state(workspace, settings, seeded_repo)

    state.remember_skip("squash", "session")

    assert not state.should_confirm("squash")
    assert state.should_confirm("rebase")  # unaffected -- per-action, not global
    # A session skip never touches the persisted file.
    assert config.load_skipped_confirmations() == set()


def test_remember_skip_ever_persists_across_a_fresh_state(workspace, settings, seeded_repo):
    state = _state(workspace, settings, seeded_repo)
    state.remember_skip("squash", "ever")

    fresh_state = _state(workspace, settings, seeded_repo)

    assert not fresh_state.should_confirm("squash")
    assert config.load_skipped_confirmations() == {"squash"}


def test_remember_skip_ever_also_takes_effect_immediately(workspace, settings, seeded_repo):
    state = _state(workspace, settings, seeded_repo)

    state.remember_skip("rebase", "ever")

    assert not state.should_confirm("rebase")
