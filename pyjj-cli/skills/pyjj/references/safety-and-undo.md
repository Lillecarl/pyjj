# Safety policy, undo, and the operation log

## Policy

Never rewrite history unless User asked for that specific rewrite. Holds even when pyjj would allow it: see Immutability.

### Always fine (append-only)

- `pyjj commit -m '...'`: describes `@`, opens a fresh empty child
- `pyjj new [-m '...'] [<rev>...]`: new empty commit; an old revision as parent just branches off it. No `--allow-backwards` flag on `new` (neither pyjj nor jj)
- `pyjj split <fileset> -m '...'` on `@` without `-o`/`-A`/`-B`
- `pyjj bookmark create <name> -r <rev>`
- `pyjj describe -r @- -m '...'`: renaming a finished parent. Avoid describing `@` itself (below)
- `pyjj squash --use-destination-message`: `@` into its immediate parent as a trivial fixup
- `pyjj next` / `pyjj prev` without `--edit`: create a new empty commit, touch no existing one
- `pyjj revert`: new commit with the inverse diff
- `pyjj op log` / `op show` / `op diff` / `undo` / `redo` / `op restore` / `op revert`

### Needs an explicit request

- `pyjj edit <rev>`, `pyjj next --edit`, `pyjj prev --edit`: move `@` onto a past commit; later edits rewrite it
- `pyjj rebase` (any form)
- `pyjj split` with `-o`/`-A`/`-B`, or `-r <rev>` on a commit other than `@`
- `pyjj absorb`, `duplicate`, `parallelize`, `metaedit`, `arrange`, `simplify-parents`: see [advanced-operations.md](advanced-operations.md)
- `pyjj run`: not read-only. Amends each targeted revision with the command's result and rebases descendants. `--ignore-changes` runs the command without rewriting
- `pyjj bookmark move` / `bookmark delete`
- `pyjj op abandon`: permanently prunes operation history, narrowing what `undo`/`op restore`/`op revert` reach. The only `op` subcommand that is not recovery

### Never run a git command that writes in a pyjj repo

No exceptions. Git writes (`commit`, `merge`, `rebase`, `reset`, `cherry-pick`, `push`, `tag`, `stash`, `branch -d`) bypass the operation log: `undo` and `op restore` cannot see them, and pyjj's view can desync from `.git`. Every write goes through `pyjj`; find the command in [git-mapping.md](git-mapping.md).

Read-only git (`git log`, `diff`, `show`, `status`, `blame`) is fine.

### `describe` does not close `@`

`pyjj describe` on `@` sets the message and leaves `@` open: the next edit lands inside the described commit. Finish work with `pyjj commit`. Use `describe -r @-` for a commit already closed.

## Immutability

Commits in `immutable()` (default: ancestors of `trunk()`, tags, untracked remote bookmarks; see [revsets.md](revsets.md)) refuse rewrites. Bypass: `--ignore-immutable`. Error:

```
Error: Commit <id> is immutable
```

(pyjj prints no `Hint:` lines; jj does.)

**With no remote, `trunk()` falls back to `root()` and `immutable()` is just `{root}`.** A local `main` does not protect its history. Verified in both: `describe -r main` succeeds before `pyjj git push --bookmark main` to a remote, fails with "is immutable" after. Do not rely on the guard in scratch repos, fresh projects or CI checkouts; the policy above stands alone.

## pyjj's own guards

### `--dry-run`, `--abort-on-conflict` (pyjj only; jj has neither)

On `rebase`, `squash`, `split`, `absorb`, `duplicate`, `revert`, `abandon`, `simplify-parents`. Not on `describe`, `new`, `metaedit`, `parallelize`.

- `--dry-run`: prints `Would write N commits.` (plus `New conflicts would appear in N commits:` and the commits). Writes nothing, records no operation, exit 0
- `--abort-on-conflict`: when the rewrite would add conflicts, prints `Error: this would leave N commits in conflict:` and `Nothing changed.`, exit 1
- Together: dry-run output, exit 1 when conflicts would appear. Use that as a pre-flight check

```bash
pyjj rebase -r @ -d main --dry-run --abort-on-conflict || echo "would conflict"
```

Without `--abort-on-conflict` a conflicting rewrite succeeds (exit 0) and leaves conflicted commits; `{{ conflict }}` in `-T` reports them.

