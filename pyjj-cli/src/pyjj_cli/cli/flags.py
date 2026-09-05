"""Shared flag helpers for pyjj-cli.

Many subcommands share the same flags (e.g. ``-r/--revision``,
``-m/--message``, ``--template``, ``filesets``). This module gives
them a single definition so help text, dest names and defaults stay
consistent. A tiny ``Flag`` enum lets a subcommand register a whole
set at once:

    from .flags import Flag, add_flags

    add_flags(p_log, {Flag.REVISIONS, Flag.LIMIT, Flag.TEMPLATE, Flag.PATCH, Flag.FILESETS})
    # or individually:
    add_revision_flag(p, dest="revision", default="@")

No heavy imports — only ``argparse`` and ``enum``.
"""

import argparse
from enum import Enum, auto


class Flag(Enum):
    """Reusable flag / positional sets. Each variant maps to one
    ``add_*`` helper below. Use ``add_flags(parser, {Flag.X, ...})``
    for the common case, or call ``add_*_flag`` directly when you need
    a non-default ``dest``/``required``/``default``."""

    # single revision, scalar -r/--revision (default @)
    REVISION = auto()
    # multi-revision, -r/--revisions (REVSETS, may be None)
    REVISIONS = auto()
    # the same flag where jj names it `--revision`, as `log` does
    REVISIONS_SINGULAR = auto()
    # -r/--revision with append (repeatable, e.g. bookmark/revert)
    REVISION_APPEND = auto()
    # -n/--limit
    LIMIT = auto()
    # -T/--template (suppressed help, as in real jj)
    TEMPLATE = auto()
    # -p/--patch
    PATCH = auto()
    # -G/--no-graph
    NO_GRAPH = auto()
    # -f/--from and -t/--to pair
    FROM = auto()
    TO = auto()
    # diff helpers
    SUMMARY = auto()
    STAT = auto()
    NAME_ONLY = auto()
    TYPES = auto()
    WHITESPACE = auto()
    # the same two, without the `-w` / `-b` aliases jj gives
    # only to the diff commands
    WHITESPACE_LONG = auto()
    GIT = auto()
    CONTEXT = auto()
    NO_PATCH = auto()
    # message
    MESSAGE = auto()
    MESSAGE_APPEND = auto()  # -m repeatable
    MESSAGE_OPT = auto()  # -m optional, dest message
    # filesets positional (often nargs="*")
    FILESETS = auto()
    FILESETS_REQUIRED = auto()  # nargs="+"
    # tool
    TOOL = auto()
    # `--tool` where it names a diff formatter, not an editor
    DIFF_TOOL = auto()
    # generic
    STDIN = auto()
    JSON_SCHEMA = auto()
    # rebase / move variants
    SOURCE = auto()  # -s/--source
    BRANCH = auto()  # -b/--branch
    DESTINATION = auto()  # -d/--destination
    ONTO = auto()  # -o/--onto
    INSERT_AFTER = auto()  # -A/--insert-after
    INSERT_BEFORE = auto()  # -B/--insert-before
    # squash
    USE_DEST_MESSAGE = auto()  # -u/--use-destination-message
    INTO = auto()  # -t/--into
    # git
    REMOTE = auto()
    BOOKMARK = auto()  # -b/--bookmark (push)
    TAG = auto()  # -t/--tag
    ALL = auto()
    TRACKED = auto()
    DELETED = auto()
    ALLOW_EMPTY = auto()
    ALLOW_PRIVATE = auto()
    ALLOW_CONFLICTS = auto()
    DRY_RUN = auto()
    CHANGE = auto()  # -c/--change
    NAMED = auto()
    DEPTH = auto()
    COLOCATE = auto()
    OBJECT_HASH = auto()
    ALL_REMOTES = auto()
    # file/bookmark/workspace etc.
    PATTERN = auto()  # -p/--pattern
    INCLUDE_IGNORED = auto()
    INCLUDE_UNCHANGED = auto()
    SOURCE_REVSET = auto()  # -s/--source for fix
    REVISION_POS = auto()  # positional REVISIONS
    PARENTS_POS = auto()
    PATHS_POS = auto()
    NAMES = auto()  # positional NAMES
    # workspace/sparse/tag/config
    ADD = auto()
    REMOVE = auto()
    CLEAR = auto()
    REPO_FLAG = auto()  # --repo
    KEY = auto()
    AUTHOR = auto()
    COMMITTER = auto()
    EDITOR = auto()
    INTERACTIVE = auto()
    AMOUNT = auto()
    RANGE = auto()


