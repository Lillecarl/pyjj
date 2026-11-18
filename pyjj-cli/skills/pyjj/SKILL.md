---
name: pyjj
description: Version control in jj (Jujutsu) and colocated jj/git repositories through the pyjj CLI — the working-copy model, committing and splitting, moving changes between commits, rebasing and merging, revsets and filesets, bookmarks and remotes, workspaces, conflicts, undo; plus pyjj's Python session API, DOT-graph reshapes, and the octopus workflow for forks kept as topic branches under one merge. Load before any VCS command in such a repository. Never rewrites history unless explicitly asked.
---

# pyjj

`pyjj` is the jj CLI on top of `jj_lib`: same arguments (`-r`, `-d`, `-A`/`-B`,
revsets), so jj documentation applies with `jj` replaced by `pyjj`. `-R <path>`
when the repo is elsewhere. Differences:

- `-T` takes Jinja2, not jj's template language: `{{ change_id_short }}
  {{ subject }}`. `{{ description }}` is the whole message, `{{ subject }}` its
  first line. A jj-language template prints as literal text, with no error.
- Extras jj lacks: `--dry-run`/`--abort-on-conflict` on rewrites, a
  fast-forward-only trunk, `pyjj hunk`, `pyjj graph`, `pyjj python`, `--dot`.
- Successful rewrites print nothing (jj prints a summary and new conflicts).
  Check the result with `pyjj log` or `pyjj log -r 'conflicts()'`.

`jj` on PATH is a fallback for a command pyjj lacks or gets wrong; each
fallback is a pyjj bug report (Lillecarl/pyjj).

Read a reference when a task touches its topic; do not preload them.

## Model

- `@` is the working-copy commit, in every workspace. A real commit, not a
  staging area: almost every command snapshots edits into it. No `add`, no
  detached HEAD.
- Two ids: **change id** (stable across rewrites; a commit's identity) and
  **commit id** (content hash; changes on every rewrite). `log` shows the
  change id first.
- Bookmarks are branches that move only when moved, or when their commit is
  rewritten (they follow). No "current branch".
- `pyjj commit -m msg` = `describe -m msg` + `new`: `@` gets the message and a
  fresh empty child becomes `@`.
- `pyjj split FILES -m msg` peels FILES out of `@` into a new commit *before*
  `@`; the rest stays in `@`, still open.
- Rewritten and abandoned commits are hidden, not deleted: `pyjj op log` can
  return to any earlier state. Recoverable is not the same as harmless; see
  Safety.

Git habits mapped one by one: [git-mapping.md](references/git-mapping.md).

## Finishing work

1. Edit. Edits land in `@`.
2. Land them:
   - one logical change: `pyjj commit -m ...` (the usual case);
   - several concerns in different files: `pyjj split FILES -m ...`, repeated
     ([splitting.md](references/splitting.md));
   - two concerns in one file: `pyjj hunk` ([hunk.md](references/hunk.md));
   - a fixup for the parent: `pyjj squash --use-destination-message`.
3. End with `@` empty and every finished piece committed with a real message.

Never "finish" with `describe`: it sets the message but leaves `@` in place, so
later edits land in the commit just described. `describe -r @-` renames a
finished parent.

Messages go through a quoted heredoc. It keeps apostrophes, quotes, `$vars` and
backticks verbatim; an inline `-m '...'` breaks on the first apostrophe and the
shell runs the rest.

```bash
pyjj commit -m "$(cat <<'EOF'
subject line

Body. Apostrophes, "quotes", $vars and `backticks` are safe.
EOF
)"
```

`pyjj split FILES -m "$(cat <<'EOF' ...` takes the same shape. Split while the
boundaries are fresh instead of letting `@` collect several concerns.

## Moving a change to the commit it belongs in

```bash
pyjj squash path/to/file --into REV          # whole files: one step; @ keeps the rest
pyjj split shared.txt -m 'the missed tweak'  # finer than a file: peel first...
pyjj squash -r @- --use-destination-message  # ...then fold into its parent
```

- `--use-destination-message` is required when a squash empties a described
  commit: otherwise an editor opens to merge the two messages, and headless
  it fails. A partial move (the first line) never hits this.
- Repeated `pyjj new -m` leaves empty commits between real ones; `-r @-` then
  folds into an empty. Name the target: a change id, `description(...)`.
- Hunk-level into the parent: `pyjj hunk squash SPEC`.

## Which command

| Situation | Command |
|---|---|
| Edits in `@` are one change | `pyjj commit -m ...` |
| Several files, several changes | `pyjj split FILES -m ...` — [splitting.md](references/splitting.md) |
| One file, two concerns | `pyjj hunk split` — [hunk.md](references/hunk.md) |
| Fixup for the parent | `pyjj squash --use-destination-message` |
| Whole files belong in an earlier commit | `pyjj squash FILES --into REV` |
| Fixups to lines earlier commits own | `pyjj absorb` — [advanced-operations.md](references/advanced-operations.md) |
| Part of `@` onto another base, as its own commit | `pyjj split FILES --onto REV -m ...` — [splitting.md](references/splitting.md) |
| A merge of two lines of work | `pyjj new -m msg REV1 REV2` — [rebase-and-merge.md](references/rebase-and-merge.md) |
| Move commits to a new base | `pyjj rebase -s/-b/-r ... -d DEST` — ask first; [rebase-and-merge.md](references/rebase-and-merge.md) |
| Conflicts | [rebase-and-merge.md](references/rebase-and-merge.md) |
| Select commits precisely | revsets — [revsets.md](references/revsets.md); files: [filesets.md](references/filesets.md) |
| A second working directory | `pyjj workspace add` — [workspaces.md](references/workspaces.md) |
| Branches, tracking, push safety | [bookmarks.md](references/bookmarks.md) |
| Clone, fetch, push, divergent changes | [remotes-and-sync.md](references/remotes-and-sync.md) |
| Something went wrong | `pyjj op log`, `pyjj op restore ID` — [safety-and-undo.md](references/safety-and-undo.md) |
| `edit`, `next`/`prev`, `duplicate`, `parallelize`, `metaedit`, `revert`, `run`, tags, sparse, `op` | [advanced-operations.md](references/advanced-operations.md) |
| A fork of topic branches under one octopus merge | [octopus.md](references/octopus.md) |
| Several rewrites as one transaction, DOT reshapes, extensions | [scripting.md](references/scripting.md) |

