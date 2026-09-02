#!/usr/bin/env python3
"""pyjj-cli — Python CLI for Jujutsu VCS, backed by the pyjj Rust bindings.

Command and argument shapes mirror the real `jj` CLI so that the parity
suite (pyjj/tests/parity) can run the same argv through both tools.
"""

import argparse
import sys

import argcomplete

# Imported after argcomplete.autocomplete() below: this pulls in pyjj and
# with it the Rust extension module, which must not load on every <TAB>.
from .commands import (
    abandon,
    absorb,
    bookmark,
    bookmark_advance,
    bookmark_track,
    bookmark_untrack,
    commit,
    config_get,
    config_list,
    config_set,
    config_unset,
    describe,
    diff,
    diffedit,
    duplicate,
    edit,
    evolog,
    file_annotate,
    file_chmod,
    file_list,
    file_search,
    file_show,
    file_track,
    file_untrack,
    fix,
    git_clone,
    git_colocation,
    git_export,
    git_fetch,
    git_import,
    git_init,
    git_push,
    git_remote,
    git_root,
    hunk_commit,
    hunk_list,
    hunk_schema,
    hunk_split,
    hunk_squash,
    interdiff,
    log,
    metaedit,
    new,
    next_commit,
    op_abandon,
    op_diff,
    op_integrate,
    op_log,
    op_restore,
    op_revert,
    op_show,
    parallelize,
    prev_commit,
    redo,
    resolve,
    restore,
    rebase,
    revert,
    show,
    sign,
    sparse_edit,
    sparse_list,
    sparse_reset,
    sparse_set,
    squash,
    split,
    status,
    tag_delete,
    tag_list,
    tag_set,
    tag_track,
    tag_untrack,
    undo,
    unsign,
    version,
    workspace_add,
    workspace_forget,
    workspace_list,
    workspace_rename,
    workspace_root,
    workspace_update_stale,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyjj",
        description="Jujutsu VCS — Python CLI (pyjj bindings)",
    )
    parser.add_argument(
        "-R", "--repository", dest="repository", default=".",
        help="Path to the workspace to operate on (default: .)",
    )
    sub = parser.add_subparsers(dest="command")

    # git
    p_git = sub.add_parser("git", help="Git interop commands")
    git_sub = p_git.add_subparsers(dest="git_command")
    p_ginit = git_sub.add_parser("init", help="Create a new jj repo backed by Git")
    p_ginit.add_argument("destination", nargs="?", default=".", help="Destination directory")
    p_gclone = git_sub.add_parser("clone", help="Create a new repo backed by a clone of a Git repo")
    p_gclone.add_argument("source", help="URL or path of the Git repo to clone")
    p_gclone.add_argument("destination", nargs="?", help="Target directory for the clone")
    p_gclone.add_argument("--remote", dest="remote_name", default="origin", metavar="REMOTE_NAME",
                          help="Name of the newly created remote (default: origin)")
    p_gclone.add_argument("--colocate", dest="colocate", action="store_true", default=True,
                          help="Colocate the Jujutsu repo with the git repo (default)")
    p_gclone.add_argument("--no-colocate", dest="colocate", action="store_false",
                          help="Disable colocation")
    p_gclone.add_argument("--depth", dest="depth", type=int, default=None, metavar="DEPTH",
                          help="Create a shallow clone of the given depth")
    p_gclone.add_argument("-b", "--branch", dest="branches", action="append", default=None,
                          metavar="BRANCH", help="Branch to fetch (repeatable)")
    p_gclone.add_argument("-t", "--tag", dest="tags", action="append", default=None,
                          metavar="TAG", help="Tag to fetch (repeatable)")
    p_gclone.add_argument("--object-hash", dest="object_hash", default=None, metavar="OBJECT_HASH",
                          help="Object hash algorithm for the local Git repository")
    p_gcolocation = git_sub.add_parser("colocation", help="Manage Jujutsu repository colocation with Git")
    colocation_sub = p_gcolocation.add_subparsers(dest="colocation_command")
    p_gcol_status = colocation_sub.add_parser("status", help="Show the current colocation status")
    p_gcol_enable = colocation_sub.add_parser("enable", help="Convert into a colocated Jujutsu/Git repository")
    p_gcol_disable = colocation_sub.add_parser("disable", help="Convert into a non-colocated Jujutsu/Git repository")
    p_gfetch = git_sub.add_parser("fetch", help="Fetch from a Git remote")
    p_gfetch.add_argument("--remote", dest="remote", default=None, metavar="REMOTE",
                          help="The remote to fetch from")
    p_gfetch.add_argument("-b", "--branch", dest="branches", action="append", default=None,
                          metavar="BRANCH", help="Branch to fetch (repeatable)")
    p_gfetch.add_argument("-t", "--tag", dest="tags", action="append", default=None,
                          metavar="TAG", help="Tag to fetch (repeatable)")
    p_gfetch.add_argument("--tracked", dest="tracked", action="store_true", help="Fetch only tracked bookmarks and tags")
    p_gfetch.add_argument("--all-remotes", dest="all_remotes", action="store_true", help="Fetch from all remotes")
    p_gimport = git_sub.add_parser("import", help="Update repo with changes made in the underlying Git repo")
    p_gexport = git_sub.add_parser("export", help="Update the underlying Git repo with changes made in the repo")
    p_gpush = git_sub.add_parser("push", help="Push to a Git remote")
    p_gpush.add_argument("--remote", dest="remote", default=None, metavar="REMOTE",
                         help="The remote to push to")
    p_gpush.add_argument("-b", "--bookmark", dest="bookmarks", action="append", default=None,
                         metavar="BOOKMARK", help="Bookmark to push (repeatable)")
    p_gpush.add_argument("-t", "--tag", dest="tags", action="append", default=None,
                         metavar="TAG", help="Tag to push (repeatable)")
    p_gpush.add_argument("--all", dest="all_flag", action="store_true", help="Push all bookmarks and tags")
    p_gpush.add_argument("--tracked", dest="tracked", action="store_true", help="Push all tracked bookmarks and tags")
    p_gpush.add_argument("--deleted", dest="deleted", action="store_true", help="Push all deleted bookmarks and tags")
    p_gpush.add_argument("--allow-empty-description", dest="allow_empty", action="store_true", help="Allow pushing commits with empty descriptions")
    p_gpush.add_argument("--allow-private", dest="allow_private", action="store_true", help="Allow pushing commits that are private")
    p_gpush.add_argument("--allow-conflicts", dest="allow_conflicts", action="store_true", help="Allow pushing commits that contain conflicts")
    p_gpush.add_argument("--dry-run", dest="dry_run", action="store_true", help="Show what would be pushed without actually pushing")
    p_gpush.add_argument("-c", "--change", dest="changes", action="append", default=None,
                         metavar="REVSETS", help="Push this commit by creating a bookmark")
    p_gpush.add_argument("--named", dest="named", action="append", default=None,
                         metavar="NAME@REV", help="Push a revision as a named bookmark")
    p_gremote = git_sub.add_parser("remote", help="Manage Git remotes")
    remote_sub = p_gremote.add_subparsers(dest="remote_command")
    p_gr_list = remote_sub.add_parser("list", help="List Git remotes")
    p_gr_add = remote_sub.add_parser("add", help="Add a Git remote")
    p_gr_add.add_argument("name", help="Remote name")
    p_gr_add.add_argument("url", help="Remote URL")
    p_gr_remove = remote_sub.add_parser("remove", help="Remove a Git remote")
    p_gr_remove.add_argument("name", help="Remote name")
    p_gr_rename = remote_sub.add_parser("rename", help="Rename a Git remote")
    p_gr_rename.add_argument("old", help="Old remote name")
    p_gr_rename.add_argument("new", help="New remote name")
    p_gr_set_url = remote_sub.add_parser("set-url", help="Set the URL of a Git remote")
    p_gr_set_url.add_argument("name", help="Remote name")
    p_gr_set_url.add_argument("--url", dest="url", default=None, help="New URL")
    p_gr_set_url.add_argument("--push-url", dest="push_url", default=None, help="New push URL")
    p_groot = git_sub.add_parser("root", help="Show the underlying Git directory")

    # status
    sub.add_parser("status", help="Show working copy status")

    # log
    p_log = sub.add_parser("log", help="Show commit history")
    p_log.add_argument("-r", "--revisions", dest="revisions", default=None, metavar="REVSETS",
                       help="Which revisions to show (revset)")
    p_log.add_argument("-n", "--limit", type=int, default=10, metavar="LIMIT",
                       help="Max commits to show (default: 10)")
    p_log.add_argument("-G", "--no-graph", action="store_true", help="Don't show the graph")
    p_log.add_argument("-T", "--template", dest="template", default=None, metavar="TEMPLATE",
                       help=argparse.SUPPRESS)
    p_log.add_argument("-p", "--patch", action="store_true", help="Show patch")
    p_log.add_argument("filesets", nargs="*", metavar="FILESETS", help=argparse.SUPPRESS)

    # diff
    p_diff = sub.add_parser("diff", help="Compare file contents between two revisions")
    p_diff.add_argument("-r", "--revisions", dest="revisions", default=None, metavar="REVSETS",
                        help="Show changes in these revisions")
    p_diff.add_argument("-f", "--from", dest="from_", default=None, metavar="REVSET",
                        help="Show changes from this revision")
    p_diff.add_argument("-t", "--to", dest="to", default=None, metavar="REVSET",
                        help="Show changes to this revision")
    p_diff.add_argument("-s", "--summary", action="store_true", help="Show only summary")
    p_diff.add_argument("--stat", action="store_true", help="Show histogram")
    p_diff.add_argument("--name-only", action="store_true", help="Show only path")
    p_diff.add_argument("--git", action="store_true", help="Show Git-format diff")
    p_diff.add_argument("-T", "--template", dest="template", default=None, metavar="TEMPLATE",
                        help=argparse.SUPPRESS)
    p_diff.add_argument("filesets", nargs="*", metavar="FILESETS", help="Paths to restrict diff to")

    # show
    p_show = sub.add_parser("show", help="Show revision metadata and diff")
    p_show.add_argument("revisions", nargs="*", metavar="REVSETS", help="Revisions to show (default: @)")
    p_show.add_argument("-T", "--template", dest="template", default=None, metavar="TEMPLATE",
                        help=argparse.SUPPRESS)
    p_show.add_argument("-s", "--summary", action="store_true", help="Show only summary")
    p_show.add_argument("--stat", action="store_true", help="Show histogram")
    p_show.add_argument("--name-only", action="store_true", help="Show only path")
    p_show.add_argument("--git", action="store_true", help="Show Git-format diff")
    p_show.add_argument("--no-patch", action="store_true", help="Do not show patch")

    # file
    p_file = sub.add_parser("file", help="File operations")
    file_sub = p_file.add_subparsers(dest="file_command")
    p_flist = file_sub.add_parser("list", help="List files in a revision")
    p_flist.add_argument("-r", "--revision", dest="revision", default="@", metavar="REVSET",
                         help="Revision to list files for (default: @)")
    p_flist.add_argument("filesets", nargs="*", metavar="FILESETS", help="Paths to restrict to")
    p_fshow = file_sub.add_parser("show", help="Print contents of files in a revision")
    p_fshow.add_argument("-r", "--revision", dest="revision", default="@", metavar="REVSET",
                         help="Revision to show files from (default: @)")
    p_fshow.add_argument("filesets", nargs="+", metavar="FILESETS", help="Paths to show")
    p_fannot = file_sub.add_parser("annotate", help="Show line annotation (blame)")
    p_fannot.add_argument("-r", "--revision", dest="revision", default="@", metavar="REVSET",
                           help="Revision to annotate (default: @)")
    p_fannot.add_argument("path", metavar="PATH", help="File to annotate")
    p_fchmod = file_sub.add_parser("chmod", help="Sets or removes the executable bit for paths in the repo")
    p_fchmod.add_argument("-r", "--revision", dest="revision", default="@", metavar="REVSET", help="Revision to update (default: @)")
    p_fchmod.add_argument("--executable", dest="executable", action="store_true", help="Make the file executable")
    p_fchmod.add_argument("--normal", dest="normal", action="store_true", help="Make the file normal (non-executable)")
    p_fchmod.add_argument("paths", nargs="+", help="Paths to update")
    p_ftrack = file_sub.add_parser("track", help="Start tracking specified paths in the working copy")
    p_ftrack.add_argument("paths", nargs="+", help="Paths to track")
    p_funtrack = file_sub.add_parser("untrack", help="Stop tracking specified paths in the working copy")
    p_funtrack.add_argument("paths", nargs="+", help="Paths to untrack")
    p_fsearch = file_sub.add_parser("search", help="Search for content in files")
    p_fsearch.add_argument("-r", "--revision", dest="revision", default="@", help="Revision to search in (default: @)")
    p_fsearch.add_argument("pattern", help="Pattern to search for")

    # describe: -r REVSETS, repeatable -m MESSAGE, --stdin
    p_desc = sub.add_parser("describe", aliases=["desc"], help="Set commit descriptions")
    p_desc.add_argument("-r", "--revision", dest="revisions_opt", action="append",
                        default=None, metavar="REVSETS", help=argparse.SUPPRESS)
    p_desc.add_argument("revisions_pos", nargs="*", metavar="REVISIONS",
                        help="Revisions to describe (default: @)")
    p_desc.add_argument("-m", "--message", dest="messages", action="append",
                        default=None, metavar="MESSAGE",
                        help="Description text (repeatable; paragraphs joined)")
    p_desc.add_argument("--stdin", action="store_true",
                        help="Read description from stdin")

    # new
    p_new = sub.add_parser("new", help="Create a new empty change on top of REVSETS")
    p_new.add_argument("parents_pos", nargs="*", metavar="REVSETS",
                       help="Parent revisions (default: @)")
    p_new.add_argument("-m", "--message", dest="message", default="", metavar="MESSAGE",
                       help="Description of the new change")

    # bookmark create/set/delete/forget/list/move/rename
    p_bm = sub.add_parser("bookmark", help="Manage bookmarks")
    bm_sub = p_bm.add_subparsers(dest="bookmark_command")
    p_bmc = bm_sub.add_parser("create", help="Create a new bookmark")
    p_bmc.add_argument("names", nargs="+", metavar="NAMES")
    p_bmc.add_argument("-r", "--revision", default="@", metavar="REVSET",
                       help="Revision to point at (default: @)")
    p_bms = bm_sub.add_parser("set", help="Move an existing bookmark")
    p_bms.add_argument("name")
    p_bms.add_argument("-r", "--revision", required=True, metavar="REVSET")
    p_bmd = bm_sub.add_parser("delete", help="Delete a bookmark")
    p_bmd.add_argument("names", nargs="+", metavar="NAMES", help="Bookmarks to delete")
    p_bmf = bm_sub.add_parser("forget", help="Forget a bookmark")
    p_bmf.add_argument("names", nargs="+", metavar="NAMES", help="Bookmarks to forget")
    p_bml = bm_sub.add_parser("list", help="List bookmarks")
    p_bml.add_argument("names", nargs="*", metavar="NAMES", help="Bookmark names to list")
    p_bml.add_argument("-a", "--all-remotes", action="store_true", help=argparse.SUPPRESS)
    p_bmm = bm_sub.add_parser("move", help="Move bookmarks to a revision")
    p_bmm.add_argument("names", nargs="*", metavar="NAMES", help="Bookmark names to move")
    p_bmm.add_argument("-f", "--from", dest="from_", default=None, metavar="REVSETS",
                       help=argparse.SUPPRESS)
    p_bmm.add_argument("-t", "--to", dest="to", default="@", metavar="REVSET",
                       help="Target revision (default: @)")
    p_bmr = bm_sub.add_parser("rename", help="Rename a bookmark")
    p_bmr.add_argument("old", metavar="OLD", help="Old bookmark name")
    p_bmr.add_argument("new", metavar="NEW", help="New bookmark name")
    p_bmt = bm_sub.add_parser("track", help="Start tracking given remote bookmarks")
    p_bmt.add_argument("names", nargs="+", help="Bookmarks to track")
    p_bmt.add_argument("--remote", dest="remote", default=None, help="Remote to track")
    p_bmut = bm_sub.add_parser("untrack", help="Stop tracking given remote bookmarks")
    p_bmut.add_argument("names", nargs="+", help="Bookmarks to untrack")
    p_bmut.add_argument("--remote", dest="remote", default=None, help="Remote to untrack")
    p_bma = bm_sub.add_parser("advance", help="Advance the closest bookmarks to a target revision")
    p_bma.add_argument("-r", "--revision", dest="revision", default="@", help="Revision to advance to (default: @)")

    # squash
    p_sq = sub.add_parser("squash", help="Move changes from a revision into another")
    p_sq.add_argument("-r", "--revision", action="append", default=None,
                      metavar="REVSETS", help="Source revisions (default: @)")
    p_sq.add_argument("-f", "--from", dest="from_", action="append", default=None,
                      metavar="REVSETS", help="Source revisions")
    p_sq.add_argument("-t", "--into", dest="into", default=None, metavar="REVSET",
                      help="Destination revision (default: source's parent)")
    p_sq.add_argument("-u", "--use-destination-message", dest="use_destination_message",
                      action="store_true",
                      help="Keep destination's description unchanged")
    p_sq.add_argument("-m", "--message", dest="message", default=None, metavar="MESSAGE",
                      help="Description for the squashed revision")
    p_sq.add_argument("filesets", nargs="*", metavar="FILESETS",
                      help="Paths to squash (default: all)")

    # rebase
    p_re = sub.add_parser("rebase", help="Move revisions to a different parent")
    p_re.add_argument("-r", "--revision", dest="revisions", action="append", default=None,
                      metavar="REVSETS", help="Revisions to move (-r mode)")
    p_re.add_argument("-s", "--source", dest="sources", action="append", default=None,
                      metavar="REVSETS", help="Revisions to move with descendants (-s mode)")
    p_re.add_argument("-b", "--branch", dest="branches", action="append", default=None,
                      metavar="REVSETS", help="Branch to rebase (-b mode)")
    p_re.add_argument("-d", "--destination", dest="destinations", action="append", default=None,
                      metavar="REVSETS", help="New parent(s) (-d/--destination)")
    p_re.add_argument("-o", "--onto", dest="ontos", action="append", default=None,
                      metavar="REVSETS", help="New parent(s) (--onto synonym for -d)")
    p_re.add_argument("-A", "--insert-after", dest="insert_afters", action="append", default=None,
                      metavar="REVSETS", help="Insert after this revision")
    p_re.add_argument("-B", "--insert-before", dest="insert_befores", action="append", default=None,
                      metavar="REVSETS", help="Insert before this revision")

    # absorb
    p_ab = sub.add_parser("absorb", help="Move changes from a revision into ancestors")
    p_ab.add_argument("-f", "--from", dest="from_", default="@", metavar="REVSET",
                      help="Source revision to absorb from (default: @)")
    p_ab.add_argument("-t", "--into", "--to", dest="into", default=None, metavar="REVSETS",
                      help="Destination revisions to absorb into (default: mutable())")
    p_ab.add_argument("-i", "--interactive", action="store_true",
                      help="Interactively choose which parts to absorb")
    p_ab.add_argument("--tool", dest="tool", default=None, metavar="NAME",
                      help="Diff editor for interactive selection")
    p_ab.add_argument("filesets", nargs="*", metavar="FILESETS",
                      help="Paths to absorb (default: all)")

    # fix
    p_fix = sub.add_parser("fix", help="Update files with formatting fixes")
    p_fix.add_argument("-s", "--source", dest="source", default=None, metavar="REVSETS",
                       help="Fix files in revision(s) and descendants (default: reachable(@, mutable()))")
    p_fix.add_argument("--include-unchanged-files", dest="include_unchanged", action="store_true",
                       help="Fix unchanged files as well")
    p_fix.add_argument("filesets", nargs="*", metavar="FILESETS",
                       help="Paths to fix (default: all)")

    # revert
    p_rev = sub.add_parser("revert", help="Apply the reverse of given revisions")
    p_rev.add_argument("-r", "--revision", dest="revisions", action="append", default=None,
                       metavar="REVSETS", required=True,
                       help="Revision(s) to revert")
    p_rev.add_argument("-o", "--onto", dest="ontos", action="append", default=None,
                       metavar="REVSETS", help="Apply reverse on top of this revision")
    p_rev.add_argument("-d", "--destination", dest="destinations", action="append", default=None,
                       metavar="REVSETS", help="Alias for --onto")
    p_rev.add_argument("-A", "--insert-after", dest="insert_afters", action="append", default=None,
                       metavar="REVSETS", help="Insert after this revision")
    p_rev.add_argument("-B", "--insert-before", dest="insert_befores", action="append", default=None,
                       metavar="REVSETS", help="Insert before this revision")

    # abandon
    p_ab = sub.add_parser("abandon", help="Remove revisions (their descendants are rebased)")
    p_ab.add_argument("revisions_pos", nargs="*", metavar="REVISIONS",
                      help="Revisions to abandon (default: @)")

    # duplicate
    p_dup = sub.add_parser("duplicate", help="Duplicate revisions onto their parents")
    p_dup.add_argument("revisions_pos", nargs="*", metavar="REVISIONS",
                       help="Revisions to duplicate (default: @)")

    # edit
    p_edit = sub.add_parser("edit", help="Edit (check out) a specific revision")
    p_edit.add_argument("revision_pos", metavar="REVSETS",
                        help="The revision to edit")

    # commit
    p_com = sub.add_parser("commit",
                           help="Describe @ and create a new empty change on top")
    p_com.add_argument("-m", "--message", default=None, metavar="MESSAGE",
                       help="Description text")
    p_com.add_argument("--editor", action="store_true",
                       help="Open an editor to edit the description")
    p_com.add_argument("-i", "--interactive", action="store_true",
                       help="Interactively choose which changes to include")
    p_com.add_argument("--tool", default=None, metavar="NAME",
                       help="Diff editor to use (implies --interactive)")
    p_com.add_argument("paths_pos", nargs="*", metavar="FILESETS",
                       help="Paths staying in the current commit")

    # restore
    p_res = sub.add_parser("restore", help="Restore paths from another revision")
    p_res.add_argument("--from", dest="from_", default="@-", metavar="REVSET",
                       help="Revision to restore from (default: @-)")
    p_res.add_argument("--into", dest="into", default="@", metavar="REVSET",
                       help="Revision to restore into (default: @)")
    p_res.add_argument("paths_pos", nargs="*", metavar="FILESETS",
                       help="Paths to restore (default: all)")

    # split
    p_spl = sub.add_parser("split", help="Split a revision in two")
    p_spl.add_argument("-r", "--revision", default=None, metavar="REVSETS",
                       help="Revision to split (default: @)")
    p_spl.add_argument("-m", "--message", default=None, metavar="MESSAGE",
                       help="Description of the first half")
    p_spl.add_argument("--tool", default=None, metavar="NAME",
                       help="Diff editor for selecting changes (no FILESETS)")
    p_spl.add_argument("paths_pos", nargs="*", metavar="FILESETS",
                       help="Paths going into the first half")

    # diffedit
    p_de = sub.add_parser("diffedit",
                          help="Edit the diff between two revisions in a diff editor")
    p_de.add_argument("--from", dest="from_", default="@-", metavar="REVSET",
                      help="Show the diff FROM this revision (default: @-)")
    p_de.add_argument("--to", dest="into", default="@", metavar="REVSET",
                      help="Apply edits TO this revision (default: @)")
    p_de.add_argument("--tool", default=None, metavar="NAME",
                      help="Diff editor to use")
    p_rslv = sub.add_parser("resolve",
                            help="Resolve conflicted files with an external merge tool")
    p_rslv.add_argument("-r", "--revision", default="@", metavar="REVSET",
                        help="The revision to resolve conflicts in (default: @)")
    p_rslv.add_argument("-l", "--list", dest="list_", action="store_true",
                        help="Instead of resolving conflicts, list all the conflicts")
    p_rslv.add_argument("--tool", default=None, metavar="NAME",
                        help="3-way merge tool to be used; :ours and :theirs pick side #1/#2")
    p_rslv.add_argument("paths_pos", nargs="*", metavar="FILESETS",
                        help="Only resolve conflicts in these paths")

    # hunk (AI agent granular selection)
    p_hunk = sub.add_parser("hunk", help="Hunk-level selection for AI agents (like jj-hunk)")
    p_hunk.add_argument("--json-schema", action="store_true", help="Dump JSON schema for LLM tool-calling and exit")
    hunk_sub = p_hunk.add_subparsers(dest="hunk_command")
    p_hunk_list = hunk_sub.add_parser("list", help="List hunks for a revision")
    p_hunk_list.add_argument("-r", "--revision", default="@", metavar="REVSET",
                             help="Revision to list hunks for (default: @)")
    p_hunk_list.add_argument("--format", choices=["json", "yaml", "text"], default="json",
                             help="Output format (default: json)")
    p_hunk_split = hunk_sub.add_parser("split", help="Split a revision with hunk/line spec")
    p_hunk_split.add_argument("-r", "--revision", default="@", metavar="REVSET",
                              help="Revision to split (default: @)")
    p_hunk_split.add_argument("--spec", dest="spec_flag", default=None, metavar="SPEC",
                              help="Spec string (JSON/YAML), alternative to positional <spec>")
    p_hunk_split.add_argument("--spec-file", dest="spec_file", default=None, metavar="PATH",
                              help="Read spec from file (JSON/YAML)")
    p_hunk_split.add_argument("--stdin", action="store_true", help="Read commit message from stdin")
    p_hunk_split.add_argument("spec", nargs="?", help="Spec JSON/YAML string or '-' for stdin")
    p_hunk_split.add_argument("message", nargs="?", help="Commit message for first half (or '-' for stdin)")
    p_hunk_commit = hunk_sub.add_parser("commit", help="Commit selected hunks from working copy")
    p_hunk_commit.add_argument("--spec", dest="spec_flag", default=None, metavar="SPEC",
                               help="Spec string (JSON/YAML), alternative to positional <spec>")
    p_hunk_commit.add_argument("--spec-file", dest="spec_file", default=None, metavar="PATH",
                               help="Read spec from file (JSON/YAML)")
    p_hunk_commit.add_argument("--stdin", action="store_true", help="Read commit message from stdin")
    p_hunk_commit.add_argument("spec", nargs="?", help="Spec JSON/YAML string or '-' for stdin")
    p_hunk_commit.add_argument("message", nargs="?", help="Commit message (or '-' for stdin)")
    p_hunk_squash = hunk_sub.add_parser("squash", help="Squash selected hunks into parent")
    p_hunk_squash.add_argument("-r", "--revision", default="@", metavar="REVSET",
                               help="Revision to squash (default: @)")
    p_hunk_squash.add_argument("--spec", dest="spec_flag", default=None, metavar="SPEC",
                               help="Spec string (JSON/YAML), alternative to positional <spec>")
    p_hunk_squash.add_argument("--spec-file", dest="spec_file", default=None, metavar="PATH",
                               help="Read spec from file (JSON/YAML)")
    p_hunk_squash.add_argument("spec", nargs="?", help="Spec JSON/YAML string or '-' for stdin")
    p_hunk_schema = hunk_sub.add_parser("schema", help="Dump JSON schema for LLM tool-calling")
    p_hunk_schema.add_argument("--format", choices=["json", "yaml"], default="json",
                               help="Output format (default: json)")

    # sparse
    p_sparse = sub.add_parser("sparse", help="Manage which paths are present in the working copy")
    sparse_sub = p_sparse.add_subparsers(dest="sparse_command")
    p_sparse_list = sparse_sub.add_parser("list", help="List the patterns that are currently present")
    p_sparse_set = sparse_sub.add_parser("set", help="Update the patterns that are present")
    p_sparse_set.add_argument("--add", dest="adds", action="append", default=None, metavar="ADD", help="Patterns to add")
    p_sparse_set.add_argument("--remove", dest="removes", action="append", default=None, metavar="REMOVE", help="Patterns to remove")
    p_sparse_set.add_argument("--clear", action="store_true", help="Include no files (combine with --add)")
    p_sparse_reset = sparse_sub.add_parser("reset", help="Reset the patterns to include all files")
    p_sparse_edit = sparse_sub.add_parser("edit", help="Start an editor to update the patterns")

    # workspace
    p_ws = sub.add_parser("workspace", help="Commands for working with workspaces")
    ws_sub = p_ws.add_subparsers(dest="workspace_command")
    p_ws_add = ws_sub.add_parser("add", help="Add a workspace")
    p_ws_add.add_argument("destination", help="Where to create the new workspace")
    p_ws_add.add_argument("--name", dest="name", default=None, help="A name for the workspace")
    p_ws_add.add_argument("-r", "--revision", dest="revisions", action="append", default=None, metavar="REVSETS", help="Parent revisions for the new workspace")
    p_ws_forget = ws_sub.add_parser("forget", help="Stop tracking a workspace")
    p_ws_forget.add_argument("names", nargs="+", help="Workspaces to forget")
    p_ws_list = ws_sub.add_parser("list", help="List workspaces")
    p_ws_list.add_argument("-T", "--template", dest="template", default=None, help=argparse.SUPPRESS)
    p_ws_rename = ws_sub.add_parser("rename", help="Renames the current workspace")
    p_ws_rename.add_argument("new_name", help="New workspace name")
    p_ws_root = ws_sub.add_parser("root", help="Show the workspace root directory")
    p_ws_update = ws_sub.add_parser("update-stale", help="Update a workspace that has become stale")
    sub.add_parser("root", help="Show the current workspace root directory (shortcut for `jj workspace root`)")

    # tag
    p_tag = sub.add_parser("tag", help="Manage tags")
    tag_sub = p_tag.add_subparsers(dest="tag_command")
    p_tag_list = tag_sub.add_parser("list", help="List tags")
    p_tag_list.add_argument("names", nargs="*", help="Tags to list")
    p_tag_set = tag_sub.add_parser("set", help="Create or update tags")
    p_tag_set.add_argument("names", nargs="+", help="Tags to set")
    p_tag_set.add_argument("-r", "--revision", dest="revision", default="@", help="Revision to point at (default: @)")
    p_tag_delete = tag_sub.add_parser("delete", help="Delete existing tags")
    p_tag_delete.add_argument("names", nargs="+", help="Tags to delete")
    p_tag_track = tag_sub.add_parser("track", help="Start tracking given remote tags")
    p_tag_track.add_argument("names", nargs="+", help="Tags to track")
    p_tag_track.add_argument("--remote", dest="remote", default=None, help="Remote to track")
    p_tag_untrack = tag_sub.add_parser("untrack", help="Stop tracking given remote tags")
    p_tag_untrack.add_argument("names", nargs="+", help="Tags to untrack")
    p_tag_untrack.add_argument("--remote", dest="remote", default=None, help="Remote to untrack")

    # config
    p_config = sub.add_parser("config", help="Manage config options")
    config_sub = p_config.add_subparsers(dest="config_command")
    p_cfg_get = config_sub.add_parser("get", help="Get the value of a given config option")
    p_cfg_get.add_argument("name", help="Config option name")
    p_cfg_list = config_sub.add_parser("list", help="List variables set in config files")
    p_cfg_list.add_argument("name", nargs="?", help="Optional config name prefix")
    p_cfg_set = config_sub.add_parser("set", help="Update config file to set the given option")
    p_cfg_set.add_argument("--repo", action="store_true", help="Update repo config")
    p_cfg_set.add_argument("name", help="Config option name")
    p_cfg_set.add_argument("value", help="Config value")
    p_cfg_unset = config_sub.add_parser("unset", help="Update config file to unset the given option")
    p_cfg_unset.add_argument("--repo", action="store_true", help="Update repo config")
    p_cfg_unset.add_argument("name", help="Config option name")
    p_cfg_edit = config_sub.add_parser("edit", help="Start an editor on a jj config file")
    p_cfg_gc = config_sub.add_parser("gc", help="Find and optionally delete repo-level config")
    p_cfg_path = config_sub.add_parser("path", help="Print the paths to the config files")

    # sign / unsign
    p_sign = sub.add_parser("sign", help="Cryptographically sign a revision")
    p_sign.add_argument("-r", "--revision", dest="revisions", action="append", default=None, metavar="REVSETS", help="Revision to sign (can be repeated)")
    p_sign.add_argument("--key", dest="key", default=None, help=argparse.SUPPRESS)
    p_unsign = sub.add_parser("unsign", help="Drop a cryptographic signature")
    p_unsign.add_argument("-r", "--revision", dest="revisions", action="append", default=None, metavar="REVSETS", help="Revision to unsign (can be repeated)")

    # operation-level
    sub.add_parser("undo", help="Undo the last operation")
    sub.add_parser("redo", help="Redo a previously undone operation")
    p_op = sub.add_parser("op", help="Operation log commands")
    op_sub = p_op.add_subparsers(dest="op_command")
    p_opr = op_sub.add_parser("restore", help="Restore to the state of an operation")
    p_opr.add_argument("operation_pos", metavar="OPERATION",
                       help="The operation to restore to")
    p_op_log2 = op_sub.add_parser("log", help="Show the operation log")
    p_op_show2 = op_sub.add_parser("show", help="Show changes to the repository in an operation")
    p_op_show2.add_argument("operation", nargs="?", help="Operation to show")
    p_op_abandon2 = op_sub.add_parser("abandon", help="Abandon operation history")
    p_op_abandon2.add_argument("operations", nargs="+", help="Operations to abandon")
    p_op_diff2 = op_sub.add_parser("diff", help="Compare changes to the repository between two operations")
    p_op_diff2.add_argument("from", help="From operation")
    p_op_diff2.add_argument("to", help="To operation")
    p_op_integrate2 = op_sub.add_parser("integrate", help="Make an operation part of the operation log")
    p_op_integrate2.add_argument("operation", help="Operation to integrate")
    p_op_revert2 = op_sub.add_parser("revert", help="Create a new operation that reverts an earlier operation")
    p_op_revert2.add_argument("operation", help="Operation to revert")
    p_oplog = sub.add_parser("operation", help="Commands for working with the operation log")
    oplog_sub = p_oplog.add_subparsers(dest="oplog_command")
    p_oplog_log = oplog_sub.add_parser("log", help="Show the operation log")
    p_oplog_show = oplog_sub.add_parser("show", help="Show changes to the repository in an operation")
    p_oplog_show.add_argument("operation", nargs="?", help="Operation to show")
    p_oplog_abandon = oplog_sub.add_parser("abandon", help="Abandon operation history")
    p_oplog_abandon.add_argument("operations", nargs="+", help="Operations to abandon")
    p_oplog_diff = oplog_sub.add_parser("diff", help="Compare changes to the repository between two operations")
    p_oplog_diff.add_argument("from", help="From operation")
    p_oplog_diff.add_argument("to", help="To operation")
    p_oplog_restore2 = oplog_sub.add_parser("restore", help="Restore to the state of an operation")
    p_oplog_restore2.add_argument("operation", help="Operation to restore to")
    p_oplog_integrate = oplog_sub.add_parser("integrate", help="Make an operation part of the operation log")
    p_oplog_integrate.add_argument("operation", help="Operation to integrate")
    p_oplog_revert = oplog_sub.add_parser("revert", help="Create a new operation that reverts an earlier operation")
    p_oplog_revert.add_argument("operation", help="Operation to revert")
    p_evolog = sub.add_parser("evolog", help="Show how a change has evolved over time")
    p_evolog.add_argument("-r", "--revisions", dest="revisions", default="@", help="Revisions to follow (default: @)")
    p_evolog.add_argument("-n", "--limit", dest="limit", type=int, default=None, help="Limit number of revisions")
    p_next = sub.add_parser("next", help="Move the working-copy commit to the child revision")
    p_next.add_argument("amount", nargs="?", type=int, default=1, help="Number of revisions to move")
    p_prev = sub.add_parser("prev", help="Change the working copy revision relative to the parent revision")
    p_prev.add_argument("amount", nargs="?", type=int, default=1, help="Number of revisions to move")
    sub.add_parser("parallelize", help="Parallelize revisions by making them siblings")
    sub.add_parser("interdiff", help="Show differences between the diffs of two revisions")
    p_meta = sub.add_parser("metaedit", help="Modify metadata of a revision without changing content")
    p_meta.add_argument("-r", "--revision", dest="revision", default="@", help="Revision to modify")
    p_meta.add_argument("--author", dest="author", default=None, help="Set author")
    p_meta.add_argument("--committer", dest="committer", default=None, help="Set committer")
    # Stubs for remaining jj commands to reach help parity
    sub.add_parser("arrange", help="Interactively arrange the commit graph")
    p_bisect = sub.add_parser("bisect", help="Find a bad revision by bisection")
    p_bisect.add_argument("--range", dest="range", default=None, help=argparse.SUPPRESS)
    sub.add_parser("gerrit", help="Interact with Gerrit Code Review")
    sub.add_parser("help", help="Print this message or the help of the given subcommand(s)")
    p_run = sub.add_parser("run", help="Run a command across a set of revisions")
    p_run.add_argument("-r", "--revision", dest="revisions", default=None, help=argparse.SUPPRESS)
    sub.add_parser("simplify-parents", help="Simplify parent edges for the specified revision(s)")
    sub.add_parser("util", help="Infrequently used commands such as for generating shell completions")
    sub.add_parser("bench", help="Benchmarking commands")
    sub.add_parser("debug", help="Low-level commands not intended for users")

    # version
    sub.add_parser("version", help="Show version information")

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    # Completion runs the CLI itself on every <TAB>; keep everything heavy
    # out of that path.
    argcomplete.autocomplete(parser)
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 1

    commands = {
        "git": lambda a: {
            "init": git_init,
            "clone": git_clone,
            "fetch": git_fetch,
            "push": git_push,
            "import": git_import,
            "export": git_export,
            "remote": git_remote,
            "root": git_root,
            "colocation": git_colocation,
        }.get(a.git_command or "", _git_help)(a),
        "status": status,
        "log": log,
        "diff": diff,
        "show": show,
        "file": lambda a: {
            "list": file_list, "show": file_show, "annotate": file_annotate,
            "chmod": file_chmod, "track": file_track, "untrack": file_untrack, "search": file_search,
        }.get(a.file_command or "", _file_help)(a),
        "describe": describe,
        "new": new,
        "bookmark": lambda a: {
            "create": bookmark, "set": bookmark, "delete": bookmark, "forget": bookmark, "list": bookmark,
            "move": bookmark, "rename": bookmark, "track": bookmark_track, "untrack": bookmark_untrack, "advance": bookmark_advance,
        }.get(a.bookmark_command or "", _bm_help)(a),
        "squash": squash,
        "rebase": rebase,
        "absorb": absorb,
        "fix": fix,
        "revert": revert,
        "abandon": abandon,
        "duplicate": duplicate,
        "edit": edit,
        "commit": commit,
        "restore": restore,
        "split": split,
        "diffedit": diffedit,
        "resolve": resolve,
        "evolog": evolog,
        "next": next_commit,
        "prev": prev_commit,
        "parallelize": parallelize,
        "interdiff": interdiff,
        "arrange": lambda a: (print("Error: arrange is not yet supported", file=sys.stderr), 2)[1],
        "bisect": lambda a: (print("Error: bisect is not yet supported", file=sys.stderr), 2)[1],
        "gerrit": lambda a: (print("Error: gerrit is not yet supported", file=sys.stderr), 2)[1],
        "help": lambda a: (print("Error: help is not yet supported", file=sys.stderr), 2)[1],
        "run": lambda a: (print("Error: run is not yet supported", file=sys.stderr), 2)[1],
        "simplify-parents": lambda a: (print("Error: simplify-parents is not yet supported", file=sys.stderr), 2)[1],
        "util": lambda a: (print("Error: util is not yet supported", file=sys.stderr), 2)[1],
        "bench": lambda a: (print("Error: bench is not yet supported", file=sys.stderr), 2)[1],
        "debug": lambda a: (print("Error: debug is not yet supported", file=sys.stderr), 2)[1],
        "sparse": lambda a: {
            "list": sparse_list,
            "set": sparse_set,
            "reset": sparse_reset,
            "edit": sparse_edit,
        }.get(a.sparse_command or "", _sparse_help)(a),
        "workspace": lambda a: {
            "add": workspace_add,
            "forget": workspace_forget,
            "list": workspace_list,
            "rename": workspace_rename,
            "root": workspace_root,
            "update-stale": workspace_update_stale,
        }.get(a.workspace_command or "", _workspace_help)(a),
        "root": workspace_root,
        "tag": lambda a: {
            "list": tag_list, "set": tag_set, "delete": tag_delete,
            "track": tag_track, "untrack": tag_untrack,
        }.get(a.tag_command or "", _tag_help)(a),
        "config": lambda a: {
            "get": config_get, "list": config_list, "set": config_set, "unset": config_unset,
            "edit": lambda a: (print("Error: config edit is not yet supported", file=sys.stderr), 2)[1],
            "gc": lambda a: (print("Error: config gc is not yet supported", file=sys.stderr), 2)[1],
            "path": lambda a: (print("Error: config path is not yet supported", file=sys.stderr), 2)[1],
        }.get(a.config_command or "", _config_help)(a),
        "sign": sign,
        "unsign": unsign,
        "metaedit": metaedit,
        "hunk": lambda a: hunk_schema(a) if getattr(a, "json_schema", False) else {
            "list": hunk_list,
            "split": hunk_split,
            "commit": hunk_commit,
            "squash": hunk_squash,
            "schema": hunk_schema,
        }.get(a.hunk_command or "", _hunk_help)(a),
        "undo": undo,
        "redo": redo,
        "op": lambda a: {
            "restore": op_restore, "log": op_log, "show": op_show, "abandon": op_abandon, "diff": op_diff,
            "integrate": op_integrate, "revert": op_revert,
        }.get(a.op_command or "", _op_help)(a),
        "operation": lambda a: {
            "restore": op_restore, "log": op_log, "show": op_show, "abandon": op_abandon, "diff": op_diff,
            "integrate": op_integrate, "revert": op_revert,
        }.get(a.oplog_command or "", _op_help)(a),
        "version": version,
    }
    return commands[args.command](args)


