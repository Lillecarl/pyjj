# Rebase, merging, and conflict resolution

`pyjj rebase` rewrites history: it changes the commit IDs of everything it moves and
of their descendants. Run it only when User asked for that rebase. `pyjj new` with
several parents only adds a commit and is always safe.

pyjj prints no "Rebased N commits" or "New conflicts appeared" lines. Read the result
with `pyjj log`, `pyjj status`, `pyjj log -r 'conflicts()'`. A rebase ends with exit 0
even when it creates conflicts (see `--abort-on-conflict`).

## Merge commits

```bash
pyjj --no-pager new -m 'merge: combine A and B' <rev1> <rev2>   # any number of parents (octopus)
```

- Creates a commit with all given parents and moves `@` to it.
- Append-only. Prefer it to rebasing when branches only need combining.
- Another workspace's work: `pyjj new -m ... 'task-a@-' 'task-b@-'`. `task-a@` alone
  names that workspace's working-copy commit, usually empty.

## What moves (pick one; default `-b @`)

| Flag | Moves |
|---|---|
| `-s/--source <revset>` | the revisions and all descendants |
| `-b/--branch <revset>` | `(dest..X)::`, the whole branch since it diverged from the destination |
| `-r/--revisions <revset>` | only those revisions; their descendants are rebased onto the old parents of the moved ones |

## Where it goes (required; pick one)

| Flag | Effect |
|---|---|
| `-o/--onto <revset>`, aliases `-d`, `--destination` | child of the given revisions; several revisions make a merge |
| `-A/--insert-after <revset>` (`--after`) | inserted after; the target's children are rebased onto the moved commits |
| `-B/--insert-before <revset>` (`--before`) | inserted before; the target and its descendants are rebased onto the moved commits |

```bash
pyjj --no-pager rebase --source @ --onto main
pyjj --no-pager rebase --branch my-feature --onto main
pyjj --no-pager rebase --revisions <rev> --onto main          # one commit, descendants stay
pyjj --no-pager rebase --source L --onto K --onto M           # several destinations: merge
pyjj --no-pager rebase -r <rev> --insert-after <target>
```

- No destination flag: error, exit 2.
- Other flags: `--skip-emptied` (abandon commits the rebase empties),
  `--keep-divergent`, `--simplify-parents`.
- pyjj-only `--dry-run`: reports "Would write N commits", writes nothing. jj has no such flag.
- pyjj-only `--abort-on-conflict`: if the rebase would add conflicts, prints the
  commits, writes nothing, exits 1. Use it to try a rebase safely. `pyjj new` takes both flags too.
- Undo a rebase: `pyjj undo`.

Cycles: jj refuses `rebase -s A -o <descendant of A>` with `Cannot rebase X onto
descendant Y` and `-o A` onto itself with `Cannot rebase X onto itself`, exit 1. No
override. pyjj does not refuse: it exits 0 and changes nothing visible (an operation is
still recorded) (pyjj differs from jj here; bug reported). `-r` onto a descendant is
legal in both (the descendants are reparented, conflicts are likely).

A rebase that abandons or moves a workspace's `@` gives that workspace a new `@`
automatically.

## Conflicts

A merge or rebase conflicts where both sides changed overlapping content. The
conflicted commit stays in history; `@` is marked `(conflict)` in `pyjj log`, and
`pyjj status` prints `Warning: There are unresolved conflicts at these paths:`.
`pyjj log -r 'conflicts()'` lists conflicted commits. `{{ conflict }}` in a `-T`
template is a boolean.

The working-copy file holds markers (jj 0.47 labels shown; pyjj writes the same):

```
DEBUG=True
<<<<<<< conflict 1 of 1
%%%%%%% diff from: <id> <commit> "base" (parents of rebased revision)
\\\\\\\        to: <id> <commit> "X" (rebase destination)
-MODE=0
+MODE=x
+++++++ <id> <commit> "Y" (rebased revision)
MODE=y
>>>>>>> conflict 1 of 1 ends
```

A merge made with `pyjj new` labels its sides by commit and description only, without
the parenthesized roles.

### Resolving

Conflicted commit is `@`: edit the file, remove the markers, save. The next command
snapshots and the conflict clears.

```bash
pyjj --no-pager status          # warning gone
pyjj --no-pager resolve --list  # "Error: No conflicts found at this revision"
```

Conflicted commit is not `@`: both routes rewrite history, so each needs User's go-ahead
unless User asked for this fix.
1. `pyjj new <conflicted-rev>`, resolve in the new commit, then `pyjj squash -u` to move
   the resolution into the conflicted commit (`-u` keeps the destination message and
   avoids the editor). Verified: descendants are rebased and the conflict clears.
2. `pyjj edit <conflicted-rev>` and resolve in place (harder to review).

### Tools

```bash
pyjj --no-pager resolve --list [-r <rev>]   # conflicted paths
pyjj --no-pager resolve --tool :ours        # pick a side without a merge tool (also :theirs)
pyjj --no-pager resolve                     # configured 3-way merge tool
pyjj --no-pager restore <path>              # discard local edits, back to the parent's version
```

- `resolve` handles only conflicts with two sides and a base. Directory/file and symlink
  conflicts: edit by hand.
- `resolve --list` prints bare paths; jj appends `    2-sided conflict` (pyjj differs from jj here; bug reported).
- `resolve` with no conflict exits 1; jj exits 2.

Verified against pyjj v0.1.0-b02afea and jj 0.47.
