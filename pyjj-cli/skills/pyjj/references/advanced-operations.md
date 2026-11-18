# Advanced / less-common operations

Policy as in [safety-and-undo.md](safety-and-undo.md): additive commands are safe; anything that rewrites a commit needs the user's go-ahead unless asked for by name.

## `pyjj next` / `pyjj prev`

- Default (no `--edit`): makes a new empty commit at the target position; no existing commit changes. Safe.
- `--edit` (`-e`): moves `@` onto the existing adjacent commit; later edits rewrite it. Same policy as `pyjj edit`.
- `pyjj next [OFFSET]`, `pyjj prev [OFFSET]`, `--conflict` jumps to the nearest conflicted descendant/ancestor.
- Default `next` fails with "The working copy must not have any children" when `@` has children. It fits an empty leaf `@` whose parent has other children (for example after `prev`).
- Past the tip: "No other descendant found ..." (default) or "No descendant found ..." (`--edit`), exit 1.
- Trap: pyjj's default `next`/`prev` leaves the old empty undescribed `@` behind as a sibling; jj abandons it. Clean up with `pyjj abandon`. (pyjj differs from jj here; bug reported.)

## `pyjj edit REV`

Moves `@` onto an existing commit. Immutable commit: `Error: Commit <id> is immutable`. Rewrite-adjacent: ask first.

## `pyjj absorb [FILESET...]`

Moves each changed line of the current diff into the mutable ancestor that last touched it, then rebases descendants. Fully absorbed: `@` ends up empty, no fixup commit. A path argument limits the scope; the remaining hunks stay in `@`.

- Rewrites ancestors: ask first, unless the user asked to absorb.

## `pyjj duplicate REV...`

New commit with the same content and a new change id; the original stays. Placement: `-o/--onto`, `-A`, `-B` (a destination that makes a commit its own ancestor warns). Additive; ask first unless requested.

## `pyjj parallelize REVSET`

Makes the commits in the revset siblings: `pyjj parallelize B::C` turns A-B-C-D into B and C both children of A, with D a merge of both. Changes graph structure: ask first. `Nothing changed.` when they are already independent.

## `pyjj metaedit -r REV`

Changes metadata, not content; descendants are rebased.

- `-m MSG`, `--author "Name <email>"`, `--update-author` (reset author to the configured user), `--update-author-timestamp`, `--author-timestamp TS`, `--force-rewrite`, `--update-change-id` (new change id).
- Same caution as `pyjj describe`: fine on a finished parent, not on `@`.

## `pyjj revert -r REV`

Adds a new commit holding the inverse of REV's diff (`Revert "<subject>"`); the original is untouched. Safe.

- One of `-o/--onto` (alias `--destination`, `-d`), `-A/--insert-after`, `-B/--insert-before` is required, else an error.
- `-A`/`-B` rebase the followers of the insertion point onto the revert.
- Contrast `pyjj restore -c REV`: rewrites REV in place (empties it, rebases descendants). `revert` appends, `restore` rewrites. `restore --restore-descendants` keeps descendants' content verbatim.

## `pyjj rebase -r C -A P`

Inserts C after P: P's children are rebased onto C. A merge among those children keeps its other parents. `-B` inserts before. Rewrites: ask first.

## `pyjj simplify-parents -r REV`

Drops parent edges already reachable through another parent (commit with parents D and A where A is an ancestor of D keeps only D). Content unchanged. `Nothing changed.` when none are redundant. Rewrites: ask first.

## `pyjj run -r REVSET -- CMD ARGS...`

Rewrite operation, not a test runner. Checks out each revision in a scratch copy, runs the command, amends the revision with the result, rebases descendants.

- The command is argv after `--`, not a shell string: `-- sh -c 'echo hi >> out.txt'`.
- Flags: `-j/--jobs`, `--root`, `--clean`, `--restore-descendants`, `--ignore-changes` (run without rewriting), `--ignore-errors`, `--passthrough`, `--sparse-patterns {copy,full,empty}`.
- No change from the command: `Nothing changed.`
- Use only for a formatter or codemod across a range the user named. Never to "try the tests".

## `pyjj diffedit` / `pyjj arrange`: interactive

Need a diff editor or TTY UI; do not use. Use `pyjj split`/`pyjj hunk` ([splitting.md](splitting.md)) or `pyjj rebase`.

## File operations

```bash
pyjj file list [PATH...]              # -r REV
pyjj file show -r REV PATH
pyjj file search --pattern REGEX      # -r REV; --name-only, -n line numbers
pyjj file chmod x|n -r REV PATH...    # set/clear executable bit; rewrites REV
pyjj file track PATH
pyjj file untrack PATH
pyjj file delete -r REV FILESET       # rewrites REV
```

- `file untrack` of a path that is not gitignored fails: `Error: 'PATH' is not ignored.` plus a hint that the next command re-adds it. Add the path to `.gitignore` first.
- `file chmod` and `file delete` rewrite the revision and rebase descendants.
- `file delete` takes fileset expressions (`glob:"B*"`, `A.txt|C.txt`). `file list` and `diff` treat each argument as a literal path: a `glob:`, `|`, `~` or `all()` expression prints `No matching entries for paths` and lists nothing. (pyjj differs from jj here; bug reported.) See [filesets.md](filesets.md).

## Tags

```bash
pyjj tag list [NAME...]               # -T '{{ name }} {{ commit_id_short }}'
pyjj tag set NAME... -r REV           # --allow-move to move an existing tag
pyjj tag delete NAME...               # unknown name: warning, no error
```

- `tag set` on an existing name fails: `Refusing to move tag: NAME`, exit 1.
- `tag delete` takes literal names; `glob:v*` warns `No such tag`. (jj accepts string patterns; pyjj differs, bug reported.)
- Tags are in `immutable_heads()`: a tagged commit and its ancestors become immutable, so `pyjj describe -r B` fails with `Commit <id> is immutable`.
- `-T` variables: `name`, `commit_id_short`, `change_id_short`, `subject`. An unknown variable raises a Jinja traceback (bug reported).
- `tag track`/`untrack` take `NAME... [--remote REMOTE]`.

## Sparse checkout

```bash
pyjj sparse list                      # "." means everything
pyjj sparse set --add PATH --clear    # only PATH
pyjj sparse set --add PATH | --remove PATH
pyjj sparse reset                     # everything
```

- Changes only files on disk, not commits. `sparse edit` is interactive: skip.

## Operation log

```bash
pyjj op show OP                       # what OP changed
pyjj op diff --from OP --to OP
pyjj op revert OP                     # undo one past operation, keep later ones
pyjj op restore OP                    # whole repo back to OP, as a new operation
pyjj op abandon OP | A..B | ..OP      # permanently prune
```

- `undo` reverts only the latest operation. `op restore` jumps to OP and drops later changes from the view (still reachable through `op log`). `op revert` removes one operation's changes and keeps what came after.
- `op revert` in pyjj needs the full 128-hex operation id (`pyjj op log --no-graph -T '{{ id }}'`); a short id fails with `Object <id> of type operation not found`, and `@-` is rejected. `op show`, `op diff` and `op restore` accept short ids and `@-` forms. (pyjj differs from jj here; bug reported.)
- `op abandon` is the only operation-log command that is not fully reversible: it discards history and anything that becomes unreachable. Needs explicit user permission. Abandoning the current operation fails.
- `op show` has no `--no-patch`; use `-s`. `op diff` accepts `--summary`, `-s` and `--stat`.

Verified against pyjj-cli v0.1.0-b02afea63cf86f2fad18f4b73a5f507e0eeb84a1 and jj 0.47.
