# Workspaces (jj's term for Git worktrees)

A workspace is a working copy with its own `@`, sharing the repository (commits,
operation log) with the other workspaces. Use one per parallel task so edits never
collide in one working copy.

## Creating

```bash
pyjj --no-pager workspace add --name ws1 /path/to/new/workspace
pyjj --no-pager workspace add --name ws1 ../ws1 --revision main
```

- `--name`: default is the directory's basename.
- Default `@` is a sibling of the current `@` (same parents, not the same commit).
  `-r/--revision` (repeatable, several make a merge) branches it off those revisions.
- `--sparse-patterns copy|full|empty`: default copies the current workspace's patterns.
- The destination must not exist or must be empty (error otherwise, also for a forgotten workspace's directory).
- A colocated repo gets a Git worktree for the new workspace (`--colocate` /
  `--no-colocate`).

## Listing / locating

```bash
pyjj --no-pager workspace list                  # name: path, @ change id, commit id, description
pyjj --no-pager workspace root                  # current workspace
pyjj --no-pager workspace root --name ws1
```

- `pyjj log` default and `builtin_log_compact` mark each `@` as `<name>@` (`default@`);
  `builtin_log_oneline` does not.
- Revsets reference another workspace's working copy as `<name>@`:
  `pyjj log -r 'ws1@'`, `pyjj diff -r 'ws1@'`.

## Working across workspaces from one place

All workspaces share the repo, so another workspace's `@` is readable from anywhere:

```bash
pyjj --no-pager log -r 'ws1@' --no-graph -T '{{ description }}'
pyjj --no-pager diff --git -r 'ws1@'
```

Read only. Never manipulate another workspace: no rewrite of its `@` or any mutable
ancestor of it (`describe`, `squash`, `rebase`, `abandon`, `absorb`), no `-R <other
path>`, `update-stale` or `forget` on it. That workspace belongs to whatever works in
it, and its files go **stale** (below). This holds from every workspace, `default`
included.

Exceptions: Agent is the sole agent owner of both workspaces (this session created or
took over both, and no other session works in either), or User asks for that exact
rewrite. Uncertain ownership is not ownership.

## Staleness and `pyjj workspace update-stale`

A workspace is stale when another workspace changed its `@` and its files on disk no
longer match. Measured on pyjj and jj 0.47:

| Rewrite from elsewhere | Effect here |
| --- | --- |
| Move a bookmark this workspace follows (`main`) | Nothing visible. `@` stays put, now off `main`. |
| Change only a description of `@` or an ancestor | Not stale. Unsnapshotted edits survive. |
| Change the tree of `@` or an ancestor (rebase onto other content, squash into) | Stale. Every command here, `pyjj status` included, fails until `pyjj workspace update-stale`. |
| Same, with unsnapshotted edits on disk | `update-stale` leaves `@` divergent: the edits sit in the older commit, `@` is a sibling without them. The files look lost. |
| `pyjj -R <this path> ...` | Runs as this workspace: snapshots first, so edits survive. Still a rewrite of someone else's `@`. |

Recovery:

```bash
pyjj --no-pager workspace update-stale
```

The stale error text says `jj workspace update-stale`; run it as `pyjj`.
`update-stale` on a fresh workspace prints "Attempted recovery, but the working copy is
not stale." Divergent `@` afterwards: `pyjj log -r 'change_id(<id>)'` shows both
commits; the older one holds the edits.

## Removing a workspace

```bash
pyjj --no-pager workspace forget ws1     # name required
pyjj --no-pager workspace remove ws1     # forget + delete the directory
```

- `forget` only drops the repo's record, and the colocated Git worktree link. The
  directory and its files stay. Commands run inside it then fail: jj prints `No working
  copy.`; pyjj prints a Python traceback ending in `KeyError: '<name>'` (pyjj differs
  from jj here; bug reported).
- The directory is orphaned. `workspace add` at that path refuses (non-empty). Delete
  it yourself if unwanted.
- `remove` snapshots the workspace's working copy into a commit first, then deletes the
  directory. It cannot remove the main workspace.
- Both are undoable with `pyjj undo`. Undoing a `forget` restores the record, undoing a
  `remove` does not restore the directory.
- `pyjj workspace forget` with no name is a usage error; jj forgets the current
  workspace (pyjj differs from jj here; bug reported). Name it, or run `forget` from
  another workspace. Before forgetting a workspace with unfinished undescribed work,
  check `pyjj status` there.

## Renaming

```bash
pyjj --no-pager workspace rename new-name    # renames the current workspace
```

## Landing a workspace

Landing = a workspace's finished commits enter `main`. Every workspace lands its
own work, `default` included, with one command:

```bash
pyjj commit -m '<message>'   # @ must be empty
pyjj wf land                 # --onto <bookmark> for a trunk other than main
```

One transaction (`croshome/home/pyjj/land.py`): rebase every root of `main..@`
onto `main` (`pyjj rebase -b @ -d main`), then move `main` to `@-`. The move is
forward, so pyjj's fast-forward guard passes it. Only the local bookmark moves.

Refusals, each writing nothing:

- `@` has changes: commit first.
- a commit in `main..@-` has no description.
- the rebase would rewrite a commit under another workspace's `@` (it would go
  stale). Land the shared base from the workspace that owns it, or ask User.
- the rebase introduces a conflict: resolve in this workspace's own commits, then
  land again.

Nothing to land: it moves `@` onto `main` and stops. That is how a workspace,
`default` included, catches up after another one landed. Run it in the workspace
itself, never with `-R` on someone else's.

**Held = off limits.** `pyjj workspace list` gives each workspace's `@`. A bookmark on
another workspace's `@` or `@-` is held by that workspace. No workspace moves, sets,
deletes or rewrites a bookmark another workspace holds, nor another workspace's `@`
or its mutable ancestors (exceptions above). `main` moves only through
`pyjj wf land`: never `bookmark set main` by hand, also when a repository's
`AGENTS.md`/`CLAUDE.md` finish steps say so.

Then push `main` if the repository lands by pushing (its own `AGENTS.md` or
`CLAUDE.md` says).

Report position exactly: "landed, `main` at <change-id>", or "on top of `main`
(`main` not moved)", never "on `main`".

When the task is over, `pyjj workspace forget` the workspace.

## One workspace per parallel task

```bash
pyjj --no-pager workspace add --name task-a /tmp/proj-task-a --revision main
pyjj --no-pager workspace add --name task-b /tmp/proj-task-b --revision main
# work in each directory; when done in one:
cd /tmp/proj-task-a && pyjj --no-pager commit -m 'feat: task a'
```

Every workspace's commits are visible from every other (one repo). To combine two
workspaces' work without leaving either directory:

```bash
pyjj --no-pager new -m 'merge: combine task a and b' 'task-a@-' 'task-b@-'
```

Verified against pyjj v0.1.0-b02afea and jj 0.47.