def add_revision_flag(parser: argparse.ArgumentParser, dest: str = "revision", default: str = "@", required: bool = False, help: str = "Revision to operate on (default: @)") -> None:
    parser.add_argument("-r", "--revision", dest=dest, default=default if not required else None, metavar="REVSET", required=required, help=help)


def add_revisions_flag(parser: argparse.ArgumentParser, dest: str = "revisions", required: bool = False, singular: bool = False) -> None:
    """`-r`, spelled the way the command spells it.

    Most commands write `--revisions` and take `--revision` as an
    alias; `log` writes the singular and has no plural. Both spellings
    are accepted either way, so only which one the help names differs.
    """
    names = (["-r", "--revision", "--revisions"] if singular
             else ["-r", "--revisions", "--revision"])
    parser.add_argument(*names, dest=dest, default=None, metavar="REVSETS", required=required, help="Which revisions to operate on (revset)")


def add_revision_append_flag(parser: argparse.ArgumentParser, dest: str = "revisions", help: str = "Revision to operate on (can be repeated)") -> None:
    parser.add_argument("-r", "--revision", dest=dest, action="append", default=None, metavar="REVSETS", help=help)


def add_limit_flag(parser: argparse.ArgumentParser, default: int = 10) -> None:
    parser.add_argument("-n", "--limit", type=int, default=default, metavar="LIMIT", help=f"Max commits to show (default: {default})")


def add_template_flag(parser: argparse.ArgumentParser, dest: str = "template") -> None:
    parser.add_argument("-T", "--template", dest=dest, default=None, metavar="TEMPLATE", help=argparse.SUPPRESS)


def add_patch_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-p", "--patch", action="store_true", help="Show patch")


def add_no_graph_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-G", "--no-graph", action="store_true", help="Don't show the graph")


def add_from_flag(parser: argparse.ArgumentParser, dest: str = "from_", default=None, help: str = "Show changes from this revision") -> None:
    parser.add_argument("-f", "--from", dest=dest, default=default, metavar="REVSET", help=help)


def add_to_flag(parser: argparse.ArgumentParser, dest: str = "to", default=None, help: str = "Show changes to this revision") -> None:
    parser.add_argument("-t", "--to", dest=dest, default=default, metavar="REVSET", help=help)


def add_summary_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-s", "--summary", action="store_true", help="Show only summary")


def add_stat_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--stat", action="store_true", help="Show histogram")


def add_name_only_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name-only", action="store_true", help="Show only path")


def add_types_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--types", action="store_true",
                        help="Show only the type of each path")


def add_whitespace_flags(parser: argparse.ArgumentParser,
                         short: bool = True) -> None:
    """How much whitespace a diff is allowed to ignore.

    jj makes the two exclusive, since a line cannot be compared two
    ways at once. `-w` and `-b` are the diff commands' own spelling:
    the log-like commands take the long names alone, so `short` turns
    the aliases off.
    """
    group = parser.add_mutually_exclusive_group()
    group.add_argument(*(["-w"] if short else []), "--ignore-all-space",
                       action="store_true",
                       help="Ignore whitespace when comparing lines")
    group.add_argument(*(["-b"] if short else []), "--ignore-space-change",
                       action="store_true",
                       help="Ignore changes in amount of whitespace when comparing lines")


def add_context_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--context", type=int, default=None, metavar="NUM",
                        help="Number of lines of context to show")


def add_git_flag(parser: argparse.ArgumentParser) -> None:
    """`--git` and `--color-words` pick the format that carries content.

    jj lets a command ask for one of these and one listing format at
    the same time, but never for both of these, so they share a
    mutually exclusive group.
    """
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--git", action="store_true", help="Show Git-format diff")
    group.add_argument("--color-words", action="store_true",
                       help="Show a word-level diff with changes indicated only by color")


