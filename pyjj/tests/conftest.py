"""Shared fixtures for the pyjj test suite.

Every fixture that creates a workspace hands back a fresh directory per
test (via pytest's `tmp_path`), since jj workspaces need an existing,
empty directory to initialize into.
"""

import pytest

import pyjj


@pytest.fixture
def settings():
    """Deterministic settings, ignoring whatever real jj config happens to
    exist on the machine running the tests -- `UserSettings()` loads real
    config by default (see AGENTS.md), so tests that want hermeticity must
    opt out explicitly.
    """
    return pyjj.UserSettings(load_config=False)


@pytest.fixture
def workspace_and_repo(tmp_path, settings):
    """A freshly-initialized internal-git workspace and its repo."""
    return pyjj.Workspace.init_internal_git(settings, str(tmp_path))


@pytest.fixture
def workspace(workspace_and_repo):
    ws, _repo = workspace_and_repo
    return ws


@pytest.fixture
def repo(workspace_and_repo):
    _ws, repo = workspace_and_repo
    return repo


@pytest.fixture
def wc_commit(repo):
    """The initial (empty) working-copy commit."""
    view = repo.view()
    wc_hex = next(iter(view.values()))
    return repo.get_commit(pyjj.CommitId(wc_hex))


# -- CLI coverage marks ---------------------------------------------------
#
# `jj util markdown-help` gives an authoritative list of every subcommand
# and flag jj accepts (see `parity/cli_surface.py`). A test claims an
# item off that list with
#
#     @pytest.mark.covers("split", "-A", "--insert-after")
#
# where the first argument is the subcommand path ("" for the root
# command) and the rest are flag spellings. With no flags, the mark
# claims the subcommand itself.
#
# Each spelling is its own item on purpose. jj accepts `-A`,
# `--insert-after` and `--after` for one option, and pyjj-cli accepted
# only two of the three until the surface comparison caught it -- a
# mark that checked off all three at once would have hidden that.

_COVERAGE_MARKS = pytest.StashKey[dict]()
_COVERAGE_COMPLETE = pytest.StashKey[bool]()


def pytest_addoption(parser):
    parser.addoption(
        "--capture-corpus", action="store_true", default=False,
        help="Re-record the jj output goldens under parity/corpus/goldens",
    )
    parser.addoption(
        "--write-surface-baseline",
        action="store_true",
        default=False,
        help="rewrite the CLI surface baseline from this run's measurement "
             "instead of asserting against it",
    )
    parser.addoption(
        "--write-coverage-baseline",
        action="store_true",
        default=False,
        help="rewrite the CLI coverage baseline from the marks collected "
             "in this run instead of asserting against it",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "covers(command, *flags): claim a subcommand or flag from jj's "
        "argument surface as tested by this test",
    )


def pytest_collection_modifyitems(session, config, items):
    """Record every `covers` mark seen during collection.

    `test_cli_coverage` reads this to say what is still unclaimed. A
    filtered run (`-k`/`-m`) collects only part of the suite, so the
    completeness check has to stand down rather than report a false gap.
    """
    covered: dict[str, set[str]] = {}
    for item in items:
        for mark in item.iter_markers("covers"):
            if not mark.args:
                raise ValueError(
                    f"{item.nodeid}: covers() needs a subcommand name"
                )
            command, *flags = mark.args
            entry = covered.setdefault(command, set())
            entry.update(flags)
    config.stash[_COVERAGE_MARKS] = covered
    config.stash[_COVERAGE_COMPLETE] = not (
        config.option.keyword or config.option.markexpr
    )


@pytest.fixture(scope="session")
def coverage_marks(pytestconfig):
    """{subcommand: {flag spellings}} claimed by the collected tests.

    A subcommand with an empty set was claimed bare, which checks off
    the subcommand itself and none of its flags.
    """
    return pytestconfig.stash.get(_COVERAGE_MARKS, {})


@pytest.fixture(scope="session")
def coverage_is_complete(pytestconfig):
    """False when `-k`/`-m` narrowed collection, so the marks seen are
    only part of what the suite declares."""
    return pytestconfig.stash.get(_COVERAGE_COMPLETE, False)
