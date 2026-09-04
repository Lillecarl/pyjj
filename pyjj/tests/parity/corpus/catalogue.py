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

# The operation log carries three things no two repositories share: an
# operation id minted per repository, a path, and times whose whole job
# is to move. Every `op log` entry normalizes the same set.
_OP = dict(normalize=("op_ids", "ago", "root", "host", "prog"))

# A remote's path lies outside the repository, so `root` does not cover
# it: the remote listing prints it, and so does a fetch.
_R = dict(fixture="remote", normalize=("remote",))

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
      claims=("diff", "--name-only"), colour="bytes"),
    # `-r @` on a merge shows nothing: the merge commit changes nothing
    # against its parents. Diffing across one parent is what surfaces
    # the conflict jj reports.
    E("diff-conflict", ("diff", "--from", 'description(glob:"one*")', "--to", "@"),
      fixture="conflict", claims=("diff",)),
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
    # The entry above cannot hold the drawing: its rows diverge on
    # purpose, so nothing compares them. A shared builtin name is a
    # template string both engines resolve, which makes the rows agree
    # and leaves the graph as the only thing that can differ.
    E("evolog-graph",
      ("evolog", "-r", "@-", "-T", "builtin_evolog_compact"),
      fixture="squashed",
      normalize=("op_ids",), claims=("evolog", "-r", "-T")),

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
    E("file-list", ("file", "list"), claims=("file list",), colour="bytes"),
    E("file-show", ("file", "show", "one.txt"), claims=("file show",), colour="bytes"),
    E("file-annotate", ("file", "annotate", "one.txt"), claims=("file annotate",)),

    # -- refs -----------------------------------------------------------
    E("bookmark-list", ("bookmark", "list"), claims=("bookmark list",), colour="bytes"),
    E("bookmark-list-all-remotes", ("bookmark", "list", "--all-remotes"),
      claims=("bookmark list", "--all-remotes", "-a"), colour="bytes"),
    E("bookmark-list-a", ("bookmark", "list", "-a"),
      claims=("bookmark list", "-a"), colour="bytes"),
    # On `chain` these print what their absence prints: with no remote,
    # `--all-remotes` and `--tracked` change nothing. The entries above
    # keep the no-remote case; these hold the flags to their job.
    E("bookmark-list-remote", ("bookmark", "list"), colour="bytes", **_R),
    E("bookmark-list-all-remotes-fetched",
      ("bookmark", "list", "--all-remotes"),
      claims=("bookmark list", "--all-remotes", "-a"), colour="bytes", **_R),
    E("bookmark-list-tracked", ("bookmark", "list", "--tracked"),
      claims=("bookmark list", "--tracked", "-t"), colour="bytes", **_R),
    E("bookmark-list-one-remote",
      ("bookmark", "list", "--remote", "origin"),
      claims=("bookmark list", "--remote"), colour="bytes", **_R),
    E("git-remotes", ("git", "remote", "list"),
      claims=("git remote list",), colour="bytes", **_R),

    E("tag-list", ("tag", "list"), fixture="tags", claims=("tag list",), colour="bytes"),
    E("workspace-list", ("workspace", "list"), claims=("workspace list",)),

    # -- paths ----------------------------------------------------------
    E("root", ("root",), normalize=("root",), claims=("root",), colour="bytes"),
    E("workspace-root", ("workspace", "root"), normalize=("root",),
      claims=("workspace root",), colour="bytes"),
    E("git-root", ("git", "root"), normalize=("root",), claims=("git root",), colour="bytes"),

    # -- operations -----------------------------------------------------
    E("op-log", ("op", "log"), claims=("operation log",), colour="bytes", **_OP),
    E("op-log-no-graph", ("op", "log", "--no-graph"),
      claims=("operation log", "--no-graph", "-G"), colour="bytes", **_OP),
    E("op-log-reversed", ("op", "log", "--reversed"),
      claims=("operation log", "--reversed"), colour="bytes", **_OP),
    E("op-log-limit", ("op", "log", "-n", "3"),
      claims=("operation log", "--limit", "-n"), colour="bytes", **_OP),
    # `--limit` applies before `--reversed`, so this shows the three
    # newest operations oldest first, not the three oldest.
    E("op-log-reversed-limit", ("op", "log", "--reversed", "-n", "3"),
      colour="bytes", **_OP),
    # A builtin template name means the same thing on both sides, so
    # this argv is shared even though the template languages differ.
    E("op-log-oneline", ("op", "log", "-T", "builtin_op_log_oneline"),
      claims=("operation log", "--template", "-T"), colour="bytes", **_OP),
    E("op-diff", ("op", "diff"), claims=("operation diff",), colour="bytes",
      normalize=("op_ids", "ago", "root", "host", "prog")),
    E("op-diff-no-graph", ("op", "diff", "--no-graph"),
      claims=("operation diff", "--no-graph", "-G"), colour="bytes",
      normalize=("op_ids", "ago", "root", "host", "prog")),
    # One changed commit is one node with no edges, which pins nothing
    # about the drawing. This operation rewrites a whole stack.
    E("op-diff-stack", ("op", "diff"), fixture="rewritten_stack", colour="bytes",
      normalize=("op_ids", "ago", "root", "host", "prog")),
    E("op-diff-stack-no-graph", ("op", "diff", "--no-graph"),
      fixture="rewritten_stack", colour="bytes",
      normalize=("op_ids", "ago", "root", "host", "prog")),
    E("op-show", ("op", "show"), claims=("operation show",), colour="bytes",
      normalize=("op_ids", "ago", "root", "host", "prog")),
    E("op-show-no-graph", ("op", "show", "--no-graph"),
      claims=("operation show", "--no-graph", "-G"), colour="bytes",
      normalize=("op_ids", "ago", "root", "host", "prog")),
    E("op-show-oneline",
      ("op", "show", "--no-op-diff", "-T", "builtin_op_log_oneline"),
      claims=("operation show", "--template", "-T"), colour="bytes",
      normalize=("op_ids", "ago", "root", "host", "prog")),
    E("op-show-no-op-diff", ("op", "show", "--no-op-diff"), colour="bytes",
      claims=("operation show", "--no-op-diff"),
      normalize=("op_ids", "ago", "root", "host", "prog")),

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