### Fast-forward-only trunk

A bookmark named in `pyjj.fast-forward-bookmarks` (default `main`, `master`, `trunk`) is protected once a remote other than `git` has a bookmark of that name. A never-pushed repo is unconstrained. The check reads the transaction's final view, so every command that moves the bookmark is covered: `bookmark set`, `abandon`, `--ignore-immutable` rewrites, `undo`, `op restore`.

Refused, before anything is written (exit 1):

- `bookmark set main -r <non-descendant>` (even with `--allow-backwards`): `Error: Refusing to move backwards or sideways fast-forward-only bookmark main`
- `bookmark delete main`: `Refusing to delete fast-forward-only bookmark main`
- a move that leaves it conflicted

Hint printed: `Use --allow-nonff to allow it.` `--allow-nonff` is a global flag, accepted before or after the subcommand. Using it needs an explicit request. Fetch, import, pull and track/untrack are exempt.

## `undo`, `redo`, operation log

Every command is one operation. The log covers commits, bookmarks and workspace `@` pointers together.

```bash
pyjj op log --limit 10                          # most recent first
pyjj undo                                       # undo the last operation
pyjj redo                                       # redo it
pyjj op restore <operation-id>                  # whole repo back to that operation
pyjj op revert <operation-id>                   # undo one past operation, keep later ones
```

- `undo` takes no id: it undoes the last operation
- `op restore <id>` rewinds everything since (itself a new operation, so recoverable)
- `op revert <id>` removes one operation's effect and keeps later work
- `op restore` and `op revert` take short id prefixes (`pyjj op restore 5c15`) and `@`/`@-`. Unknown prefix: `Object ab of type operation not found` or `` `zzzz` is not a valid operation id``, exit 1
- `op restore` prints nothing on success (jj prints `Restored to operation: ...`; pyjj differs from jj here; bug reported). Check with `op log`
- Rewritten and abandoned commits become hidden, not deleted: recover one by commit id (find it in `op log`) while it exists. See [revsets.md](revsets.md)
- `pyjj --at-op <op> log` reads state as of a past operation

### Do not chain `undo` expecting "back N steps"

Reproduced on pyjj and jj 0.47. `undo` is itself an operation, and a snapshot of the working copy precedes most commands. With commits `step 1..3`: the first `undo` undoes the `commit -m 'step 3'` (`f3` stays on disk); the second undoes the snapshot operation the first `undo` made, not `step 2`, and `f3` disappears from disk.

Nothing is lost: `pyjj op restore <id of the 'commit step 3' operation>` restores everything. After any `undo`, check `op log` (or `status`, `log`) before the next. For more than one step back, `op restore` to an identified id.

### Checkpoint before multi-step work

```bash
pyjj op log --no-graph --limit 1 -T '{{ id_short }}'    # note the id
```

Later, `pyjj op restore <id>` returns the whole repo (commits, bookmarks, working copy) to that point in one step. Preferred over counting `undo` calls. It bounds the cost of an autonomous multi-step sequence going wrong. It does not relax the rewrite policy.

## Verify, and know when to stop

After an operation (or small group), check the result: `pyjj status`, `pyjj log -r '<revset>'` ([revsets.md](revsets.md)). Exit 0 does not mean the intended result.

- One obviously wrong last step: one `pyjj undo` (or `op restore` to a recorded checkpoint), then retry
- Anything deeper (several operations since the mistake, unclear which one broke it, unexpected conflict or divergence): stop. Do not run more operations. Report to User: the goal, current `status`/`log`/`op log` output, the suggested recovery (`op restore <id>`), then wait

## Working-copy staleness

See [workspaces.md](workspaces.md) (`pyjj workspace update-stale`).

## Global flags

| Flag | Effect | Agent use |
|---|---|---|
| `--ignore-immutable` | bypass the immutability check | No, unless the specific rewrite was requested |
| `--allow-nonff` | bypass the fast-forward-only trunk guard | No, unless requested |
| `--ignore-working-copy` | skip the working-copy snapshot | No: work against on-disk state |
| `--at-op <op>` / `--at-operation` | run as of a past operation | Fine for read-only inspection |

Verified against pyjj v0.1.0-b02afea63cf86f2fad18f4b73a5f507e0eeb84a1 and jj 0.47.