def _git_help(args) -> int:
    print("usage: pyjj git {init,clone,fetch,push,import,export,remote,root}", file=sys.stderr)
    return 2


def _git_remote_help(args) -> int:
    print("usage: pyjj git remote {add,list,remove,rename,set-url}", file=sys.stderr)
    return 2


def _bm_help(args) -> int:
    print("usage: pyjj bookmark {create,set,delete,forget,list,move,rename}", file=sys.stderr)
    return 2


def _op_help(args) -> int:
    print("usage: pyjj op {restore}", file=sys.stderr)
    return 2


def _file_help(args) -> int:
    print("usage: pyjj file {list,show,annotate}", file=sys.stderr)
    return 2


def _sparse_help(args) -> int:
    print("usage: pyjj sparse {list,set,reset,edit}", file=sys.stderr)
    return 2


def _workspace_help(args) -> int:
    print("usage: pyjj workspace {add,forget,list,rename,root,update-stale}", file=sys.stderr)
    return 2


def _tag_help(args) -> int:
    print("usage: pyjj tag {list,set,delete}", file=sys.stderr)
    return 2


def _config_help(args) -> int:
    print("usage: pyjj config {get,list,set,unset}", file=sys.stderr)
    return 2


def _hunk_help(args) -> int:
    print("usage: pyjj hunk {list,split,commit,squash,schema}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
