---
name: pyjj
description: Drive a Jujutsu (jj) repository through the pyjj CLI or its Python session API — history rewrites, DOT-graph reshapes, safe trial loops with restore points. Load when editing history, scripting jj operations, or working in a repo where `pyjj` is the interface.
---

# pyjj

`pyjj` mirrors the `jj` CLI on top of `jj_lib`. Two interfaces, same repository:

- **CLI**: `pyjj <command>` — speaks jj's argument dialect (`-r`, `-d`, `-A`/`-B`).
  Pass `-R <path>` when the repo is elsewhere.
- **Session API** (`import pyjj`): `pyjj.open()` + `repo.atomic("msg")` block.
  One block is one transaction: clean exit commits it as one operation,
  any exception discards it with nothing written. Verbs use jj's names
  (`squash`, `describe`, `rebase(..., destination|after|before)`, `absorb`,
  `restore`, `duplicate`, `bookmark`).

## Safe rewrite loop

Every `graph apply` prints `Restore with: pyjj op restore <id>` on success
(plus `before_op` in `--format json`). Checkpoint before risky sequences
with `pyjj op log --no-graph --limit 1` and restore that id on trouble.
Never chain `jj undo`; one `op restore` returns to a known-good point.

## Reshape via DOT graph

`pyjj log -r '<revset>' --dot --dot-key change_id -T '{{ description }}' > base.dot`
exports the shape. Edit edges, then:

- `pyjj graph plan base.dot` — prints the rebases, writes nothing. Read it.
- `pyjj graph apply base.dot` — all-or-nothing; conflicts or immutable
  commits roll everything back.

Every step is a rebase: the graph can rearrange parents but cannot
create commits, so it cannot build a merge-based topology — only
verify one afterwards via `--dot` export. New commits (merges,
reverts) come from the commands below or a script, not from a graph.

Key the graph on **change ids** (`--dot-key change_id`): commit ids are
content hashes, so a rewrite replaces them and the old one still resolves
to the obsolete predecessor. Order in the file is topological, parents
before children — the resolver enforces it and refuses cycles.

## Scripting (`pyjj python`)

`pyjj python [-c cmds | script.py | -]` runs Python with `pyjj`,
`pyjj_bindings` and `repo` already bound (`repo` is open on `-R`;
`--no-repo` leaves it `None`). Script args follow the script name.

Prefer scripting over templates when the question is structural (walk
`repo.log()`, read `commit.list_files()` / `read_file()`), and prefer
one `repo.atomic("msg")` block over several CLI calls when several
rewrites belong together: the block is a single transaction, so it
becomes a single operation or nothing at all.

```
pyjj python - <<'EOF'
with repo.atomic("tidy the stack") as tx:
    tx.squash("@", into="@-")
    tx.describe("@-", message="the whole change")
EOF
```

Operation ids accept unique prefixes wherever a command names one
(`op restore`, `op show`, `--at-op`): paste the short id `op log`
prints, no need for the full hex.

## Gotchas

- Undoing a commit is two different verbs: `restore -c REV` rewrites
  that revision in place (same as `jj restore --changes-in`), while
  `revert -r REV` appends a new undo commit and leaves the original
  alone (same as `jj revert`). The session API mirrors both:
  `tx.restore(...)` rewrites, `tx.revert(...)` appends.
- Revisions inside an `atomic` block resolve through the transaction, which
  sees the block's own writes; the repo object still answers from the
  starting state.
- `graph apply` refuses immutable commits (override: `--ignore-immutable`)
  and rolls back on introduced conflicts (keep: `--allow-conflicts`).
- Output templates are Jinja2 (`-T` takes Jinja, not jj's template language).
- `jj commit` labels `@` then opens a fresh empty child; further edits land
  in the child, not the commit just finished.
