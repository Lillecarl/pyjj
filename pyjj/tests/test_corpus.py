"""Holds pyjj-cli to the recorded corpus of what jj prints.

`test_parity.py` compares the two CLIs live, a scenario at a time. This
compares both against goldens on disk, which buys three things a live
comparison cannot.

- The comparison is three-way. jj is checked against the golden too, so
  a failure says whether pyjj-cli moved or whether jj, the fixture or
  the environment did.
- The judgement is enumerable. Every read-only item on the coverage
  ledger must have a catalogue entry or a reasoned skip, so a flag
  cannot be left out by simply not thinking about it.
- A golden must not be empty unless its entry says so. A scenario that
  passes because both sides print nothing is the way `tag list` kept a
  wrong format for weeks.

Regenerate the goldens after changing the catalogue:

    nix run --file . tests -- -q -k test_capture_the_corpus --capture-corpus
"""

import subprocess
import sys
from pathlib import Path

import pytest

from parity import cli_surface
from parity.corpus import GOLDEN_SUFFIX, PLAIN_SUFFIX, normalize
from parity.corpus.capture import GOLDENS, capture, run_jj
from parity.corpus.catalogue import CATALOGUE
from parity.corpus.fixtures import FIXTURES
from parity.parity_harness import DRIVER, RepoPair

COMPARED = [e for e in CATALOGUE if e.bar in {"bytes", "facts", "todo"}]


def _params(entries, claim: bool):
    """Parametrization for a list of entries.

    `claim` attaches each entry's `covers` marks, so a corpus entry that
    actually holds pyjj-cli to jj checks its items off the coverage
    ledger. Only a `bytes` entry does that: a `todo` is a recorded gap,
    and a `facts` entry is claimed by its scenario in `test_parity.py`.
    """
    out = []
    for entry in entries:
        marks = (
            [pytest.mark.covers(*entry.claims)]
            if claim and entry.claims and entry.bar == "bytes"
            else []
        )
        out.append(pytest.param(entry, marks=marks, id=entry.id))
    return out


def _golden(entry, suffix: str = GOLDEN_SUFFIX) -> str:
    path = GOLDENS / f"{entry.id}{suffix}"
    if not path.exists():
        pytest.fail(
            f"no golden for {entry.id!r}; capture the corpus "
            "(see this module's docstring)"
        )
    return path.read_text()


def _run_pyjj(pair, argv) -> subprocess.CompletedProcess:
    env = pair._env(bump=False)
    return subprocess.run(
        [sys.executable, str(DRIVER), str(pair.py_repo), "--no-pager",
         "--ignore-working-copy", *argv],
        env=env, capture_output=True, text=True, cwd=str(pair.py_repo),
        stdin=subprocess.DEVNULL,
    )


@pytest.fixture(scope="module")
def corpus_pairs(tmp_path_factory):
    """One built pair per fixture, shared by every entry that names it.

    A read-only command cannot perturb a repository, which is what makes
    sharing safe -- and `test_parity.py` has a scenario asserting
    exactly that for each of them.
    """
    built = {}
    for name in sorted({entry.fixture for entry in CATALOGUE}):
        root = tmp_path_factory.mktemp(f"corpus-{name}")
        pair = RepoPair(root)
        FIXTURES[name](pair)
        built[name] = pair
    return built


def _op_ids(pair) -> list[str]:
    from parity.corpus.capture import _op_ids as read

    return {
        "cli": read(pair.jj_bin, pair.cli_repo, pair._env(bump=False)),
        "py": read(pair.jj_bin, pair.py_repo, pair._env(bump=False)),
    }


@pytest.mark.parametrize("entry", _params(COMPARED, claim=False))
def test_the_corpus_still_describes_jj(entry, corpus_pairs):
    """jj itself still prints what the golden recorded.

    This is the leg that makes a failure legible. Without it, a change
    in jj, in a fixture or in the environment would read as pyjj-cli
    having broken.
    """
    pair = corpus_pairs[entry.fixture]
    ops = _op_ids(pair)
    context = {"repo": pair.cli_repo, "op_ids": ops["cli"]}
    got = normalize(run_jj(pair, entry.argv, "never"), entry.normalize, context)
    assert got == _golden(entry, PLAIN_SUFFIX), (
        f"jj no longer prints what the golden for {entry.id!r} recorded"
    )


