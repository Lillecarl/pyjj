"""What a value can be, one completer a kind, for the shell to offer.

argcomplete hands a completer the text typed so far and takes back the
candidates that start with it. The shell scripts the package installs
call back into this program to ask, so every answer here is computed
from the repository the caller is standing in.

**A Tab press must not write.** A command snapshots the working copy
before it reads the repository; a completion loads the head instead, so
pressing Tab never records an operation and never changes what a later
command would see.

**A completion that fails offers nothing.** A traceback drawn into a
half-typed command line is worse than a missing candidate, and most
directories are not a repository at all -- that is the common case, not
an error. So every entry point catches whatever the repository raises
and answers with an empty list.

**Nothing heavy is imported here.** The parser is built on every run,
and this module is imported with it. `pyjj` and the settings come in
inside the functions, which run only when the shell asks.
"""

import os

# jj's own revset symbols, the ones worth offering before any name.
# `@` is the working copy and `root()` the commit every history starts
# from; the rest are the functions a revset is most often written with.
_REVSET_SYMBOLS = (
    "@", "root()", "all()", "mine()", "empty()", "merges()", "heads()",
    "roots()", "trunk()", "visible_heads()", "conflicts()", "bookmarks()",
    "tags()", "remote_bookmarks()", "description(", "author(", "committer(",
    "files(", "ancestors(", "descendants(", "parents(", "children(",
    "latest(", "reachable(", "present(", "mutable()", "immutable()",
)

# How many characters of an id `jj log` prints, and so how many a
# completion offers. A shorter spelling still resolves, but nobody
# reads one.
_ID_LENGTH = 8

# The same, for an operation id, which `jj op log` prints longer. And
# how many operations are worth offering: a repository holds thousands,
# and only the newest few name anything a reader is looking for.
_OPERATION_ID_LENGTH = 12
_OPERATIONS_OFFERED = 20

# jj's builtin templates. A `-T` takes one of these names or a template
# expression, and the names are the half a shell can offer.
_BUILTIN_TEMPLATES = (
    "builtin_log_compact", "builtin_log_comfortable", "builtin_log_oneline",
    "builtin_log_compact_full_description", "builtin_log_detailed",
    "builtin_log_node", "builtin_log_node_ascii",
    "builtin_op_log_compact", "builtin_op_log_comfortable",
    "builtin_op_log_oneline", "builtin_op_log_node",
    "builtin_op_log_node_ascii", "builtin_evolog_compact",
    "builtin_config_list_detailed", "builtin_draft_commit_description",
)


def _repo(parsed_args):
    """The workspace this completion is about, as `(settings, ws, repo)`.

    `None` when there is no workspace, which is what standing outside
    one looks like. The repository is loaded at its head rather than
    snapshotted: see this module's docstring.
    """
    import pyjj

    settings = pyjj.UserSettings()
    path = getattr(parsed_args, "repository", None) or os.getcwd()
    ws = pyjj.Workspace.load(settings, path)
    return settings, ws, ws.load_at_head()


def _answering(function):
    """Wrap a completer so that a failure offers nothing.

    The shell is drawing a command line, and there is nowhere in it for
    an error to go.
    """
    def answer(prefix="", parsed_args=None, **_kwargs):
        try:
            candidates = function(prefix, parsed_args)
        except Exception:
            return []
        return [text for text in candidates if text.startswith(prefix)]

    answer.__name__ = function.__name__
    answer.__doc__ = function.__doc__
    return answer


def _bookmark_names(repo):
    """Local bookmark names, and remote ones as `name@remote`."""
    names = [bookmark.name for bookmark in repo.bookmarks()]
    names += [f"{bookmark.name}@{bookmark.remote}"
              for bookmark in repo.remote_bookmarks()]
    return names


@_answering
def revsets(prefix, parsed_args):
    """A revset: a name that resolves to commits, or the start of one.

    jj offers ids beside the names, and so does this. An id is offered
    at the length `jj log` prints it, which is the spelling a reader
    has in front of them and can retype -- the shortest unambiguous
    prefix is often one character, which no one would recognise and
    which stops matching the moment a second one is typed.
    """
    if prefix.startswith("-"):
        return []
    loaded = _repo(parsed_args)
    if loaded is None:
        return []
    settings, _ws, repo = loaded
    names = list(_REVSET_SYMBOLS)
    names += _bookmark_names(repo)
    names += [tag.name for tag in repo.tags()]
    # The log's own revset, so the ids offered are the ones a bare
    # `pyjj log` would have just printed.
    expression = settings.get_string("revsets.log") or "all()"
    for node in repo.log_graph(settings, expression, limit=30):
        commit = node.commit
        if not commit.parent_ids:
            continue
        change = repo.shortest_change_id_prefix_len(commit.change_id, settings)
        names.append(commit.change_id.reverse_hex()[:max(change, _ID_LENGTH)])
        short = repo.shortest_commit_id_prefix_len(commit.id, settings)
        names.append(commit.id.hex()[:max(short, _ID_LENGTH)])
    return names


@_answering
def bookmarks(prefix, parsed_args):
    """A bookmark, local or remote."""
    loaded = _repo(parsed_args)
    return [] if loaded is None else _bookmark_names(loaded[2])


@_answering
def local_bookmarks(prefix, parsed_args):
    """A bookmark this repository holds itself.

    `jj bookmark rename` and `jj bookmark delete` name one of these and
    never a remote one, which is the whole reason this is separate.
    """
    loaded = _repo(parsed_args)
    return [] if loaded is None else [b.name for b in loaded[2].bookmarks()]


@_answering
def tags(prefix, parsed_args):
    """A tag name."""
    loaded = _repo(parsed_args)
    return [] if loaded is None else [tag.name for tag in loaded[2].tags()]


