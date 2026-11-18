# Remotes: clone, fetch, push, divergence

## Clone

`pyjj git clone <url-or-path> <dest>` (colocated by default; `--no-colocate` hides git in `.jj`).
- Tracks only the remote's default branch (its `HEAD` symref). Every other remote bookmark stays untracked: `feature@origin` listed, no local `feature`.
- `pyjj new feature` on an untracked one fails `Revision 'feature' doesn't exist` (jj adds a "Did you mean `feature@origin`?" hint; pyjj does not). Fix: `pyjj bookmark track feature --remote=origin`, or name `feature@origin` directly.
- A bare remote needs no `git`: `pyjj git init --no-colocate hub` gives a bare git repo at `hub/.jj/repo/store/git`; use that path as the remote URL.

## Fetch

`pyjj git fetch [--remote <name>]`
- Moves `<name>@<remote>` for every remote bookmark.
- Moves the local bookmark only if tracked: merged if both sides moved compatibly, conflicted otherwise.
- Untracked: only the `@<remote>` position moves.

## Push

`pyjj git push --bookmark <name>` | `--all` | `--dry-run`
- Output lists `Add bookmark X`, `Move forward bookmark X`, `Delete bookmark X`. Sideways and backward moves also print `Move forward bookmark X` (pyjj differs from jj here; jj prints `[move sideways from A to B]`, `[move backward ...]`; bug reported). Do not read the move kind from the label.
- A bookmark absent from the remote is added and becomes tracked.
- Stale check always on (force-with-lease): remote moved since last fetch -> refused, nothing pushed:
  ```
  Warning: The following references unexpectedly moved on the remote:
    feature (reason: stale info)
  Hint: Try fetching from the remote, then make the bookmark point to where you want it to be, and push again.
  Error: Failed to push some bookmarks
  ```
  (jj spells the ref `refs/heads/feature`.) Fix: `pyjj git fetch`, reconcile, push again.
- A rewrite of an already-pushed commit pushes as a normal move when the remote still matches the last fetch.
- `pyjj git push --bookmark nosuch` and a bare `pyjj git push` with nothing to push print only `Nothing changed.`, exit 0 (jj warns; pyjj differs, bug reported).
- Trial flags `--dry-run` also exist on push; pyjj `--abort-on-conflict` is for rewrites, not push.

### Fast-forward-only trunk

`main`, `master`, `trunk` (config `pyjj.fast-forward-bookmarks`) with a non-`@git` remote counterpart refuse any sideways or backward move, before anything is written:
```
Error: Refusing to move backwards or sideways fast-forward-only bookmark main
Hint: Use --allow-nonff to allow it.
```
- Applies to `bookmark set/move`, rewriting the bookmarked commit, even with `--ignore-immutable`.
- Override: global flag before the subcommand, `pyjj --allow-nonff --ignore-immutable describe -r main -m ...`, then `pyjj --allow-nonff git push --bookmark main`.
- Fetch and `bookmark track` follow the remote unguarded.
- Any other bookmark (e.g. `feature`) is unguarded.
- A rewrite of a commit that `trunk()` (`main@origin`) already contains is also refused as immutable: `Error: Commit <id> is immutable`.

## Divergence: two clones rewrite the same commit

Two different things:
- Bookmark conflict: the name `feature` has two targets.
- Divergent change: one change id has several visible commits.

Both appear when two clones rewrite a bookmarked commit and both publish.

Sequence (reproduced with two independent clones of one bare remote, `feature` tracked in both):
1. Clone A rewrites `feature` (`pyjj describe -r feature -m 'X (A)'`), pushes. Accepted.
2. Clone B rewrites it differently without fetching, pushes. Refused (stale info).
3. Clone B `pyjj git fetch`. Now:
   - `pyjj bookmark list` shows the conflict; `@git`/`@origin` lines are the remote-tracking positions:
     ```
     feature (conflicted):
       - msnpxoov/2 c09aecda (hidden) work
       + msnpxoov/1 a6d18285 (divergent) work (B)
       + msnpxoov/0 178a80cd (divergent) work (A)
       @git (behind by 1 commits): msnpxoov/1 a6d18285 (divergent) work (B)
       @origin (behind by 1 commits): msnpxoov/0 178a80cd (divergent) work (A)
     ```
     Non-conflicted bookmarks print only the local line; `-a`/`--all-remotes` adds remote lines. `@git` appears in non-colocated repos too (it is the git backend's own ref namespace, not evidence of colocation). `-c` lists conflicted only.
   - `pyjj log -r 'divergent()'` finds both commits. `pyjj log` shows both versions; default `log` and `status` show no `??`, no `(divergent)` and no conflicted-bookmark warning (pyjj differs from jj; bug reported). `-T builtin_log_compact` shows `/0`, `/1` and `(divergent)` but still no `??`.
   - A bare change id now errors: `Error: Change ID msnpxoov is divergent` (jj adds hints for `id/0`, `change_id(id)`, `abandon`; pyjj prints none).
   - Address sides by offset `msnpxoov/0`, `msnpxoov/1`, or all via `change_id(msnpxoov)`.

### Resolve

Pick one side:
```
pyjj bookmark set feature -r 'msnpxoov/0'
pyjj git push --bookmark feature
```
Reconcile into a merge:
```
pyjj new 'msnpxoov/0' 'msnpxoov/1' -m 'merge: reconcile divergent feature'
pyjj bookmark set feature -r @
pyjj git push --bookmark feature
```
- Both push as `Move forward bookmark feature`; the other clone then fetches with no conflict.
- Resolving the bookmark does not end the divergence. `divergent()` still lists both commits (after the merge, as its ancestors; after picking a side, the unpicked one stays visible). Harmless. To clear it: `pyjj abandon <commit_id>` of the unwanted side (verified: `divergent()` then empty).
- Undo a wrong resolution: `pyjj op restore <op id>` (note the id first with `pyjj op log --no-graph --limit 1`).

Agent procedure:
1. Identify the conflicted name and divergent change id.
2. View both: `pyjj log -r 'change_id(<id>)' --no-graph`.
3. One side wrong: `bookmark set`. Both worth keeping: merge. Unclear which wins: ask the user.
4. Push the resolution.

Verified against pyjj v0.1.0-b02afea63cf86f2fad18f4b73a5f507e0eeb84a1 and jj 0.47.
