"""history subcommand: show."""
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

import pyjj
import pyjj.hunk as hunk_mod
from ...formatter import Line, render_block, separate
from ..common import (
    _bookmarks_by_commit,
    _commit_context,
    _detailed_signature,
    _diff_base,
    _indent,
    _print_diff,
    _resolve_template,
    _tags_by_commit,
    CommandError,
    _checkout_if_moved,
    _finish,
    _load,
    _resolve_all,
    _resolve_in_arg_order,
    _resolve_one,
    _restore_view_command,
    _wc_commit,
    complete_newline,
    join_message_paragraphs,
    _run_editor,
    _changed_files,
    _print_diff_stats,
    _run_diff_tool,
    _selection_is_empty,
    _merge_marker_len,
    _run_merge_tool,
    _fix_pattern_matches,
    _signature_spans,
    use_color,
)

def show(args) -> int:
    """`jj show` — a commit's metadata and its diff."""
    try:
        settings, ws, repo = _load(args)
        revs = args.revisions or ["@"]
        commits = _resolve_all(repo, settings, revs)
        bookmarks = _bookmarks_by_commit(repo, remotes=True)
        locals_ = _bookmarks_by_commit(repo)
        # jj lists the local names first and the remote ones after, and
        # colours a remote name's three parts apart.
        remotes: dict[str, list[tuple[str, str]]] = {}
        for remote_bookmark in repo.remote_bookmarks():
            for target in remote_bookmark.target_ids:
                remotes.setdefault(target.hex(), []).append(
                    (remote_bookmark.name, remote_bookmark.remote))
        tags = _tags_by_commit(repo)
        # jj drives `show` from `templates.show`, whose default is
        # `builtin_log_detailed`. A template replaces the header block;
        # the diff below it still prints, as it does for jj.
        builtins = {
            "builtin_log_detailed":
                "Commit ID: {{ commit_id }}\nChange ID: {{ change_id }}\n"
                "Author   : {{ author_detailed }}\nCommitter: {{ committer_detailed }}\n"
                "\n{{ description_indented }}\n",
        }
        template = _resolve_template(settings, ws, args, "show", builtins)
        for commit in commits:
            if template is not None:
                context = _commit_context(
                    repo, settings, commit, bookmarks.get(commit.id.hex(), [])
                )
                context["tags"] = tags.get(commit.id.hex(), [])
                context["author_detailed"] = _detailed_signature(commit.author)
                context["committer_detailed"] = _detailed_signature(commit.committer)
                context["description_indented"] = _indent(
                    commit.description.rstrip() or "(no description set)"
                )
                print(template.render(context))
                if not getattr(args, "no_patch", False):
                    _print_diff(args, ws, settings, _diff_base(repo, settings, commit),
                                commit, None)
                continue
            print(render_block(
                _detailed_lines(repo, settings, commit,
                                locals_.get(commit.id.hex(), []),
                                remotes.get(commit.id.hex(), []),
                                tags.get(commit.id.hex(), [])),
                "show commit", use_color(settings)))
            if getattr(args, "no_patch", False):
                continue
            base = _diff_base(repo, settings, commit)
            _print_diff(args, ws, settings, base, commit, None)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def _detailed_lines(repo, settings, commit, names, remote_names, tags):
    """jj's `builtin_log_detailed`: the block `show` prints above a diff.

    Every label sits under `show commit`, which is what jj labels the
    whole template. A bookmark line lists the local names first and the
    remote ones after, and a remote name's three parts colour apart.
    """
    lines = [
        [("Commit ID: ", ""), (commit.id.hex(), "commit_id")],
        [("Change ID: ", ""),
         (commit.change_id.reverse_hex(), "change_id")],
    ]
    if names or remote_names:
        refs = [[(name, "local_bookmarks name")] for name in names]
        refs += [[(name, "remote_bookmarks name"),
                  ("@", "remote_bookmarks"),
                  (remote, "remote_bookmarks remote")]
                 for name, remote in remote_names]
        lines.append([("Bookmarks: ", "")] + separate(refs))
    if tags:
        lines.append([("Tags     : ", "")]
                     + separate([[(tag, "tags name")] for tag in tags]))
    lines.append([("Author   : ", "")]
                 + _signature_spans(commit.author, "author"))
    lines.append([("Committer: ", "")]
                 + _signature_spans(commit.committer, "committer"))
    lines.append([])

    description = commit.description.rstrip()
    if description:
        body = [(text, "description trim_end")
                for text in _indent(description).split("\n")]
    else:
        empty = commit.is_empty(repo) if commit.parent_ids else True
        body = [("    (no description set)",
                 "empty description placeholder" if empty
                 else "description placeholder")]
    lines += [[span] for span in body]
    lines.append([])
    return lines