@pytest.mark.parametrize(
    "entry", _params([e for e in COMPARED if e.bar == "bytes"], claim=True)
)
def test_pyjj_prints_what_the_corpus_records(entry, corpus_pairs):
    """pyjj-cli's plain output matches the golden's plain rendering."""
    pair = corpus_pairs[entry.fixture]
    ops = _op_ids(pair)
    proc = _run_pyjj(pair, entry.argv)
    assert proc.returncode == 0, (
        f"pyjj-cli failed on {list(entry.argv)}\n{proc.stderr}"
    )
    got = normalize(
        proc.stdout, entry.normalize, {"repo": pair.py_repo, "op_ids": ops["py"]}
    )
    assert got == _golden(entry, PLAIN_SUFFIX)


@pytest.mark.parametrize(
    "entry", _params([e for e in COMPARED if e.bar == "todo"], claim=False)
)
def test_the_todo_entries_are_still_todo(entry, corpus_pairs):
    """A `todo` entry that started matching should become a `bytes` one.

    Strictness in the same spirit as the xfails: closing a gap must turn
    the suite red until the catalogue says so.
    """
    pair = corpus_pairs[entry.fixture]
    ops = _op_ids(pair)
    proc = _run_pyjj(pair, entry.argv)
    if proc.returncode != 0:
        return  # not implemented at all; still a todo
    got = normalize(
        proc.stdout, entry.normalize, {"repo": pair.py_repo, "op_ids": ops["py"]}
    )
    assert got != _golden(entry, PLAIN_SUFFIX), (
        f"{entry.id!r} now matches jj; change its bar from todo to bytes"
    )


@pytest.mark.parametrize("entry", _params(COMPARED, claim=False))
def test_no_golden_is_vacuously_empty(entry):
    """Output nobody printed proves nothing about either side."""
    if entry.may_be_empty:
        return
    assert _golden(entry, PLAIN_SUFFIX).strip(), (
        f"{entry.id!r} recorded no output; either the fixture does not "
        "reach this case, or the entry needs may_be_empty"
    )


def test_the_catalogue_covers_the_read_only_surface():
    """Every read-only item is either recorded or refused, with a reason.

    This is the judgement the catalogue exists to hold. An item left out
    of it is a decision nobody wrote down.
    """
    claimed = set()
    for entry in CATALOGUE:
        claimed.update(entry.claims)
    checklist = cli_surface.checklist()
    missing = sorted(
        command
        for command in READ_ONLY_COMMANDS
        if command in checklist and command not in claimed
    )
    assert not missing, (
        "read-only commands with no corpus entry and no reason: "
        f"{missing}"
    )


#: Commands that only read. A corpus entry runs them against a shared
#: fixture, so anything that writes belongs elsewhere -- `bisect run`
#: checks out revisions and executes a script, and would rewrite the
#: fixture underneath every other entry.
READ_ONLY_COMMANDS = {
    "log", "diff", "show", "status", "evolog", "interdiff", "root", "version",
    "help", "file list", "file show", "file annotate",
    "bookmark list", "tag list", "workspace list", "workspace root",
    "operation log", "git root", "util markdown-help",
}


def test_capture_the_corpus(pytestconfig, tmp_path_factory):
    """Re-records every golden from the pinned jj.

    Skipped unless asked for: it rewrites committed files, and the diff
    it produces is meant to be read.
    """
    if not pytestconfig.getoption("--capture-corpus"):
        pytest.skip("pass --capture-corpus to re-record the goldens")

    def factory(name):
        return RepoPair(tmp_path_factory.mktemp(f"capture-{name}"))

    written = capture(factory)
    assert written, "the catalogue is empty"
