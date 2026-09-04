"""Which invocations the corpus records, and the bar each is held to.

This file is the weighted judgement, written down. Adding a read-only
flag means adding an entry here; `test_corpus.py` fails if an unclaimed
read-only item has neither an entry nor a reasoned skip, so the
judgement cannot be made by omission.

See the package docstring for what the bars mean.
"""

from __future__ import annotations

from . import Entry

E = Entry

CATALOGUE: tuple[Entry, ...] = (
    # -- status ---------------------------------------------------------
    E("status", ("status",), claims=("status",)),
    E("status-clean", ("status",), fixture="executable", claims=("status",)),
    E("status-conflict", ("status",), fixture="conflict", claims=("status",)),

    # -- diff -----------------------------------------------------------
    E("diff", ("diff", "-r", "@"), fixture="executable", claims=("diff",)),
    E("diff-git", ("diff", "--git", "-r", "@"), fixture="executable",
      claims=("diff", "--git")),
    E("diff-summary", ("diff", "--summary", "-r", "@"), fixture="executable",
      claims=("diff", "--summary", "-s")),
    E("diff-stat", ("diff", "--stat", "-r", "@"), fixture="executable",
      claims=("diff", "--stat")),
    E("diff-name-only", ("diff", "--name-only", "-r", "@"), fixture="executable",
      claims=("diff", "--name-only")),
    # `-r @` on a merge shows nothing: the merge commit changes nothing
    # against its parents. Diffing across one parent is what surfaces
    # the conflict jj reports.
    E("diff-conflict", ("diff", "--from", 'description(glob:"one*")', "--to", "@"),
      fixture="conflict", bar="todo",
      reason="a conflicted path reads as a regular file: git_diff() has "
             "already materialized the markers, so jj's `Created conflict "
             "in` heading cannot be reconstructed",
      claims=("diff",)),
    E("diff-context", ("diff", "--context", "1", "-r", "@"), fixture="executable",
      claims=("diff", "--context")),

    # -- show -----------------------------------------------------------
    E("show", ("show", 'description(glob:"one*")'), claims=("show",)),
    E("show-no-patch", ("show", "--no-patch", 'description(glob:"one*")'),
      claims=("show", "--no-patch")),
    E("show-git", ("show", "--git", 'description(glob:"one*")'),
      claims=("show", "--git")),
    E("show-summary", ("show", "--summary", 'description(glob:"one*")'),
      claims=("show", "--summary", "-s")),
    E("show-stat", ("show", "--stat", 'description(glob:"one*")'),
      claims=("show", "--stat")),

    # -- log ------------------------------------------------------------
    E("log", ("log",), bar="facts",
      reason="pyjj-cli prints the author's name and a century-less "
             "timestamp on request; test_parity.py checks the facts",
      claims=("log",)),
    E("log-no-graph", ("log", "--no-graph"), bar="facts",
      reason="same divergence as `log`", claims=("log", "--no-graph")),
    E("log-reversed", ("log", "--reversed"), bar="facts",
      reason="same divergence as `log`", claims=("log", "--reversed")),

    # -- evolog ---------------------------------------------------------
    E("evolog", ("evolog",), fixture="evolution", bar="facts",
      reason="rows share `log`'s divergence, and every row names an "
             "operation, whose id is repo-local",
      normalize=("op_ids",), claims=("evolog",)),

    # -- interdiff ------------------------------------------------------
    E("interdiff", ("interdiff", "--from", 'description(glob:"one*")',
                    "--to", 'description(glob:"two*")'),
      claims=("interdiff",)),
    E("interdiff-git", ("interdiff", "--git", "--from", 'description(glob:"one*")',
                        "--to", 'description(glob:"two*")'),
      claims=("interdiff", "--git")),
    E("interdiff-summary", ("interdiff", "--summary",
                            "--from", 'description(glob:"one*")',
                            "--to", 'description(glob:"two*")'),
      claims=("interdiff", "--summary")),

    # -- file -----------------------------------------------------------
    E("file-list", ("file", "list"), claims=("file list",)),
    E("file-show", ("file", "show", "one.txt"), claims=("file show",)),
    E("file-annotate", ("file", "annotate", "one.txt"), claims=("file annotate",)),

    # -- refs -----------------------------------------------------------
    E("bookmark-list", ("bookmark", "list"), claims=("bookmark list",)),
    E("bookmark-list-all-remotes", ("bookmark", "list", "--all-remotes"),
      claims=("bookmark list", "--all-remotes", "-a")),
    E("bookmark-list-a", ("bookmark", "list", "-a"),
      claims=("bookmark list", "-a")),
    E("tag-list", ("tag", "list"), fixture="tags", claims=("tag list",)),
    E("workspace-list", ("workspace", "list"), claims=("workspace list",)),

    # -- paths ----------------------------------------------------------
    E("root", ("root",), normalize=("root",), claims=("root",)),
    E("workspace-root", ("workspace", "root"), normalize=("root",),
      claims=("workspace root",)),
    E("git-root", ("git", "root"), normalize=("root",), claims=("git root",)),

    # -- operations -----------------------------------------------------
    E("op-log", ("op", "log"), bar="todo",
      reason="pyjj-cli prints its own format for the operation log",
      normalize=("op_ids", "ago", "root", "host"), claims=("operation log",)),

    # -- each tool's own identity ---------------------------------------
    E("version", ("version",), bar="skip",
      reason="each tool reports its own version; agreeing would be the bug",
      claims=("version",)),
    E("help", ("help",), bar="skip",
      reason="argparse and clap render help differently by construction, "
             "and the text is each tool's own",
      claims=("help",)),
    E("util-markdown-help", ("util", "markdown-help"), bar="skip",
      reason="jj's is the authoritative surface the ledgers read; pyjj-cli "
             "reproducing it would make the measurement circular",
      claims=("util markdown-help",)),
)


BY_ID = {entry.id: entry for entry in CATALOGUE}
assert len(BY_ID) == len(CATALOGUE), "duplicate corpus entry id"
