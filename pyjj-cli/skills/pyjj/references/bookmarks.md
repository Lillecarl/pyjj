# Bookmarks

Named pointer to a commit. No "current branch": creating or editing a commit never moves one. A bookmark follows its commit across rewrites (rebase, describe) by change id; everything else moves it explicitly. `pyjj b` = `pyjj bookmark`.

## Commands

```
pyjj bookmark list [NAMES...] [-a|--all-remotes] [-t|--tracked] [--remote R] [-c|--conflicted] [-r REV] [-T TMPL]
pyjj bookmark create <name> [-r REV]          # default @; errors if the name exists
pyjj bookmark set <name> [-r REV]             # create or move
pyjj bookmark move <name>... --to REV         # existing bookmarks only
pyjj bookmark move --from REV --to REV        # whichever bookmarks point at --from
pyjj bookmark rename <old> <new>
pyjj bookmark delete <name>                   # local; the deletion propagates on next push
pyjj bookmark forget <name>                   # local only; never propagates
pyjj bookmark track <name> --remote=origin    # also: track name@origin
pyjj bookmark untrack <name> --remote=origin
```
- Backward or sideways moves (`set`, `move`) refuse: `Error: Refusing to move bookmark backwards or sideways: y`. Add `--allow-backwards` (`-B`) to force (works on `set` and `move`). `pyjj new` has no such flag: `pyjj new <old-rev>`.
- `move` of a name that matches nothing: pyjj prints `No bookmarks to update.`/`Already at <id>.`; jj warns `No matching bookmarks for names`.
- `create` on an existing name: `Bookmark already exists: x (use bookmark set to move it)`.
- `rename` onto an existing name fails.
- Fast-forward-only trunk (`main`, `master`, `trunk` with a remote): backward/sideways moves, delete and forget are refused unless `--allow-nonff`. See [remotes-and-sync.md](remotes-and-sync.md).
- `create`/`set` at a new name is additive. `move`/`delete` retarget or drop an existing pointer: do it for a bookmark Agent drives, never for a shared one (`main`) unasked.
- `forget` then `fetch` re-creates only the untracked `name@origin`; the local bookmark stays gone.
- `forget --include-remotes <name>` for a bookmark that exists only as `name@origin` fails in pyjj (`No such bookmark`); jj forgets the remote one (pyjj differs from jj; bug reported).
- `bookmark delete` of a tracked bookmark shows `feature (deleted)` plus its `@origin` line; `pyjj git push --bookmark feature` then prints `Delete bookmark feature`.

## Output

- Local line: `name: <change> <commit> <description>`. `name (conflicted):` lists `- removed` and `+ added` targets.
- Remote lines (`@origin`, `@git`): shown with `-a`/`-t`/`--remote`, and always for a conflicted bookmark. Push state: `@origin (ahead by 1 commits, behind by 1 commits): ...` when local and remote differ; no suffix when equal.
- `-T` is Jinja2. Verified: `-T '{{ name }}\n'` per bookmark. `{{ remotes }}` (list of dicts: `remote`, `tracked`, `synced`, `ahead`, `behind`) and `{{ unpushed }}` (bool) report push state.

## Remote tracking

`<name>@<remote>` is the last-seen remote position. Tracked: fetch moves the local bookmark, push sends it.
- Clone tracks only the default branch. Pushing a new local bookmark tracks the remote one.
- `track` on an already-tracked name prints nothing and changes nothing (jj warns); `untrack` leaves the local bookmark (it becomes local-only, `feature@origin` still listed).
- Push refuses if the remote moved since last fetch, or if the remote has it and it is untracked (`Error: Non-tracking remote bookmark ahead@origin exists`; track it first).
- Push is outward-facing: only when the user asked to publish.
- Details, stale-push error and divergence: [remotes-and-sync.md](remotes-and-sync.md).

## Conflicts

A bookmark moved differently in two places (local vs fetched remote) becomes conflicted. `pyjj bookmark list` shows it; `pyjj new <name>` then errors because the name resolves to several revisions.
- Pick one target: `pyjj bookmark set <name> -r <rev>`.
- Reconcile: `pyjj new <t1> <t2>`, then `bookmark set <name> -r @`.
- Default `pyjj log`/`status` do not flag conflicted bookmarks (jj prints `??` and a warning; bug reported). Use `pyjj bookmark list -c`.

## Log markers

`pyjj log` shows the bookmark name beside the commit. It does not print jj's `main*` (differs from remote), `main??` (conflicted) or `main@origin` markers; read push state from `bookmark list -a`.

Verified against pyjj v0.1.0-b02afea63cf86f2fad18f4b73a5f507e0eeb84a1 and jj 0.47.
