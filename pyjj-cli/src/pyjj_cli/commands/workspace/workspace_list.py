"""workspace subcommand: workspace_list."""
import os

import pyjj
from ...formatter import render_block
from ..common import (
    _bookmarks_by_commit,
    _commit_context,
    _commit_summary_spans,
    _resolve_template,
    _load,
    use_color,
    command,
)

@command(catch=(pyjj.WorkspaceLoadError, pyjj.RepoLoadError,))
def workspace_list(args) -> int:
    settings, ws, repo = _load(args)
    view = repo.view()
    bookmarks = _bookmarks_by_commit(repo)
    template = _resolve_template(settings, ws, args, "workspace_list")
    for name, commit_id in sorted(view.items()):
        commit = repo.get_commit(pyjj.CommitId(commit_id))
        refs = bookmarks.get(commit_id, [])
        if template is not None:
            context = _commit_context(repo, settings, commit, refs)
            context["name"] = name
            print(template.render(context))
            continue
        # Since jj 0.46 the template labels each row `workspace`,
        # with the name and root beneath it (`workspace name`,
        # `workspace root relative`) -- the debug golden carries the
        # whole stacks.
        under = "workspace target"
        if commit_id == view.get(ws.workspace_name):
            under = "workspace working_copy target"
        # jj prints the workspace's root path, relative to where
        # the command runs, between the name and the summary --
        # `if(root, root.relative())` in the default template. The
        # workspace running the command shows `.`.
        spans = [(name, "workspace name"), (": ", "workspace")]
        rel = ws.workspace_path(name)
        if rel is not None:
            # `workspace_path()` is already absolute; show it
            # relative to where the command runs.
            root = os.path.relpath(os.path.normpath(rel), os.getcwd())
            spans += [(root, "workspace root relative"), (" ", "workspace")]
        spans += [(text, f"{under} {labels}".strip()) for text, labels
                  in _commit_summary_spans(repo, settings, commit, refs)]
        print(render_block([spans], "workspace_list",
                           use_color(settings)))
    return 0
