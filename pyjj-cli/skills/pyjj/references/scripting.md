# Scripting, graph reshapes and extensions (pyjj-only)

jj has none of these.

## Session API and `pyjj python`

`pyjj python [-c cmds | script.py | -]` runs Python with `pyjj`,
`pyjj_bindings` and `repo` bound (`repo` is open on `-R`; `--no-repo` leaves
it `None`). Arguments after the script name reach it as `sys.argv[1:]`,
option-shaped ones too.

- `pyjj.open()` + `repo.atomic("msg")`: one block is one transaction. A clean
  exit commits it as one operation; any exception discards it, nothing
  written. Verbs use jj's names: `squash`, `describe`, `new`, `commit`,
  `split`, `rebase(..., destination|after|before)`, `abandon`, `duplicate`,
  `absorb`, `restore`, `revert`, `bookmark`.
- Revisions inside a block resolve through the transaction, which sees the
  block's own writes; `repo` itself still answers from the starting state.
- `atomic(..., allow_conflicts=, allow_immutable=, allow_nonff=)`: without
  them, a block that introduces a conflict, touches an immutable commit or
  moves a published trunk backwards is discarded.
- `tx.restore(...)` rewrites in place, `tx.revert(...)` appends.

Prefer one block over several CLI calls when several rewrites belong together,
and prefer scripting over templates for structural questions (walk
`repo.log()`, read `commit.list_files()` / `read_file()`).

```
pyjj python - <<'EOF'
with repo.atomic("tidy the stack") as tx:
    tx.squash("@", into="@-")
    tx.describe("@-", message="the whole change")
EOF
```

## Reshape via DOT graph

`pyjj log -r '<revset>' --dot --dot-key change_id -T '{{ subject }}' > base.dot`
exports the shape. Edit edges, then:

- `pyjj graph plan base.dot`: prints the rebases, writes nothing. Read it.
- `pyjj graph apply base.dot`: all-or-nothing; a new conflict or an immutable
  commit drops the whole reshape unwritten (`--allow-conflicts`,
  `--ignore-immutable` override). `--dry-run` reports, exit 1 if it would
  conflict. On success prints `Restore with: pyjj op restore <id>`.

Every step is a rebase, plus abandonment: a node with `abandon="true"` is
dropped and its children re-pointed at its parents. A graph cannot create
commits, so merges and reverts come from commands or a script; `--dot`
export verifies the result.

Key on change ids (`--dot-key change_id`): a rewrite replaces a commit id, and
the old one still resolves, to the obsolete predecessor. File order is
topological, parents first; cycles are refused.

`--dot` also reads topology better than the ASCII graph, which can draw a
wrong edge almost identically to the right one:
`pyjj log -r 'all()' --dot -T '{{ subject }}'`.

## Extensions: identity hooks and workflows

`pyjj.extensions` (config, list of `.py` paths, `~` expanded) names files
imported once per run. `--config 'pyjj.extensions=["x.py"]'` loads one for a
single run.

- `pyjj.identity(fn)`: `fn(ctx)` returns `pyjj.Identity(name, email,
  signing_key, signing_backend, sign_behavior)`, a `{config key: value}` dict,
  or `None` (next hook). `ctx`: `remotes` (name to fetch URL),
  `workspace_root`, `repo_path`, `settings`. Runs when a repository loads, as
  a layer under `--config`. A raising hook fails the command, nothing written.
  Rewrites keep a commit's author; new commits, committer and signature use
  the hook's answer. No hook on `git init`/`clone`.
- `class X(pyjj.Workflow)`: `name`, `help`, `add_arguments(parser)`,
  `run(repo, args) -> int | None`; `self.pyjj(repo, *argv)` runs a pyjj
  command in-process. `pyjj wf` lists them, `pyjj wf NAME ...` runs one.
  Metavars `REVSET`/`BOOKMARK`/`REMOTE` complete like pyjj's own.