def add_no_patch_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--no-patch", action="store_true", help="Do not show patch")


def add_message_flag(parser: argparse.ArgumentParser, dest: str = "message", required: bool = False, help: str = "Description text") -> None:
    parser.add_argument("-m", "--message", dest=dest, default=None, metavar="MESSAGE", required=required, help=help)


def add_message_append_flag(parser: argparse.ArgumentParser, dest: str = "messages") -> None:
    parser.add_argument("-m", "--message", dest=dest, action="append", default=None, metavar="MESSAGE", help="Description text (repeatable; paragraphs joined)")


def add_filesets_flag(parser: argparse.ArgumentParser, nargs: str = "*", help: str = "Paths to restrict to", required: bool = False) -> None:
    if nargs == "+":
        parser.add_argument("filesets", nargs="+", metavar="FILESETS", help=help)
    else:
        parser.add_argument("filesets", nargs="*", metavar="FILESETS", help=help)


def add_tool_flag(parser: argparse.ArgumentParser, help: str = "Diff editor to use") -> None:
    parser.add_argument("--tool", default=None, metavar="NAME", help=help)


def add_diff_tool_flag(parser: argparse.ArgumentParser) -> None:
    """`--tool` where it names a diff *formatter* rather than an editor.

    The two spellings are the same flag with different jobs: an editor
    is handed two directories to change, a formatter is handed them to
    describe. A leading `:` asks for one of jj's builtin formats.
    """
    parser.add_argument("--tool", default=None, metavar="TOOL",
                        help="Generate diff with an external command, or "
                             "with a builtin format as `:<name>`")


def add_stdin_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--stdin", action="store_true", help="Read description from stdin")


def add_source_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-s", "--source", dest="sources", action="append", default=None, metavar="REVSETS", help="Revisions to move with descendants (-s mode)")


def add_branch_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-b", "--branch", dest="branches", action="append", default=None, metavar="REVSETS", help="Branch to rebase (-b mode)")


def add_destination_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-d", "--destination", dest="destinations", action="append", default=None, metavar="REVSETS", help="New parent(s) (-d/--destination)")


def add_onto_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-o", "--onto", dest="ontos", action="append", default=None, metavar="REVSETS", help="New parent(s) (--onto synonym for -d)")


def add_insert_after_flag(parser: argparse.ArgumentParser) -> None:
    # jj spells this `-A`, `--insert-after` with `--after` as a visible
    # alias, and accepts all three.
    parser.add_argument("-A", "--insert-after", "--after", dest="insert_afters", action="append", default=None, metavar="REVSETS", help="Insert after this revision")


def add_insert_before_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-B", "--insert-before", "--before", dest="insert_befores", action="append", default=None, metavar="REVSETS", help="Insert before this revision")


def add_use_dest_message_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-u", "--use-destination-message", dest="use_destination_message", action="store_true", help="Keep destination's description unchanged")


def add_into_flag(parser: argparse.ArgumentParser, dest: str = "into", default=None, help: str = "Destination revision (default: source's parent)") -> None:
    parser.add_argument("-t", "--into", dest=dest, default=default, metavar="REVSET", help=help)


def add_remote_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--remote", dest="remote", default=None, metavar="REMOTE", help="The remote to fetch from")


def add_bookmark_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-b", "--bookmark", dest="bookmarks", action="append", default=None, metavar="BOOKMARK", help="Bookmark to push (repeatable)")


def add_tag_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-t", "--tag", dest="tags", action="append", default=None, metavar="TAG", help="Tag to push (repeatable)")


def add_all_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--all", dest="all_flag", action="store_true", help="Push all bookmarks and tags")


def add_tracked_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tracked", dest="tracked", action="store_true", help="Push all tracked bookmarks and tags")


def add_deleted_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--deleted", dest="deleted", action="store_true", help="Push all deleted bookmarks and tags")


def add_allow_empty_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--allow-empty-description", dest="allow_empty", action="store_true", help="Allow pushing commits with empty descriptions")


