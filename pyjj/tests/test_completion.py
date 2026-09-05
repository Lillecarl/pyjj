"""What the shell is offered when someone presses Tab.

The generated scripts the package installs run `pyjj` again with the
half-typed command line in the environment, and read the candidates
back. These tests drive that same protocol, so what they check is what
a shell would receive rather than what a function returns.

**A completion that fails offers nothing, and that is indistinguishable
from a completer that ran and found nothing.** So every case here names
candidates it expects to see. A row that only asserted "no crash" would
still pass with every completer removed.
"""

import os
import subprocess
import sys

import pytest

import pyjj


#: What argcomplete puts between two candidates.
_SEPARATOR = "\013"


def _candidates(line: str, cwd) -> list[str]:
    """The candidates `pyjj` offers for `line`, driven as a shell does.

    argcomplete writes its answer to a file descriptor the generated
    script opens, or to the file this names -- which is the same
    protocol without a shell in the way.
    """
    answer = os.path.join(str(cwd), ".completion-answer")
    environment = {
        **os.environ,
        "_ARGCOMPLETE": "1",
        "_ARGCOMPLETE_IFS": _SEPARATOR,
        "_ARGCOMPLETE_SHELL": "bash",
        "_ARGCOMPLETE_STDOUT_FILENAME": answer,
        "COMP_LINE": line,
        "COMP_POINT": str(len(line)),
        "COMP_TYPE": "9",
        "_ARGCOMPLETE_COMP_WORDBREAKS": " \t\n\"'><=;|&(:",
    }
    done = subprocess.run(
        [sys.executable, "-c", "from pyjj_cli.__main__ import main; main()"],
        env=environment, cwd=str(cwd), capture_output=True, text=True,
    )
    assert done.returncode == 0, (
        f"completing {line!r} exited {done.returncode}:\n{done.stderr[:2000]}"
    )
    if not os.path.exists(answer):
        return []
    with open(answer, encoding="utf-8") as handle:
        text = handle.read()
    # A candidate carries a trailing space when argcomplete considers it
    # finished, which is a hint to the shell and not part of the word.
    # bash also gets its own escaping, which a reader never types.
    return sorted(
        candidate.rstrip().replace("\\", "")
        for candidate in text.split(_SEPARATOR) if candidate
    )


@pytest.fixture
def repo_dir(tmp_path, settings):
    """A workspace holding one bookmark, so a name has something to find."""
    root = tmp_path / "repo"
    root.mkdir()
    ws, repo = pyjj.Workspace.init_internal_git(settings, str(root))
    wc_hex = next(iter(repo.view().values()))
    tx = repo.start_transaction(settings)
    tx.set_bookmark("feature", pyjj.CommitId(wc_hex))
    tx.commit("add bookmark")
    return root


def test_a_subcommand_is_offered(repo_dir):
    assert "log" in _candidates("pyjj ", repo_dir)


def test_help_is_not_offered(repo_dir):
    """`-h` and `--help` are argparse's own and are noise beside the rest."""
    offered = _candidates("pyjj log -", repo_dir)
    assert "--patch" in offered
    assert "-h" not in offered
    assert "--help" not in offered


def test_a_revset_offers_the_working_copy_and_a_bookmark(repo_dir):
    offered = _candidates("pyjj log -r ", repo_dir)
    assert "@" in offered
    assert "feature" in offered
    assert "root()" in offered


def test_a_revset_offers_an_id_a_reader_can_retype(repo_dir):
    """The shortest unambiguous prefix is often one character.

    Nobody recognises one, and it stops matching as soon as a second
    is typed, so an id is offered at the length `jj log` prints.
    """
    offered = _candidates("pyjj log -r ", repo_dir)
    ids = [text for text in offered if len(text) >= 8 and text.isalnum()]
    assert ids, f"no id among {offered}"


def test_a_positional_revset_is_offered_too(repo_dir):
    """`jj new` takes its parents positionally, with no flag to key on."""
    assert "feature" in _candidates("pyjj new ", repo_dir)


def test_a_bookmark_name_is_offered(repo_dir):
    assert _candidates("pyjj bookmark delete ", repo_dir) == ["feature"]


def test_an_operation_is_offered(repo_dir):
    offered = _candidates("pyjj op show ", repo_dir)
    assert "@" in offered
    assert "@-" in offered


def test_a_template_name_is_offered(repo_dir):
    assert "builtin_log_compact" in _candidates("pyjj log -T ", repo_dir)


def test_a_path_is_offered(repo_dir):
    (repo_dir / "readme.md").write_text("hi\n")
    assert "readme.md" in _candidates("pyjj diff ", repo_dir)


def test_outside_a_repository_nothing_fails(tmp_path):
    """Most directories are not a workspace, and that is not an error.

    The flags still complete there; only the values a repository would
    have named are missing.
    """
    offered = _candidates("pyjj log -", tmp_path)
    assert "--patch" in offered
    assert _candidates("pyjj bookmark delete ", tmp_path) == []
