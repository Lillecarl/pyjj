# Splitting: `pyjj split`

Default tool for turning a messy working copy (or any commit) into clean commits. File granularity only; for finer, use [hunk.md](hunk.md).

## Non-interactive form

- With path arguments, `pyjj split` never opens a diff editor. Matched paths go to the first commit, everything else to the second.
- **Never run `pyjj split` with no paths.** Without a configured diff tool it errors (`no diff editor specified; pass --tool`); with one it launches it. jj itself fails with a terminal error headless.
- **Always pass `-m`/`--message`.** It is the first half's description. Without it, a split of a described revision opens the description editor and fails headless.
- Second half keeps the original description (usually none for a WIP `@`).

```bash
pyjj split src/config.py -m 'feat: add debug config flag'
pyjj split src/foo.py src/bar.py -m '...'     # several files
pyjj split src/ -m '...'                      # directory
pyjj split -r <rev> <paths...> -m '...'       # a commit other than @
pyjj split <paths...> -m '...' --parallel     # siblings, not parent/child
```

- Splits `@` by default. First half = "selected", second = "remaining" (child; the new `@` when splitting `@`).
- Paths are plain files or directories, relative to cwd. **Filesets are not parsed** (see below).

## Identity after a plain split

- First (selected) commit keeps the original change id; the second gets a fresh one.
- Bookmarks on the pre-split commit move to the **second** (remaining) commit. Same in jj (`split.legacy-bookmark-behavior` defaults true there).
- `split.legacy-bookmark-behavior = false` flips it in jj (bookmark stays with the first commit). pyjj ignores the setting and always moves the bookmark to the second commit (pyjj differs from jj here; bug reported). `pyjj config get split.legacy-bookmark-behavior` also reports it unset, where jj prints `true`.
- Placement flags (below) give the *selected* part the fresh change id instead; check `pyjj bookmark list` afterwards if a bookmark is involved.

## Repeated splitting

Peel one concern off the front each time; `@` stays as the unsplit remainder:

```bash
pyjj split src/schema.py -m 'feat: add schema'
pyjj split README.md -m 'docs: describe schema'
pyjj commit -m 'feat: wire schema into api'     # whatever is left
```

## Paths, not filesets

jj parses fileset expressions here; pyjj reads each argument as a literal path.
- jj: `'glob:"*.md"'`, `'~src/wip.py'`, `'a.md|c.py'`, `file:a.md` all work in `split` and `diff`.
- pyjj: the same arguments print `No matching entries for paths: ...` and, for `split`, `No changes have been selected, so the new revision will be empty.` (pyjj differs from jj here; bug reported.)
- Until fixed, list files or directories explicitly. To split "everything except X", name what goes first.

## Placement flags

Relocate the *selected* part; the remainder stays in place. Behavior matches jj.

- `--onto <rev...>` (alias `--destination`): new commit whose parents are the given revisions. Several revisions make a merge. Does **not** splice into a line: `--onto @-` yields two siblings under `@-`.
- `--insert-after <rev...>` (`--after`, `-A`): splice in directly after; its children rebase onto the new commit.
- `--insert-before <rev...>` (`--before`, `-B`): splice in directly before; those commits and descendants rebase onto it.

```bash
pyjj split src/bugfix.py -m 'fix: null check' --onto main
pyjj split src/bugfix.py -m 'fix: null check' --insert-after main
```

Placement flags can rebase descendants beyond `@`: treat them like `pyjj rebase` under the policy in [safety-and-undo.md](safety-and-undo.md).

## Folding a peeled piece into an earlier commit

```bash
pyjj split shared.txt -m 'the missed tweak'            # peeled commit sits at @-
pyjj squash --revision @- --use-destination-message    # fold into its parent
```

- `--use-destination-message` keeps the destination's description. Without it, a squash that empties a described revision opens the description editor (fails headless).
- Whole files, one step, any destination (`--from` defaults to `@`):

```bash
pyjj squash --from @ --into <rev> path/to/file
```

- Hunks into the parent of the source revision, one step: `pyjj hunk squash` ([hunk.md](hunk.md)). It has no destination flag; for a farther destination peel with split, then squash.

## `--parallel`

Halves become siblings instead of parent/child. Use for independent changes edited together.

## Verifying

```bash
pyjj log --limit 5 --revisions 'root()..@' -T builtin_log_compact_full_description --stat
pyjj diff --git --revisions <rev>
```

Verified against pyjj-cli v0.1.0-b02afea63cf86f2fad18f4b73a5f507e0eeb84a1 and jj 0.47.