def add_allow_private_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--allow-private", dest="allow_private", action="store_true", help="Allow pushing commits that are private")


def add_allow_conflicts_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--allow-conflicts", dest="allow_conflicts", action="store_true", help="Allow pushing commits that contain conflicts")


def add_dry_run_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Show what would be pushed without actually pushing")


def add_change_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-c", "--change", dest="changes", action="append", default=None, metavar="REVSETS", help="Push this commit by creating a bookmark")


def add_named_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--named", dest="named", action="append", default=None, metavar="NAME@REV", help="Push a revision as a named bookmark")


def add_depth_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--depth", dest="depth", type=int, default=None, metavar="DEPTH", help="Create a shallow clone of the given depth")


def add_colocate_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--colocate", dest="colocate", action="store_true", default=True, help="Colocate the Jujutsu repo with the git repo (default)")
    parser.add_argument("--no-colocate", dest="colocate", action="store_false", help="Disable colocation")


def add_object_hash_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--object-hash", dest="object_hash", default=None, metavar="OBJECT_HASH", help="Object hash algorithm for the local Git repository")


def add_all_remotes_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--all-remotes", dest="all_remotes", action="store_true", help="Fetch from all remotes")


def add_pattern_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-p", "--pattern", dest="pattern", required=True, help="Pattern to search for")


def add_include_ignored_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--include-ignored", dest="include_ignored", action="store_true", help="Track ignored or too large files")


def add_include_unchanged_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--include-unchanged-files", dest="include_unchanged", action="store_true", help="Fix unchanged files as well")


def add_source_revset_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-s", "--source", dest="source", default=None, metavar="REVSETS", help="Fix files in revision(s) and descendants (default: reachable(@, mutable()))")


def add_add_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--add", dest="adds", action="append", default=None, metavar="ADD", help="Patterns to add")


def add_remove_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--remove", dest="removes", action="append", default=None, metavar="REMOVE", help="Patterns to remove")


def add_clear_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--clear", action="store_true", help="Include no files (combine with --add)")


def add_repo_flag(parser: argparse.ArgumentParser, help: str = "Update repo config") -> None:
    parser.add_argument("--repo", action="store_true", help=help)


def add_config_scope_flags(parser: argparse.ArgumentParser) -> None:
    """`--user`/`--repo`/`--workspace`: which config file to act on."""
    parser.add_argument("--user", action="store_true",
                        help="Target the user-level config")
    parser.add_argument("--repo", action="store_true",
                        help="Target the repo-level config")
    parser.add_argument("--workspace", action="store_true",
                        help="Target the workspace-level config")


def add_key_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--key", dest="key", default=None, help=argparse.SUPPRESS)


def add_author_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--author", dest="author", default=None, help="Set author")


def add_committer_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--committer", dest="committer", default=None, help="Set committer")


def add_json_schema_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json-schema", action="store_true", help="Dump JSON schema for LLM tool-calling and exit")


