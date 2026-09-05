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

# `log`'s own rows diverge from jj's on purpose, so every entry that
# wants to read what sits *under* a row asks for a builtin template
# both sides resolve the same way.
_COMPACT = "builtin_log_compact"

# `evolog`'s rows diverge the same way, and every row names the
# operation that made the version, whose id is repo-local.
_EVO = "builtin_evolog_compact"
_E = dict(fixture="evolution", normalize=("op_ids",), colour="bytes")

CATALOGUE: tuple[Entry, ...] = (
    # -- status ---------------------------------------------------------
    E("status", ("status",), claims=("status",), colour="bytes"),
    E("status-clean", ("status",), fixture="executable", claims=("status",), colour="bytes"),
    E("status-conflict", ("status",), fixture="conflict", claims=("status",), colour="bytes"),

    # -- diff -----------------------------------------------------------
    E("diff", ("diff", "-r", "@"), fixture="executable", claims=("diff",),
      colour="bytes"),
    E("diff-git", ("diff", "--git", "-r", "@"), fixture="executable",
      claims=("diff", "--git"), colour="bytes"),
    E("diff-summary", ("diff", "--summary", "-r", "@"), fixture="executable",
      claims=("diff", "--summary", "-s"), colour="bytes"),
    E("diff-stat", ("diff", "--stat", "-r", "@"), fixture="executable",
      claims=("diff", "--stat"), colour="bytes"),
    E("diff-name-only", ("diff", "--name-only", "-r", "@"), fixture="executable",
      claims=("diff", "--name-only"), colour="bytes"),
    # `-r @` on a merge shows nothing: the merge commit changes nothing
    # against its parents. Diffing across one parent is what surfaces
    # the conflict jj reports.
    E("diff-conflict", ("diff", "--from", 'description(glob:"one*")', "--to", "@"),
      fixture="conflict", claims=("diff",), colour="bytes"),
    E("diff-context", ("diff", "--context", "1", "-r", "@"), fixture="executable",
      claims=("diff", "--context"), colour="bytes"),
    E("diff-color-words", ("diff", "--color-words", "-r", "@"),
      fixture="executable", claims=("diff", "--color-words"), colour="bytes"),
    E("diff-types", ("diff", "--types", "-r", "@"), fixture="executable",
      claims=("diff", "--types"), colour="bytes"),
    # `-w` and `-b` answer which lines changed, not how they print, so
    # a fixture whose lines differ only in whitespace is what tells
    # them apart -- from each other and from a plain diff.
    E("diff-whitespace", ("diff", "-r", "@"), fixture="whitespace",
      claims=("diff",), colour="bytes"),
    E("diff-ignore-all-space", ("diff", "-w", "-r", "@"), fixture="whitespace",
      claims=("diff", "--ignore-all-space", "-w"), colour="bytes"),
    E("diff-ignore-space-change", ("diff", "-b", "-r", "@"),
      fixture="whitespace",
      claims=("diff", "--ignore-space-change", "-b"), colour="bytes"),
    E("diff-ignore-all-space-git", ("diff", "-w", "--git", "-r", "@"),
      fixture="whitespace", claims=("diff",), colour="bytes"),
    E("diff-ignore-all-space-stat", ("diff", "-w", "--stat", "-r", "@"),
      fixture="whitespace", claims=("diff",), colour="bytes"),
    # Which revisions to diff, spelled every way jj spells it.
    E("diff-revisions", ("diff", "--revisions", 'description(glob:"one*")'),
      claims=("diff", "--revisions", "-r"), colour="bytes"),
    E("diff-from-to", ("diff", "--from", 'description(glob:"one*")',
                       "--to", 'description(glob:"two*")'),
      claims=("diff", "--from", "--to"), colour="bytes"),
    E("diff-f-t", ("diff", "-f", 'description(glob:"one*")',
                   "-t", 'description(glob:"two*")'),
      claims=("diff", "-f", "-t"), colour="bytes"),
    # `--types` says what a path *is*, so a conflict is the case that
    # tells it apart from `--summary`.
    E("diff-types-conflict", ("diff", "--types",
                              "--from", 'description(glob:"one*")', "--to", "@"),
      fixture="conflict", claims=("diff",), colour="bytes"),
    # jj sorts the format flags into a listing and a content format and
    # prints one of each, so this asks for two formats and gets two.
    E("diff-stat-color-words", ("diff", "--stat", "--color-words", "-r", "@"),
      fixture="executable", claims=("diff",), colour="bytes"),

    # -- show -----------------------------------------------------------
    E("show", ("show", 'description(glob:"one*")'), claims=("show",),
      colour="bytes"),
    E("show-no-patch", ("show", "--no-patch", 'description(glob:"one*")'),
      claims=("show", "--no-patch"), colour="bytes"),
    E("show-git", ("show", "--git", 'description(glob:"one*")'),
      claims=("show", "--git"), colour="bytes"),
    E("show-summary", ("show", "--summary", 'description(glob:"one*")'),
      claims=("show", "--summary", "-s"), colour="bytes"),
    E("show-stat", ("show", "--stat", 'description(glob:"one*")'),
      claims=("show", "--stat"), colour="bytes"),
    E("show-color-words", ("show", "--color-words", 'description(glob:"one*")'),
      claims=("show", "--color-words"), colour="bytes"),
    E("show-types", ("show", "--types", 'description(glob:"one*")'),
      claims=("show", "--types"), colour="bytes"),
    E("show-revision", ("show", "-r", 'description(glob:"one*")'),
      claims=("show", "-r"), colour="bytes"),
    E("show-name-only", ("show", "--name-only", 'description(glob:"one*")'),
      claims=("show", "--name-only"), colour="bytes"),
    E("show-context", ("show", "--context", "1",
                       'description(glob:"every shape*")'),
      fixture="executable", claims=("show", "--context"), colour="bytes"),
    E("show-ignore-all-space", ("show", "-w", 'description(glob:"whitespace*")'),
      fixture="whitespace",
      claims=("show", "--ignore-all-space", "-w"), colour="bytes"),
    # jj reverses the revisions, not the blocks: each one still carries
    # its own diff, and only the order of the two changes.
    E("show-reversed", ("show", "-r", "all()", "--reversed"),
      claims=("show", "--reversed"), colour="bytes"),
    E("show-ignore-space-change",
      ("show", "-b", 'description(glob:"whitespace*")'), fixture="whitespace",
      claims=("show", "--ignore-space-change", "-b"), colour="bytes"),

    # -- log ------------------------------------------------------------
    E("log", ("log",), bar="facts",
      reason="pyjj-cli prints the author's name and a century-less "
             "timestamp on request; test_parity.py checks the facts",
      claims=("log",)),
    E("log-no-graph", ("log", "--no-graph"), bar="facts",
      reason="same divergence as `log`", claims=("log", "--no-graph")),
    E("log-reversed", ("log", "--reversed"), bar="facts",
      reason="same divergence as `log`", claims=("log", "--reversed")),
    # A builtin template name means the same thing on both sides, so
    # this is where `log`'s rows get compared at all. The three entries
    # above are `facts`, and a `facts` entry hides everything about its
    # output -- including the colours.
    E("log-compact", ("log", "-T", "builtin_log_compact"),
      claims=("log", "--template", "-T"), colour="bytes"),
    # Every diff flag below rides on that same builtin name, for the
    # same reason: the rows have to agree before the diff under them
    # can be read. jj lays the diff beside the graph column, so these
    # entries pin the drawing as much as the diff.
    E("log-patch", ("log", "-T", _COMPACT, "-p"),
      claims=("log", "--patch", "-p"), colour="bytes"),
    E("log-git", ("log", "-T", _COMPACT, "--git"),
      claims=("log", "--git"), colour="bytes"),
    E("log-color-words", ("log", "-T", _COMPACT, "--color-words"),
      claims=("log", "--color-words"), colour="bytes"),
    E("log-summary", ("log", "-T", _COMPACT, "-s"),
      claims=("log", "--summary", "-s"), colour="bytes"),
    E("log-stat", ("log", "-T", _COMPACT, "--stat"),
      claims=("log", "--stat"), colour="bytes"),
    E("log-name-only", ("log", "-T", _COMPACT, "--name-only"),
      claims=("log", "--name-only"), colour="bytes"),
    E("log-types", ("log", "-T", _COMPACT, "--types"),
      fixture="executable", claims=("log", "--types"), colour="bytes"),
    # A short format and a long one together: the listing comes first,
    # and the root commit lists nothing at all.
    E("log-summary-git", ("log", "-T", _COMPACT, "-s", "--git"),
      colour="bytes"),
    E("log-context", ("log", "-T", _COMPACT, "-p", "--context", "1"),
      fixture="executable", claims=("log", "--context"), colour="bytes"),
    E("log-ignore-all-space",
      ("log", "-T", _COMPACT, "-p", "--ignore-all-space"),
      fixture="whitespace", claims=("log", "--ignore-all-space"),
      colour="bytes"),
    E("log-ignore-space-change",
      ("log", "-T", _COMPACT, "-p", "--ignore-space-change"),
      fixture="whitespace", claims=("log", "--ignore-space-change"),
      colour="bytes"),
    # `--no-graph` drops the column the diff was laid beside, so the
    # diff has to stand on its own.
    E("log-patch-no-graph", ("log", "-T", _COMPACT, "--no-graph", "-p"),
      claims=("log", "--no-graph", "-G"), colour="bytes"),
    E("log-patch-limit", ("log", "-T", _COMPACT, "-n", "2", "-p"),
      claims=("log", "--limit", "-n"), colour="bytes"),
    E("log-patch-revision", ("log", "-T", _COMPACT, "-r", "@-", "-p"),
      claims=("log", "-r"), colour="bytes"),
    # A path narrows the revset rather than the rows, so the graph
    # elides the commits it leaves out instead of dropping them.
    E("log-fileset", ("log", "-T", _COMPACT, "two.txt"), colour="bytes"),
    E("log-fileset-patch", ("log", "-T", _COMPACT, "-p", "one.txt", "two.txt"),
      colour="bytes"),
    # `--count` prints no rows, so it needs no template to agree.
    E("log-count", ("log", "--count"), claims=("log", "--count"),
      colour="bytes"),
    E("log-count-limit", ("log", "--count", "-n", "2"), colour="bytes"),

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
      normalize=("op_ids",), colour="bytes",
      claims=("evolog", "-r", "-T")),
    # `evolog --patch` is an interdiff, not a parent diff: it compares
    # a version with the one it was rewritten from, rebased onto this
    # version's parents. jj compares the descriptions too, which is why
    # a `describe` step shows a diff at all.
    E("evolog-patch", ("evolog", "-T", _EVO, "-p"),
      claims=("evolog", "--patch", "-p"), **_E),
    E("evolog-git", ("evolog", "-T", _EVO, "--git"),
      claims=("evolog", "--git"), **_E),
    E("evolog-color-words", ("evolog", "-T", _EVO, "--color-words"),
      claims=("evolog", "--color-words"), **_E),
    E("evolog-summary", ("evolog", "-T", _EVO, "-s"),
      claims=("evolog", "--summary", "-s"), **_E),
    E("evolog-stat", ("evolog", "-T", _EVO, "--stat"),
      claims=("evolog", "--stat"), **_E),
    E("evolog-name-only", ("evolog", "-T", _EVO, "--name-only"),
      claims=("evolog", "--name-only"), **_E),
    E("evolog-types", ("evolog", "-T", _EVO, "--types"),
      claims=("evolog", "--types"), **_E),
    E("evolog-context", ("evolog", "-T", _EVO, "-p", "--context", "1"),
      claims=("evolog", "--context"), **_E),
    E("evolog-patch-no-graph", ("evolog", "-T", _EVO, "-p", "--no-graph"),
      claims=("evolog", "--no-graph", "-G"), **_E),
    E("evolog-patch-limit", ("evolog", "-T", _EVO, "-p", "-n", "2"),
      claims=("evolog", "--limit", "-n"), **_E),
    E("evolog-reversed", ("evolog", "-T", _EVO, "--reversed"),
      claims=("evolog", "--reversed"), **_E),
    E("evolog-revisions",
      ("evolog", "-T", _EVO, "--revisions", "@-", "-p"),
      fixture="squashed", normalize=("op_ids",), colour="bytes",
      claims=("evolog", "--revisions")),
    # A squash gives a version two predecessors, and jj merges their
    # descriptions the way it merges their trees. That merge does not
    # resolve, so the description the diff starts from is the conflict,
    # markers and all.
    E("evolog-patch-squash", ("evolog", "-T", _EVO, "-r", "@-", "-p"),
      fixture="squashed", normalize=("op_ids",), colour="bytes"),
    # A snapshot whose only change is whitespace: `-w` and `-b` decide
    # which of its lines count as the same.
    E("evolog-ignore-all-space",
      ("evolog", "-T", _EVO, "-p", "--ignore-all-space"),
      fixture="whitespace", normalize=("op_ids",), colour="bytes",
      claims=("evolog", "--ignore-all-space")),
    E("evolog-ignore-space-change",
      ("evolog", "-T", _EVO, "-p", "--ignore-space-change"),
      fixture="whitespace", normalize=("op_ids",), colour="bytes",
      claims=("evolog", "--ignore-space-change")),

    # -- interdiff ------------------------------------------------------
    E("interdiff", ("interdiff", "--from", 'description(glob:"one*")',
                    "--to", 'description(glob:"two*")'),
      claims=("interdiff", "--from", "--to"), colour="bytes"),
    E("interdiff-git", ("interdiff", "--git", "--from", 'description(glob:"one*")',
                        "--to", 'description(glob:"two*")'),
      claims=("interdiff", "--git"), colour="bytes"),
    E("interdiff-summary", ("interdiff", "--summary",
                            "--from", 'description(glob:"one*")',
                            "--to", 'description(glob:"two*")'),
      claims=("interdiff", "--summary"), colour="bytes"),
    E("interdiff-color-words", ("interdiff", "--color-words",
                                "--from", 'description(glob:"one*")',
                                "--to", 'description(glob:"two*")'),
      claims=("interdiff", "--color-words"), colour="bytes"),
    E("interdiff-types", ("interdiff", "--types",
                          "--from", 'description(glob:"one*")',
                          "--to", 'description(glob:"two*")'),
      claims=("interdiff", "--types"), colour="bytes"),
    E("interdiff-f-t", ("interdiff", "-f", 'description(glob:"one*")',
                        "-t", 'description(glob:"two*")'),
      claims=("interdiff", "-f", "-t"), colour="bytes"),
    E("interdiff-stat", ("interdiff", "--stat",
                         "--from", 'description(glob:"one*")',
                         "--to", 'description(glob:"two*")'),
      claims=("interdiff", "--stat", "-s"), colour="bytes"),
    E("interdiff-name-only", ("interdiff", "--name-only",
                              "--from", 'description(glob:"one*")',
                              "--to", 'description(glob:"two*")'),
      claims=("interdiff", "--name-only"), colour="bytes"),
    E("interdiff-context", ("interdiff", "--context", "1",
                            "--from", 'description(glob:"base*")',
                            "--to", 'description(glob:"whitespace*")'),
      fixture="whitespace", claims=("interdiff", "--context"), colour="bytes"),
    E("interdiff-ignore-all-space",
      ("interdiff", "-w", "--from", 'description(glob:"base*")',
       "--to", 'description(glob:"whitespace*")'),
      fixture="whitespace",
      claims=("interdiff", "--ignore-all-space", "-w"), colour="bytes"),
    E("interdiff-ignore-space-change",
      ("interdiff", "-b", "--from", 'description(glob:"base*")',
       "--to", 'description(glob:"whitespace*")'),
      fixture="whitespace",
      claims=("interdiff", "--ignore-space-change", "-b"), colour="bytes"),

    # -- file -----------------------------------------------------------
    E("file-list", ("file", "list"), claims=("file list",), colour="bytes"),
    E("file-show", ("file", "show", "one.txt"), claims=("file show",), colour="bytes"),
    E("file-annotate", ("file", "annotate", "one.txt"), claims=("file annotate",), colour="bytes"),

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
    E("workspace-list", ("workspace", "list"), claims=("workspace list",), colour="bytes"),

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
    # `op log --op-diff` puts a whole operation diff under each row, and
    # the graph column runs down beside it -- one graph nested in
    # another. `--patch` asks for it too, and adds each commit's diff.
    E("op-log-op-diff", ("op", "log", "-d", "-n", "3"),
      fixture="rewritten_stack",
      claims=("operation log", "--op-diff", "-d"), colour="bytes", **_OP),
    E("op-log-patch", ("op", "log", "-p", "-n", "3"),
      fixture="rewritten_stack",
      claims=("operation log", "--patch", "-p"), colour="bytes", **_OP),
    E("op-log-git", ("op", "log", "--git", "-n", "3"),
      fixture="rewritten_stack",
      claims=("operation log", "--git"), colour="bytes", **_OP),
    E("op-log-color-words", ("op", "log", "--color-words", "-n", "3"),
      fixture="rewritten_stack",
      claims=("operation log", "--color-words"), colour="bytes", **_OP),
    E("op-log-summary", ("op", "log", "-s", "-n", "3"),
      fixture="rewritten_stack",
      claims=("operation log", "--summary", "-s"), colour="bytes", **_OP),
    E("op-log-stat", ("op", "log", "--stat", "-n", "3"),
      fixture="rewritten_stack",
      claims=("operation log", "--stat"), colour="bytes", **_OP),
    E("op-log-name-only", ("op", "log", "--name-only", "-n", "3"),
      fixture="rewritten_stack",
      claims=("operation log", "--name-only"), colour="bytes", **_OP),
    E("op-log-types", ("op", "log", "--types", "-n", "3"),
      fixture="rewritten_stack",
      claims=("operation log", "--types"), colour="bytes", **_OP),
    E("op-log-context", ("op", "log", "-p", "--context", "1", "-n", "3"),
      fixture="whitespace",
      claims=("operation log", "--context"), colour="bytes", **_OP),
    E("op-log-ignore-all-space",
      ("op", "log", "-p", "--ignore-all-space", "-n", "3"),
      fixture="whitespace",
      claims=("operation log", "--ignore-all-space"), colour="bytes", **_OP),
    E("op-log-ignore-space-change",
      ("op", "log", "-p", "--ignore-space-change", "-n", "3"),
      fixture="whitespace",
      claims=("operation log", "--ignore-space-change"), colour="bytes",
      **_OP),
    E("op-log-show-changes-in",
      ("op", "log", "-d", "-n", "3", "--show-changes-in",
       'description(glob:"one*")'),
      fixture="rewritten_stack",
      claims=("operation log", "--show-changes-in"), colour="bytes", **_OP),
    E("op-log-op-diff-no-graph", ("op", "log", "-d", "-n", "3", "--no-graph"),
      fixture="rewritten_stack", colour="bytes", **_OP),
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
    # `--from`/`--to` name two operations to compare; `--op` names one
    # and compares it with its parent. A trailing `-` walks the
    # operation log back a step, which is how a name reaches an
    # operation that is not the newest.
    E("op-diff-from-to", ("op", "diff", "--from", "@--", "--to", "@"),
      claims=("operation diff", "--from", "--to"), colour="bytes", **_OP),
    E("op-diff-f-t", ("op", "diff", "-f", "@-", "-t", "@"),
      claims=("operation diff", "-f", "-t"), colour="bytes", **_OP),
    E("op-diff-operation", ("op", "diff", "--operation", "@-"),
      claims=("operation diff", "--operation"), colour="bytes", **_OP),
    E("op-diff-op", ("op", "diff", "--op", "@--"),
      claims=("operation diff", "--op"), colour="bytes", **_OP),
    # `--show-changes-in` narrows the changed commits to a revset. The
    # ones it leaves out are counted as elided rather than dropped.
    E("op-diff-show-changes-in",
      ("op", "diff", "--show-changes-in", 'description(glob:"one*")'),
      fixture="rewritten_stack",
      claims=("operation diff", "--show-changes-in"), colour="bytes", **_OP),
    # `--patch` compares a changed commit with the version it was
    # rewritten from, so a `describe` shows a description diff and a
    # snapshot shows the file. An abandoned change has no new version,
    # so what prints is its own diff against its parent.
    E("op-diff-patch", ("op", "diff", "-p"), fixture="rewritten_stack",
      claims=("operation diff", "--patch", "-p"), colour="bytes", **_OP),
    E("op-diff-git", ("op", "diff", "--git"), fixture="rewritten_stack",
      claims=("operation diff", "--git"), colour="bytes", **_OP),
    E("op-diff-color-words", ("op", "diff", "--color-words"),
      fixture="rewritten_stack",
      claims=("operation diff", "--color-words"), colour="bytes", **_OP),
    E("op-diff-summary", ("op", "diff", "-s"), fixture="rewritten_stack",
      claims=("operation diff", "--summary", "-s"), colour="bytes", **_OP),
    E("op-diff-stat", ("op", "diff", "--stat"), fixture="rewritten_stack",
      claims=("operation diff", "--stat"), colour="bytes", **_OP),
    E("op-diff-name-only", ("op", "diff", "--name-only"),
      fixture="rewritten_stack",
      claims=("operation diff", "--name-only"), colour="bytes", **_OP),
    E("op-diff-types", ("op", "diff", "--types"), fixture="rewritten_stack",
      claims=("operation diff", "--types"), colour="bytes", **_OP),
    E("op-diff-context", ("op", "diff", "-p", "--context", "1"),
      fixture="whitespace",
      claims=("operation diff", "--context"), colour="bytes", **_OP),
    E("op-diff-patch-no-graph", ("op", "diff", "-p", "--no-graph"),
      fixture="rewritten_stack", colour="bytes", **_OP),
    E("op-diff-ignore-all-space",
      ("op", "diff", "--op", "@-", "-p", "--ignore-all-space"),
      fixture="whitespace",
      claims=("operation diff", "--ignore-all-space"), colour="bytes", **_OP),
    E("op-diff-ignore-space-change",
      ("op", "diff", "--op", "@-", "-p", "--ignore-space-change"),
      fixture="whitespace",
      claims=("operation diff", "--ignore-space-change"), colour="bytes",
      **_OP),
    E("op-show", ("op", "show"), claims=("operation show",), colour="bytes",
      normalize=("op_ids", "ago", "root", "host", "prog")),
    E("op-show-patch", ("op", "show", "-p"), fixture="rewritten_stack",
      claims=("operation show", "--patch", "-p"), colour="bytes", **_OP),
    E("op-show-git", ("op", "show", "--git"), fixture="rewritten_stack",
      claims=("operation show", "--git"), colour="bytes", **_OP),
    E("op-show-color-words", ("op", "show", "--color-words"),
      fixture="rewritten_stack",
      claims=("operation show", "--color-words"), colour="bytes", **_OP),
    E("op-show-summary", ("op", "show", "-s"), fixture="rewritten_stack",
      claims=("operation show", "--summary", "-s"), colour="bytes", **_OP),
    E("op-show-stat", ("op", "show", "--stat"), fixture="rewritten_stack",
      claims=("operation show", "--stat"), colour="bytes", **_OP),
    E("op-show-name-only", ("op", "show", "--name-only"),
      fixture="rewritten_stack",
      claims=("operation show", "--name-only"), colour="bytes", **_OP),
    E("op-show-types", ("op", "show", "--types"), fixture="rewritten_stack",
      claims=("operation show", "--types"), colour="bytes", **_OP),
    E("op-show-context", ("op", "show", "@-", "-p", "--context", "1"),
      fixture="whitespace",
      claims=("operation show", "--context"), colour="bytes", **_OP),
    E("op-show-ignore-all-space",
      ("op", "show", "@-", "-p", "--ignore-all-space"), fixture="whitespace",
      claims=("operation show", "--ignore-all-space"), colour="bytes", **_OP),
    E("op-show-ignore-space-change",
      ("op", "show", "@-", "-p", "--ignore-space-change"),
      fixture="whitespace",
      claims=("operation show", "--ignore-space-change"), colour="bytes",
      **_OP),
    E("op-show-revision", ("op", "show", "@-"), colour="bytes", **_OP),
    E("op-show-show-changes-in",
      ("op", "show", "--show-changes-in", 'description(glob:"one*")'),
      fixture="rewritten_stack",
      claims=("operation show", "--show-changes-in"), colour="bytes", **_OP),
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
