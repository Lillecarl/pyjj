"""The repository states the corpus records output against.

A fixture is built once per capture run and reused by every entry that
names it, since a read-only command cannot perturb one. Coverage tends
to be limited by these rather than by the catalogue: a flag about
remotes needs a repository with a remote, and no amount of catalogue
entries conjures one.
"""

from __future__ import annotations

import subprocess

from parity_harness import make_bare_remote


def chain(pair) -> None:
    """base <- one (bookmark `main`) <- two. The standard history."""
    pair.init()
    pair.op(files={"base.txt": b"base\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new", "-m", "one"])
    pair.op(files={"one.txt": b"one\n"}, jj=["bookmark", "create", "main"])
    pair.op(jj=["new", "-m", "two"])
    pair.op(files={"two.txt": b"two\n"}, jj=["status"])


def conflict(pair) -> None:
    """Two siblings editing one line, merged: `f.txt` is conflicted."""
    pair.init()
    pair.op(files={"f.txt": b"line1\nline2\n"}, jj=["describe", "-m", "base"])
    pair.op(jj=["new", "-m", "one"])
    pair.op(files={"f.txt": b"ONE\nline2\n"}, jj=["status"])
    pair.op(jj=["new", 'description(glob:"base*")', "-m", "two"])
    pair.op(files={"f.txt": b"TWO\nline2\n"}, jj=["status"])
    pair.op(jj=["new", 'description(glob:"one*")', 'description(glob:"two*")',
                "-m", "merge"])


def tags(pair) -> None:
    """A chain with a tag on it.

    `tag list` printed a truncated commit id for a long time, and the
    scenario claiming it passed anyway -- on a repository with no tags,
    which is what this exists to stop.
    """
    chain(pair)
    pair.op(jj=["tag", "set", "v1", "-r", 'description(glob:"one*")'])


def evolution(pair) -> None:
    """A change rewritten twice, so earlier versions are hidden.

    `evolog` needs this: with nothing rewritten there is no evolution to
    show, and every assertion about hidden versions passes on empty.
    """
    chain(pair)
    pair.op(files={"two.txt": b"two again\n"}, jj=["describe", "-m", "two rewritten"])
    pair.op(files={"two.txt": b"two once more\n"}, jj=["describe", "-m", "two rewritten twice"])


def squashed(pair) -> None:
    """An evolution that forks.

    A squash gives its destination two predecessors, so the destination's
    evolution log is a graph rather than a line. `evolution` alone is
    linear, and a drawing that only ever opens one lane proves nothing
    about the drawing.

    The squash leaves `@` empty and new, so the fork is at `@-`.
    """
    evolution(pair)
    pair.op(jj=["new", "-m", "sibling"])
    pair.op(files={"extra.txt": b"extra\n"},
            jj=["squash", "--use-destination-message"])


def executable(pair) -> None:
    """Every file shape a diff has a sentence for: a modification, a
    deletion, an addition, a mode change and a missing trailing
    newline."""
    pair.init()
    pair.op(
        files={
            "edited.txt": b"one\ntwo\nthree\nfour\nfive\nsix\nseven\neight\n",
            "removed.txt": b"gone\n",
            "mode.txt": b"same content\n",
            "nonewline.txt": b"no trailing newline",
        },
        jj=["describe", "-m", "base"],
    )
    pair.op(jj=["new", "-m", "every shape"])
    pair.op(
        files={
            "edited.txt": b"one\nTWO\nthree\nfour\nfive\nsix\nseven\nEIGHT\n",
            "removed.txt": None,
            "added.txt": b"brand new\n",
            "nonewline.txt": b"no trailing newline, now longer",
        },
        jj=["file", "chmod", "x", "mode.txt"],
    )


def whitespace(pair) -> None:
    """Lines that differ only in whitespace, and one that does not.

    `-w` and `-b` are the only flags whose answer is which lines
    changed rather than how they are printed, so nothing else in the
    corpus can tell them apart. Three lines, one each: `indented` moves
    leading space, so `-b` and `-w` both hide it; `spaced` changes the
    amount of space inside the line, which `-b` hides and `-w` hides
    too; `stripped` removes space entirely, which only `-w` hides. The
    fourth line changes a word, so every mode still shows something.
    """
    pair.init()
    pair.op(
        files={
            "ws.txt": b"    indented\nspaced  out\nstr ipped\nreal change\n",
        },
        jj=["describe", "-m", "base"],
    )
    pair.op(jj=["new"])
    pair.op(
        files={
            "ws.txt": b"        indented\nspaced out\nstripped\nreal changed\n",
        },
        jj=["describe", "-m", "whitespace"],
    )


def rewritten_stack(pair) -> None:
    """A chain whose oldest commit is rewritten, so the stack moves.

    `op diff` draws the commits an operation changed. With one changed
    commit that graph is a single node with no edges, which says
    nothing about the drawing -- the same way `tag list` passed for
    weeks on a repository with no tags. Rewriting an ancestor changes
    three commits at once, with edges between them.
    """
    chain(pair)
    pair.op(jj=["describe", "-r", 'description(glob:"base*")',
                "-m", "base rewritten"])


def remote(pair) -> None:
    """A chain with a fetched remote.

    Every flag about a remote -- `--all-remotes`, `--tracked`, the
    remote listings -- prints the same thing as its absence on a
    repository that has none. Those entries were passing on `chain`,
    which is the `tag list` failure again.
    """
    chain(pair)
    pair.remote = make_bare_remote(pair.root)
    # A second bookmark on the remote that nothing follows. A fetch
    # imports it untracked, so it is the line `--all-remotes` and
    # `--remote` add and `--tracked` leaves out. Without it those three
    # listings print the same block, and each one passes on the others'
    # work.
    subprocess.run(
        ["git", "--git-dir", str(pair.remote), "update-ref",
         "refs/heads/feature", "refs/heads/main"],
        check=True, capture_output=True,
    )
    pair.op(jj=["git", "remote", "add", "origin", str(pair.remote)])
    pair.op(jj=["git", "fetch"])
    # A fetched bookmark starts untracked, so `--tracked` would list
    # nothing and pass on empty. Tracking one gives it something to
    # show -- and gives the listings a tracked remote to render.
    pair.op(jj=["bookmark", "track", "main@origin"])


FIXTURES = {
    "chain": chain,
    "remote": remote,
    "rewritten_stack": rewritten_stack,
    "conflict": conflict,
    "tags": tags,
    "evolution": evolution,
    "squashed": squashed,
    "executable": executable,
    "whitespace": whitespace,
}