# Registry for add_flags(enum set)
_FLAG_HANDLERS = {
    Flag.REVISION: lambda p: add_revision_flag(p),
    Flag.REVISIONS: lambda p: add_revisions_flag(p),
    Flag.REVISIONS_SINGULAR: lambda p: add_revisions_flag(p, singular=True),
    Flag.REVISION_APPEND: lambda p: add_revision_append_flag(p),
    Flag.LIMIT: lambda p: add_limit_flag(p),
    Flag.TEMPLATE: lambda p: add_template_flag(p),
    Flag.PATCH: lambda p: add_patch_flag(p),
    Flag.NO_GRAPH: lambda p: add_no_graph_flag(p),
    Flag.FROM: lambda p: add_from_flag(p),
    Flag.TO: lambda p: add_to_flag(p),
    Flag.SUMMARY: lambda p: add_summary_flag(p),
    Flag.STAT: lambda p: add_stat_flag(p),
    Flag.NAME_ONLY: lambda p: add_name_only_flag(p),
    Flag.TYPES: lambda p: add_types_flag(p),
    Flag.WHITESPACE: lambda p: add_whitespace_flags(p),
    Flag.WHITESPACE_LONG: lambda p: add_whitespace_flags(p, short=False),
    Flag.GIT: lambda p: add_git_flag(p),
    Flag.CONTEXT: lambda p: add_context_flag(p),
    Flag.NO_PATCH: lambda p: add_no_patch_flag(p),
    Flag.MESSAGE: lambda p: add_message_flag(p),
    Flag.MESSAGE_APPEND: lambda p: add_message_append_flag(p),
    Flag.FILESETS: lambda p: add_filesets_flag(p, nargs="*"),
    Flag.FILESETS_REQUIRED: lambda p: add_filesets_flag(p, nargs="+"),
    Flag.TOOL: lambda p: add_tool_flag(p),
    Flag.DIFF_TOOL: lambda p: add_diff_tool_flag(p),
    Flag.STDIN: lambda p: add_stdin_flag(p),
    Flag.SOURCE: lambda p: add_source_flag(p),
    Flag.BRANCH: lambda p: add_branch_flag(p),
    Flag.DESTINATION: lambda p: add_destination_flag(p),
    Flag.ONTO: lambda p: add_onto_flag(p),
    Flag.INSERT_AFTER: lambda p: add_insert_after_flag(p),
    Flag.INSERT_BEFORE: lambda p: add_insert_before_flag(p),
    Flag.USE_DEST_MESSAGE: lambda p: add_use_dest_message_flag(p),
    Flag.INTO: lambda p: add_into_flag(p),
    Flag.REMOTE: lambda p: add_remote_flag(p),
    Flag.BOOKMARK: lambda p: add_bookmark_flag(p),
    Flag.TAG: lambda p: add_tag_flag(p),
    Flag.ALL: lambda p: add_all_flag(p),
    Flag.TRACKED: lambda p: add_tracked_flag(p),
    Flag.DELETED: lambda p: add_deleted_flag(p),
    Flag.ALLOW_EMPTY: lambda p: add_allow_empty_flag(p),
    Flag.ALLOW_PRIVATE: lambda p: add_allow_private_flag(p),
    Flag.ALLOW_CONFLICTS: lambda p: add_allow_conflicts_flag(p),
    Flag.DRY_RUN: lambda p: add_dry_run_flag(p),
    Flag.CHANGE: lambda p: add_change_flag(p),
    Flag.NAMED: lambda p: add_named_flag(p),
    Flag.DEPTH: lambda p: add_depth_flag(p),
    Flag.COLOCATE: lambda p: add_colocate_flag(p),
    Flag.OBJECT_HASH: lambda p: add_object_hash_flag(p),
    Flag.ALL_REMOTES: lambda p: add_all_remotes_flag(p),
    Flag.PATTERN: lambda p: add_pattern_flag(p),
    Flag.INCLUDE_IGNORED: lambda p: add_include_ignored_flag(p),
    Flag.INCLUDE_UNCHANGED: lambda p: add_include_unchanged_flag(p),
    Flag.SOURCE_REVSET: lambda p: add_source_revset_flag(p),
    Flag.ADD: lambda p: add_add_flag(p),
    Flag.REMOVE: lambda p: add_remove_flag(p),
    Flag.CLEAR: lambda p: add_clear_flag(p),
    Flag.REPO_FLAG: lambda p: add_repo_flag(p),
    Flag.KEY: lambda p: add_key_flag(p),
    Flag.AUTHOR: lambda p: add_author_flag(p),
    Flag.COMMITTER: lambda p: add_committer_flag(p),
    Flag.JSON_SCHEMA: lambda p: add_json_schema_flag(p),
}


def add_flags(parser: argparse.ArgumentParser, flags) -> None:
    """Register a set of shared flags on ``parser``.

    Example::

        add_flags(p_log, {Flag.REVISIONS, Flag.LIMIT, Flag.TEMPLATE, Flag.PATCH, Flag.FILESETS})
    """
    for flag in flags:
        handler = _FLAG_HANDLERS.get(flag)
        if handler is None:
            raise ValueError(f"Unknown flag {flag}")
        handler(parser)