Revsets beat counting offsets: `pyjj log -r 'trunk()..@'` (local work),
`'conflicts()'`, `'mine() & description(substring:"fix")'`. Without a remote
`trunk()` is `root()`. Details: [revsets.md](references/revsets.md).

## Workspaces are branches; the default workspace follows `main`

- The default workspace (`~/Code/<repo>`) is tied to the `main` bookmark: its
  `@` sits on the latest `main`. User and other configurations build from it.
  Committing there is normal; quick fixes land straight from it.
- A secondary workspace is a checked-out branch for one larger task that must
  not block those fixes. Commit there.
- **Never manipulate another workspace**, from any workspace, `default`
  included:
  - no rewrite of its `@` or of any mutable ancestor of it: `rebase`,
    `squash`, `describe`, `abandon`, `absorb`, `split`, `edit`;
  - no `-R <its path>`, `workspace update-stale` or `workspace forget` on it;
  - no move, set or delete of a bookmark it holds; `main` moves only through
    `pyjj wf land`.

  Only exception: Agent is the sole agent owner of both workspaces, meaning
  this session created or took over both and no other session works in either.
  When ownership is not certain, Agent is not the owner. User asking for that
  exact rewrite also permits it.
- A workspace commits on its own `@` and moves only bookmarks it created for
  its own task, plus `main` through `pyjj wf land`.
- Every workspace lands its own finished work: `pyjj commit`, then
  `pyjj wf land` (rebase onto `main`, move `main` forward, one transaction).
  Never `bookmark set main` by hand. With nothing to land it moves `@` onto
  `main`: how a workspace, `default` included, catches up. Details and
  refusals: [workspaces.md](references/workspaces.md).

## Safety

- **Rewrite only when User asks for that rewrite**: `edit`, `rebase`,
  `absorb`, `duplicate`, `parallelize`, `metaedit`, moving a bookmark to
  another target. Appending is always fine: `commit`, `new`, `split` on `@`,
  `bookmark create`. Exceptions: `squash --use-destination-message` of a
  fixup, and a workflow whose instructions call for the rewrite (octopus).
- jj's immutability guard covers only `trunk()` and what a remote tracks. In a
  repo with no remote `trunk()` is `root()` and nothing is protected; follow
  this policy regardless.
- **Never run a git command that writes** in a jj repo (`commit`, `merge`,
  `rebase`, `reset`, `cherry-pick`, `push`, `tag`, `stash`, `branch -d`, ...).
  It bypasses the operation log. Read-only git (`log`, `diff`, `show`,
  `status`, `blame`) is fine.
- **Checkpoint** before a multi-step sequence:
  `pyjj op log --no-graph --limit 1 -T '{{ id_short }}'`. On trouble,
  `pyjj op restore ID` (short ids work). Never chain `pyjj undo`: undo
  records operations itself, so a second undo can undo the first.
- **Trial a rewrite** first: `--dry-run` writes nothing and lists commits that
  would newly conflict; `--abort-on-conflict` writes only if nothing new
  conflicts (exit 1 otherwise). On `rebase`, `squash`, `split`, `absorb`,
  `abandon`, `duplicate`, `restore`, `revert`, `new`, `simplify-parents`,
  `fix`, `hunk`, `graph apply`; not on `parallelize`.
- **Published trunk is fast-forward-only**: `main`/`master`/`trunk` with a
  real remote only moves forward (`pyjj.fast-forward-bookmarks`); anything
  else is refused, nothing written, unless the global `--allow-nonff`.
- **Verify** with `pyjj status`/`pyjj log`, never by exit code alone. One
  clear wrong step: `pyjj undo` once and retry. Anything murkier: stop, tell
  User what you see, name the `op restore` id to return to.

Full detail: [safety-and-undo.md](references/safety-and-undo.md).

## Output

Pass `--no-pager`. For `diff`, `show`, `log -p` and `interdiff` pass `--git`:
the default colour-words format is not reliably parseable. `diff`/`show` of a
merge currently compare against its first parent only (a pyjj bug); `pyjj log
-r REV` says `(empty)` correctly.

## Gotchas

- `rebase -r C -A P` moves `C` onto `P` and re-points `P`'s children, a merge
  among them, onto `C`, keeping their other parents. One command.
- `restore -c REV` rewrites REV in place; `revert -r REV` appends a commit
  undoing it.
- `-r X -A trunk() -B MERGE` slides X under every parent of MERGE, not beside
  them. Adding a parent to a merge: `pyjj rebase -r MERGE -d 'MERGE-' -d X`.
