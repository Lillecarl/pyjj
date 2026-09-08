"""git subcommand: git_fetch."""
import sys

import pyjj
from ..common import (
    CommandError,
    _finish,
    _load,
    _name_matches,
    _start_transaction,
)

# The remote a fetch reads when nothing names one and the repository
# holds more than one.
_DEFAULT_REMOTE = "origin"


def _configured_remotes(settings):
    """The remotes `git.fetch` names, or `None` when it names none.

    jj accepts either a list or a single name there, so both are read.
    """
    names = settings.get_string_list("git.fetch")
    if names:
        return list(names)
    name = settings.get_string("git.fetch")
    return [name] if name else None


def _remotes(repo, settings, args) -> list[str]:
    """The remotes this fetch reads, in the order the repository holds them.

    `--all-remotes` takes every one. `--remote` takes patterns, so one
    flag can name a set. With neither, `git.fetch` decides; with that
    unset the only remote wins, and a repository with several falls back
    to `origin`.
    """
    known = repo.git_remotes()
    if getattr(args, "all_remotes", False):
        return known if known else _no_remotes()

    patterns = getattr(args, "remotes", None) or _configured_remotes(settings)
    if patterns is None:
        if len(known) == 1:
            patterns = list(known)
            if patterns != [_DEFAULT_REMOTE]:
                print("Hint: Fetching from the only existing remote: "
                      f"{patterns[0]}", file=sys.stderr)
        else:
            patterns = [_DEFAULT_REMOTE]

    matching = [name for name in known
                if any(_name_matches(name, pattern) for pattern in patterns)]
    # A pattern that names one remote and finds nothing is worth saying
    # out loud. A glob that matches nothing is not: it asks for whatever
    # is there.
    missing = [pattern for pattern in patterns
               if "*" not in pattern and pattern not in known]
    if missing:
        print(f"Warning: No matching remotes for names: {', '.join(missing)}",
              file=sys.stderr)
    return matching if matching else _no_remotes()


def _no_remotes():
    raise CommandError("No git remotes to fetch from")


def git_fetch(args) -> int:
    """`jj git fetch` — fetch from a Git remote."""
    try:
        branches = getattr(args, "branches", None)
        tags = getattr(args, "tags", None)
        tracked = getattr(args, "tracked", False)
        if tracked and (branches is not None or tags is not None):
            named = "--branch" if branches is not None else "--tag"
            print(f"error: the argument '--tracked' cannot be used with "
                  f"'{named}'", file=sys.stderr)
            return 2

        settings, ws, repo = _load(args)
        remotes = _remotes(repo, settings, args)
        tx = _start_transaction(repo, settings)
        for remote in remotes:
            tx.git_fetch(settings, remote, branches, tags, tracked)
        _finish(tx, f"fetch from git remote(s) {','.join(remotes)}",
                settings, ws, repo)
        return 0
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError,
            CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