@_answering
def remotes(prefix, parsed_args):
    """A remote this repository knows."""
    loaded = _repo(parsed_args)
    if loaded is None:
        return []
    return sorted({b.remote for b in loaded[2].remote_bookmarks()} | {"origin"})


@_answering
def operations(prefix, parsed_args):
    """An operation: `@`, a step back from it, or an id.

    An id is offered at the length `jj op log` prints, since that is
    the spelling a reader copies.
    """
    loaded = _repo(parsed_args)
    if loaded is None:
        return []
    names = ["@", "@-", "@--"]
    # The binding takes no limit, so the whole log is read and the
    # newest few kept -- which is what `op log` does with it too. A
    # limit belongs in the binding rather than here.
    names += [op.id[:_OPERATION_ID_LENGTH]
              for op in loaded[2].operation_log()[:_OPERATIONS_OFFERED]]
    return names


@_answering
def templates(prefix, parsed_args):
    """A template name: one of jj's builtins, or one this user saved.

    A saved one lives under `pyjj.templates.<name>` in the config, and
    only `jj config list` walks every layer that a name can come from.
    The call is short-lived and the answer is nothing when there is no
    `jj` to ask, which is the same shape as every other failure here.
    """
    return list(_BUILTIN_TEMPLATES) + _saved_template_names(parsed_args)


def _saved_template_names(parsed_args):
    """The names under `pyjj.templates.` this repository can see."""
    import subprocess

    cwd = getattr(parsed_args, "repository", None) or os.getcwd()
    try:
        result = subprocess.run(
            ["jj", "--no-pager", "config", "list", "--include-defaults=false",
             "pyjj.templates"],
            cwd=cwd, capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    names = []
    for line in result.stdout.splitlines():
        key = line.split("=", 1)[0].strip()
        if key.startswith("pyjj.templates."):
            names.append(key[len("pyjj.templates."):].strip('"'))
    return names


@_answering
def filesets(prefix, parsed_args):
    """A path in the working copy, as a fileset names one.

    A fileset is a language, but the shape a reader types most is a
    plain path, so this offers what is on disk beside the cursor.
    """
    import glob

    # The prefix is a literal, so `[`, `?` and `*` in it name
    # themselves. Passing it to `glob` unescaped would read a file
    # called `a[1].txt` as a pattern and match nothing.
    return [
        name + "/" if os.path.isdir(name) else name
        for name in glob.glob(glob.escape(prefix) + "*")
    ]


@_answering
def workspaces(prefix, parsed_args):
    """A workspace name this repository holds."""
    loaded = _repo(parsed_args)
    return [] if loaded is None else list(loaded[2].view())



@_answering
def saved_templates(prefix, parsed_args):
    """A template this user saved, which is what `pyjj templates` names."""
    return _saved_template_names(parsed_args)


# What a metavar says the argument takes. jj writes the same word on an
# option and on the positional that means the same thing, so the
# metavar is where the kind is already declared -- reading it reaches
# `jj new`'s parents and `jj rebase -d` in one pass, and whatever is
# declared next without anybody remembering to.
_BY_METAVAR = {
    "REVSET": revsets,
    "REVSETS": revsets,
    "OPERATION": operations,
    "BOOKMARK": bookmarks,
    "BOOKMARKS": bookmarks,
    "TAG": tags,
    "TAGS": tags,
    "REMOTE": remotes,
    "REMOTES": remotes,
    "TEMPLATE": templates,
    "FILESETS": filesets,
    "PATHS": filesets,
    "WORKSPACE": workspaces,
}

# A positional with no metavar of its own, named by what it holds.
_BY_DEST = {
    "revisions": revsets,
    "revisions_pos": revsets,
    "revision_pos": revsets,
    "parents_pos": revsets,
    "operation": operations,
    "operations": operations,
    "operation_pos": operations,
    "filesets": filesets,
    "paths": filesets,
    "paths_pos": filesets,
}

# `name` and `names` mean whatever the command names, so the command
# decides. The key is the word after `pyjj` in the parser's own `prog`.
_NAMES_BY_COMMAND = {
    "bookmark": local_bookmarks,
    "tag": tags,
    "workspace": workspaces,
    "templates": saved_templates,
}

# Two bookmark subcommands name a remote bookmark rather than a local
# one, since tracking is what they turn on and off.
_REMOTE_BOOKMARK_SUBCOMMANDS = ("track", "untrack")


def _for(action, words):
    """The completer for one argument, or `None` if nothing fits.

    `words` is the parser's own `prog`, split -- `pyjj bookmark delete`
    -- which is what tells a bookmark name from a tag name.
    """
    if action.metavar in _BY_METAVAR:
        return _BY_METAVAR[action.metavar]
    if action.dest in _BY_DEST:
        return _BY_DEST[action.dest]
    if action.dest not in ("name", "names"):
        return None
    if len(words) > 1 and words[1] == "bookmark":
        if words[-1] in _REMOTE_BOOKMARK_SUBCOMMANDS:
            return bookmarks
        return local_bookmarks
    return _NAMES_BY_COMMAND.get(words[1]) if len(words) > 1 else None


def attach(parser) -> None:
    """Give every argument of `parser` the completer for its kind.

    Walks the subcommands too, since that is where nearly every
    argument is. An argument that already carries a completer keeps it:
    a parser that knows better than its metavar says so itself.
    """
    words = parser.prog.split()
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            # A subparsers action: its choices are the subcommands.
            for subparser in choices.values():
                attach(subparser)
            continue
        if getattr(action, "completer", None) is not None:
            continue
        completer = _for(action, words)
        if completer is not None:
            action.completer = completer
