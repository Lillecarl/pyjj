# pyjj workflow

Python bindings, CLI, and TUI for Jujutsu (jj), split into four projects.
This used to live inside the jj monorepo itself (`~/Code/jj`); it was moved
out to its own repo so each project's Nix build could be genuinely
self-contained (its own directory *is* its Nix `src`, full stop) instead of
filtering a shared monorepo tree — see "Reproducible builds" below.

- `pyjj-bindings/` — Rust/PyO3 crate producing the native `pyjj_bindings`
  module. Its own independent Cargo workspace (own `Cargo.lock`). Depends on
  `jj-lib` as a normal crates.io dependency (pinned to the jj release this
  was last synced against — see its `Cargo.toml`), not a path dependency
  into a jj checkout — this repo has no jj monorepo source in it at all.
- `pyjj/` — pure Python, wraps `pyjj_bindings` in a pythonic API. This is what
  consumers (and `pyjj-cli`) should import, not `pyjj_bindings` directly.
- `pyjj-cli/` — CLI on top of `pyjj`.
- `pyjjui/` — Textual TUI on top of `pyjj`. See `pyjjui/AGENTS.md` for its
  own architecture/testing/packaging notes (kept separate since it's a
  different kind of project — a Textual app, not a binding layer).

Binding-surface coverage below (API coverage, async model, etc.) was written
against `jj_lib` 0.43.0 and describes `jj_lib`'s own behavior, not anything
monorepo-specific — it stays accurate regardless of where this repo lives.
When bumping the `jj-lib` crates.io version in `pyjj-bindings/Cargo.toml`,
re-check this section against that release's actual behavior/changelog.

## Fast local loop

For iterating on the Rust bindings, use `shells.default` (entered via
`nix develop --file .`; see "Reproducible builds" below for why not
`.#`-style flake installable syntax) — a bare cargo/rustc/maturin/python3
shell, deliberately not the `shells.pyjjui` editable-install one:

```
nix develop --file . shells.default --command bash
python3 -m venv .venv && source .venv/bin/activate
maturin develop -m pyjj-bindings/Cargo.toml   # incremental rebuild, installs into venv
pip install -e pyjj -e pyjj-cli
python pyjj-bindings/smoke_test.py
pyjj status   # from pyjj-cli
```

`maturin develop` only rebuilds what changed, so this loop is normal `cargo`
incremental compilation speed, not a full Nix rebuild each time.

## Tests

Two separate pytest suites, matching the project split:

```
pip install -e pyjj-bindings[test] -e pyjj[test]
(cd pyjj-bindings && pytest)   # unit-level: ids, errors, settings — no filesystem/workspace state
(cd pyjj && pytest)            # comprehensive: workspace/repo/transaction workflows, via tmp_path
```

Run each project's `pytest` from inside its own directory, as above.
`pyjj/pyproject.toml` and `pyjjui/pyproject.toml` set different
`[tool.pytest.ini_options]` (only `pyjjui`'s sets `anyio_mode = "auto"`), and
one `pytest pyjj/tests pyjjui/tests` invocation from the repo root picks just
*one* project's config for the whole session -- `pyjjui`'s async tests then
fail with "async def functions are not natively supported", because
`anyio_mode` never got applied.

A third suite, `pyjj/tests/parity/`, is conformance testing against the real
`jj` binary: every scenario runs the *same argv* through `jj` and through
pyjj-cli in two separate fresh repos, then asserts the resulting repos
are **bit-identical** (down to change ids and commit ids — determinism comes
from pinned identity/timestamps via the same `JJ_*` env vars both tools
read, a scratch HOME suppressing machine config, and per-logical-step
`JJ_RANDOMNESS_SEED` seeds; the pyjj side runs one fresh interpreter per
operation to mirror jj's process-per-command RNG model). Both repos are
extracted through the same `jj` binary, so a mismatch means real semantic
divergence, never extractor disagreement. It skips if no `jj` is on PATH;
set `PYJJ_PARITY_JJ=/path/to/jj` to pin the version under test (the Nix
build pins it to the release matching `pyjj-bindings`' jj-lib, see
"Reproducible builds"). This suite is where CLI-parity bugs get found and
regression-proven. In Nix, `nix build --file . checks.pyjj-conformance`
runs the whole pyjj pytest suite store-built against that pinned binary
(`nix/checks.nix`), with gitMinimal/openssh present for the clone and
signing fixtures. For filtered runs without remembering the full pytest
invocation, use the impure passthrough:

```
# store-built (sandboxed) — needs --impure to read host env at eval time
PYTEST_ARGS="-k test_absorb -xvs" nix build --impure --file . checks.pyjj-conformance
PYTEST_ARGS="--collect-only -q" nix build --impure --file . checks.pyjj-conformance

# live run on the working tree — no sandbox copy, faster for iteration
PYTEST_ARGS="-k test_absorb -q" nix run --file . tests
PYTEST_ARGS="--collect-only -q" nix run --file . tests
nix run --file . tests -- -k test_absorb -xvs   # CLI args also forwarded
```

Pass a `-k` expression that contains spaces **after** `--`, not through
`PYTEST_ARGS`: the wrapper word-splits `PYTEST_ARGS` unquoted, so
`PYTEST_ARGS="-k 'a or b'"` reaches pytest as three arguments and fails with
"file or directory not found: or".

```
nix run --file . tests -- -k "test_tag or test_workspace" -q   # works
PYTEST_ARGS="-k 'test_tag or test_workspace'" nix run --file . tests  # does not
```

Pure `nix build --file . checks.pyjj-conformance` (no `PYTEST_ARGS`, no
`--impure`) stays hermetic — `builtins.getEnv` returns `""` and the default
`-q` is used. The `tests` app (`default.nix:tests`, `writeShellApplication`)
sets `PYJJ_PARITY_JJ` to the pinned `jj` and isolates `HOME`; `PYTEST_ARGS`
at runtime wins over any eval-time fallback, and `"$@"` is appended, so
both forms compose.

- `pyjj-bindings/tests/` tests the native module directly (`import pyjj_bindings`)
  and stays mechanical: type construction, exception hierarchy/constructibility,
  equality/hash semantics. It should stay fast and not need real jj repos.
- `pyjj/tests/` tests the pythonic wrapper (`import pyjj`) and owns the real
  workflow coverage: init/load, transactions, commit building, error paths.
  Fixtures in `pyjj/tests/conftest.py` build fresh workspaces per test via
  `tmp_path`.
- Exception taxonomy: specific subclasses (`WorkspaceInitError`,
  `WorkspaceLoadError`, `BackendError`, `TransactionError`, `RepoLoadError`)
  are raised where the call site clearly maps to one. Argument-validation
  errors with no dedicated category (bad hex in `CommitId`/etc., unknown
  `set_sign_behavior` string) raise the generic `JjError`.

## jj CLI parity coverage

Every command the pinned `jj` (0.43) offers has a scenario in
`pyjj/tests/parity/test_parity.py`. A command pyjj-cli does not implement
yet still has one, marked `UNIMPLEMENTED` (a **strict** xfail): the day
the command lands, its scenario stops being an expected failure and the
run goes red until the marker is removed. So the matrix is executable --
`nix run --file . tests -- -k parity` is the check, not this table.

What parity proves depends on the command:

- a command that **writes** is proved bit-identical: same change ids,
  commit ids, bookmarks, tags, working-copy names and file contents;
- a command that only **reads** is proved to exit 0 on both sides and to
  leave the repository untouched -- which still catches a renderer that
  crashes or snapshots differently on its way to printing. Output text is
  never compared; the two tools format differently on purpose.

Three kinds of state sit outside a commit id and are compared explicitly:
bookmarks and tags (extracted per commit by the harness), workspace names
(likewise), and git refs (`git_refs()` reads both sides with read-only
git against the path `jj git root` reports -- `git export`/`import` move
nothing else).

Deliberately excluded, with the reason:

| Excluded | Why |
| --- | --- |
| `arrange` | an interactive TUI; there is no argv to run on both sides |
| `gerrit` | needs a Gerrit server |
| `sparse edit`, `config edit` | open the editor on both sides |
| `bench`, `debug` | hidden developer commands, not part of the CLI surface |
| `hunk`, `templates` | pyjj-cli's own commands; `jj` has no such subcommand, so there is no other side to compare against. Covered by unit tests instead |
| `op integrate` | needs an operation created concurrently elsewhere; the harness runs one operation at a time |
| `workspace update-stale` | has to run inside the stale workspace, and `op()` runs with the primary repo as cwd and prepends its own `-R`, which jj rejects a second one of |
| `tag track`, `tag untrack` | pyjj-cli has them; jj 0.43 does not |

When adding a command or a flag, add its scenario in the same commit.
Two traps the suite has already caught, worth knowing before you write
one:

- **The same argv runs on both sides.** A flag missing from pyjj-cli's
  parser fails the scenario outright, which is the point -- pyjj-cli has
  to speak jj's argument dialect, not a dialect of its own.
- **Anything that names an operation names it per side.** Operation ids
  differ between the two repos, so use `RepoPair.op_id(side, depth)` and
  pass a different value to `jj=` and `py=`.
- **A merge's parent order is part of its commit id.** The extracted
  state sorts parents, so a scenario that builds a merge the wrong way
  round shows up only as a differing commit id, with every other field
  identical. That shape of diff -- one changed hash and nothing else --
  almost always means parent order, not content.

## API coverage

Goal is to eventually expose "practically everything" the `jj` CLI can do.
Current state:

- **Revsets**: `ReadonlyRepo.revset(settings, "expr")` and `.resolve_single(...)`
  parse and evaluate the full built-in revset language (`@`, `ancestors()`,
  id prefixes, etc.) against the repo's default workspace, plus
  `revset-aliases`/`fileset-aliases` from `settings`'s config -- including
  jj's bundled `trunk()`/`immutable_heads()`/`mutable()`/`visible()`/
  `hidden()`/etc. when `settings` was built with `load_config=True` (the
  default; see **Config** below).
- **Log graph**: `ReadonlyRepo.log_graph(settings, "expr", limit=None) ->
  list[GraphNode]` is like `revset()` but structured for rendering a graph
  (e.g. `jj log`'s) instead of a flat list — each `GraphNode` has `.commit`
  and `.edges` (`list[GraphEdge]`, each with `.target: CommitId` and
  `.edge_type`: `"direct"` (an actual parent present in the revset's
  result), `"indirect"` (nearest *visible* ancestor, when one or more
  intermediate commits were filtered out of the revset — the line-skips-
  past-elided-commits behavior `jj log` itself draws), or `"missing"` (an
  ancestor entirely outside the revset's domain, e.g. a range boundary or
  shallow-history edge). Rows come out topologically grouped
  (`jj_lib::graph::TopoGroupedGraph` wrapping `Revset::stream_graph()`, the
  same primitives `cli/src/commands/log.rs` itself is built on — children
  before parents, with a branch's commits kept contiguous rather than
  interleaving with unrelated branches). No ASCII-art rendering is included
  — jj's own graph glyph layout lives behind an external Rust-only crate
  (`renderdag`) the CLI uses; a caller wanting to *draw* the graph does its
  own lane/column layout from this edge data (well-understood technique,
  same one most git TUIs use).
- **Evolution**: `ReadonlyRepo.evolution_log(start_commits, limit=None) ->
  list[EvolutionEntry]` is `jj evolog`'s history
  (`jj_lib::evolution::walk_predecessors`): every earlier version of a
  change, newest first. Each `EvolutionEntry` has `.commit`, `.operation`
  (the operation that created or rewrote it, `None` once that operation
  has left the op log) and `.predecessor_ids` (empty for the first
  version, several where versions were squashed together).

  It walks the *operation* log rather than the commit graph, so it finds
  versions that are hidden and no longer reachable in any revset. Unlike
  the graph and bisect wrappers there is no lifetime to work around --
  `walk_predecessors` streams owned entries, drained inside the call.
- **Bisect**: `Bisector(repo, settings, ["v1.0..main", ...])` is
  `jj bisect`'s binary search (`jj_lib::bisect`). Call `next_step()` for a
  `BisectStep` -- `kind` `"evaluate"` (test `.commit`) or `"done"`
  (`.result` is `"found"` with `.commits`, `"indeterminate"`, or
  `"abort"`) -- then report the outcome with `mark(id, "good"|"bad"|
  "skip"|"abort")`. `remaining_count()` gives the `(lower, upper)`
  estimate `jj` turns into its "N revisions left to test" line, and the
  static `Bisector.invert(evaluation)` is what `--find-good` applies.
  The range's heads are assumed bad and seeded at construction; only an
  empty bad set yields `"indeterminate"`, so skipping every candidate
  still reports the seeded head.

  `jj_lib`'s `Bisector<'repo>` borrows the repo, and a `#[pyclass]` cannot
  hold a borrow, so this wrapper stores the search *state* (the input
  range plus the three id sets) and rebuilds a real `Bisector` inside each
  call. The borrow never escapes the call and everything stored is
  `Send + Sync`, so a plain `#[pyclass]` suffices and `_async` siblings
  remain possible if a caller ever wants them. Replay order is bad, good,
  skipped: `Bisector::new` seeds `bad` from the range's heads, so the
  stored set is always a superset of the seed, and `mark_bad` asserts only
  against the two still-empty sets. `mark()` rejects a conflicting id
  before storing it, because jj_lib's `assert!`s stay live in release
  builds and would surface as `PanicException` rather than a catchable
  error.
- **Config**: `UserSettings()` loads jj's real config by default (system,
  user, `revset-aliases`, env var overrides -- see the module docs on
  `pyjj_bindings::config` in `pyjj-bindings/src/config.rs` for the exact
  precedence order and file locations, which mirror `jj`'s own). Pass
  `UserSettings(load_config=False)` to get only `jj_lib`'s bare built-in
  defaults instead (empty user name/email, no revset aliases) --
  `pyjj/tests/conftest.py`'s `settings` fixture does this, so tests stay
  hermetic regardless of the machine's real jj config. Repo-level
  (`.jj/repo/`) and workspace-level (`.jj/<workspace>/`) config are **not**
  loaded -- deliberately: real jj gates those behind an ID-indirection
  scheme (`jj_lib::secure_config`) specifically so a cloned repo can't make
  its own config (merge-tool commands, aliases) take effect without the
  user opting in, and reimplementing that casually would be a real
  security regression, not just a missing feature.
  `UserSettings.get_string(key) -> str | None` reads an arbitrary dotted
  config key (`"revsets.log"`, `"ui.default-command"`, ...) as a string —
  `None` if unset anywhere in the loaded layers (including built-in
  defaults), raises `JjError` if it's set but not a string (e.g. a table).
  One generic accessor rather than per-key getters, matching how `jj`
  itself reads arbitrary config via `StackedConfig::get`.
- **Bookmarks**: `ReadonlyRepo.bookmarks()`/`.get_bookmark()` (read),
  `Transaction.set_bookmark()`/`.delete_bookmark()`/`.get_bookmark()`/
  `.bookmarks()` (mutate). Local bookmarks only — no remote-tracking-bookmark
  read/write surface yet. `Transaction.rebase_descendants()` automatically
  moves a bookmark pointing at a *rewritten* commit to its new successor.
  For *abandoned* commits, bookmarks move to the abandoned commit's parent
  by default — but that is jj_lib's default (`RewriteRefsOptions::
  delete_abandoned_bookmarks = false`), **not** what the real CLI's
  `jj abandon` does: it deletes such bookmarks unless `--retain-bookmarks`
  is passed. To match the CLI, call
  `rebase_descendants(delete_abandoned_bookmarks=True)`. Found by the
  parity suite (`pyjj/tests/parity`) — the old "same as real `jj abandon`"
  claim here was wrong.
- **Tags**: same shape as bookmarks — `ReadonlyRepo.tags()`/`.get_tag()`
  (read), `Transaction.set_tag()`/`.delete_tag()`/`.get_tag()`/`.tags()`
  (mutate) — a separate namespace from bookmarks, backed by the same
  `jj_lib::op_store::RefTarget`/`RefName` machinery
  (`MutableRepo::set_local_tag_target`/`get_local_tag`,
  `View::local_tags()`). Real `jj` itself only exposes tags read-only
  (`jj tag list`, populated by `git_import_refs()` from actual Git tags) —
  this binding additionally exposes the write side since it's a public,
  unrestricted `jj_lib` primitive, matching the "expose practically
  everything `jj_lib` can do" goal even where the CLI is more conservative.
- **Working copy**: `Workspace.snapshot(settings)` reads on-disk file state
  into the wc commit's tree and commits that as a new operation (a no-op,
  no new commit/operation, if nothing changed — matches `jj status`'s
  implicit snapshot). `Workspace.check_out(repo, commit)` writes a commit's
  tree out to the working-copy files. `Workspace.reset(repo, commit)` is
  the other, much rarer half of that pair: it re-syncs the working copy's
  tracked-file-state bookkeeping (recorded mtimes/hashes) to `commit`'s
  tree *without writing a single file to disk*, wrapping
  `LockedWorkingCopy::reset` — for when files on disk already match
  `commit` because something outside jj put them there (the CLI's own use
  case, `WorkspaceCommandHelper::import_git_head`: a colocated repo's `git`
  command moved Git HEAD and rewrote the files directly, so jj just needs
  to stop considering its recorded state stale). It doesn't touch the repo
  view's working-copy-commit pointer at all — pair it with
  `Transaction.edit()`/`.set_wc_commit()` yourself if that also needs to
  move. Per-directory `.gitignore` files on
  disk *are* consulted when deciding whether to track a new file (matches
  `jj status`/`jj diff`) — `checkout.rs`'s `snapshot()` passes
  `NothingMatcher` as `SnapshotOptions::force_tracking_matcher`; passing
  `EverythingMatcher` there (the previous, incorrect default) force-tracks
  every gitignored file regardless of `.gitignore`, since per jj_lib's own
  docs that matcher means "track anyway even if ignored." No
  `snapshot.auto-track` pattern support, and `.git/info/exclude`/global
  `core.excludesFile` still aren't consulted (only real per-directory
  `.gitignore` plus the working copy's own always-ignored paths like
  `.jj/`). A nested `.git` file or directory anywhere in the working copy
  is *always* skipped on snapshot, independent of `.gitignore` (guards
  against accidentally tracking a nested repo's own git metadata).
  `check_out()` also has real filesystem-safety limits worth knowing:
  writing a path is skipped (not an error, just `skipped_files` in the
  stats) rather than followed through an existing symlinked parent
  directory that would otherwise let a tracked path escape the workspace
  root, and it's likewise skipped (not failed) if the target path was
  externally replaced with a real directory on disk.
  `snapshot.max-new-file-size` *is* read from `settings` (via
  `jj_lib::settings::HumanByteSize`, same as the CLI's own
  `WorkspaceCommandHelper::snapshot_options`, including its `0` ->
  "unlimited" convention) — this used to be a hardcoded constant that
  happened to match jj's built-in default (`"1MiB"`), silently ignoring
  any user override. `working-copy.eol-conversion` (`"none"` (default) /
  `"input"` / `"input-output"`) is also honored transparently — it's read
  from whatever `UserSettings` the `Workspace` was `init`ed/`load`ed with
  (`TreeStateSettings::try_from_user_settings`, baked into the working
  copy at that point), not something `snapshot()`/`check_out()` need to
  pass separately. `"input"` normalizes CRLF/mixed line endings to LF
  going into the store but leaves the working copy alone on checkout;
  `"input-output"` additionally restores the original CRLF on checkout;
  `"none"` round-trips whatever bytes are on disk untouched. Binary files
  (a NUL byte anywhere) are never converted regardless of mode.
- **Diffing**: `Commit.diff(other, paths=None)` / `.diff_with_copies(other,
  paths=None)` return a list of `DiffEntry` (`path`, `status`, `executable`,
  plus copy info from the `_with_copies` variant). `paths`, if given, restricts
  results the same way `jj diff <path>...`/`jj squash <path>...` do — each
  string is either an exact file path or a directory prefix (everything
  under it matches too), via `jj_lib::matchers::PrefixMatcher` (shared with
  `squash`/`split`'s existing path-filter parameter through
  `rewrite.rs`'s `paths_matcher` helper — a real, previously-existing bug
  there, since it used `FilesMatcher`, exact-file-only, silently making any
  directory argument match nothing). `status` is `"executable"` (not
  `"modified"`) when a file's content is unchanged but its executable bit
  flipped.
- **Listing files**: `Commit.list_files(paths=None) -> list[str]` is `jj file
  list [paths]` — every path in the tree (files, symlinks, Git submodules;
  not directories, which aren't separate tree entries), via
  `MergedTree::entries_matching`, restricted by the same `paths_matcher`
  path-or-subtree rules as `diff()`/`squash()`. Conflicted paths are still
  listed (matching real `jj file list`) — check a specific path's
  resolution via `read_file()`/`is_executable()` if needed.
- **Symlinks and file/directory transitions**: handled transparently by the
  same `jj_lib` working-copy code every other operation here goes through —
  `read_file()` on a symlink returns its target as bytes (matching
  `TreeValue::Symlink`'s own representation), and `Workspace.check_out()`
  correctly replaces a file with a directory (or vice versa) on disk when
  the target commit's tree requires it. No pyjj-specific code was needed
  for either; they're tested (`test_file.py`, `test_checkout.py`) mainly to
  confirm the binding layer doesn't get in the way.
- **Executable bit**: `Commit.is_executable(path) -> bool | None` (`None` for
  a nonexistent path or a directory). `Transaction.set_executable(commit,
  path, executable) -> CommitBuilder` flips the bit without touching
  content, built on `jj_lib::merged_tree_builder::MergedTreeBuilder`; raises
  `JjError` if `path` isn't a resolvable regular file (doesn't exist, is a
  directory, or is genuinely conflicted). The bit round-trips through the
  real filesystem too, not just tree metadata: `Workspace.snapshot()` picks
  up a `chmod` done directly on disk (outside `set_executable()`), and
  `Workspace.check_out()` writes the tree's executable bit back out to the
  file's real Unix permissions.
- **Duplicate**: `Transaction.duplicate(commits) -> list[Commit]` is plain
  `jj duplicate` (no explicit destination) — wraps
  `jj_lib::rewrite::duplicate_commits_onto_parents`, duplicating each commit
  onto its own original parents.
- **Restore**: `Transaction.restore(from_commit, into_commit, paths=None) ->
  CommitBuilder` is `jj restore [paths] --from <src> --into <dest>` —
  overwrites `paths` (or everything) in `into_commit`'s tree with
  `from_commit`'s content at those paths, leaving `from_commit` itself
  untouched. Wraps `jj_lib::rewrite::restore_tree`, the same primitive
  `squash`/`split` use internally for path selection — but unlike `squash`,
  `into_commit` need not be a descendant of `from_commit` at all; there's no
  ancestry requirement.
- **Edit / advance the working copy**: `Transaction.edit(workspace_name,
  commit)` is `jj new <rev>`/`jj edit <rev>`'s core semantic — wraps
  `MutableRepo::edit` directly. Prefer it over the lower-level
  `set_wc_commit(workspace_name, commit_id)` (which just repoints the wc,
  full stop): `edit()` additionally abandons the commit the workspace was
  previously pointing at, but *only* if it's discardable (empty + no
  description), unreferenced by any bookmark/tag/other workspace, and
  *still a head* at the moment of the call. That head-check is exactly why
  the everyday "advance to a child of the current wc" `jj new` doesn't
  delete anything — writing the child already makes the old wc non-head
  (it now has a visible child) before the check runs. The abandon only
  actually fires for `jj new <unrelated-rev>`/`jj edit <sibling>`-style
  jumps that leave the old wc an orphaned empty head — mirrors
  `lib/tests/test_mut_repo.rs`'s `test_edit_previous_empty`/
  `test_edit_previous_not_empty`. When it does fire, `rebase_descendants()`
  is still required before `commit()`, same as any other operation that
  populates `parent_mapping`, even though the abandoned commit itself has
  no descendants to rebase.
- **Abandon**: `Transaction.abandon_commit(commit)` is `jj abandon <rev>` —
  wraps `MutableRepo::record_abandoned_commit` directly. Removes the commit
  from history; descendants (including a wc commit pointing at it) get
  rebased onto its own parents, but only once `rebase_descendants()` is
  called afterward, same convention as every other rewrite here. The
  commit's data isn't deleted from the backend and stays resolvable by
  direct id — it's just no longer an ancestor of any visible head, matching
  real jj's "hidden, not deleted" semantics.
- **Rebase**: two levels of primitive, matching the two things `jj rebase`
  itself can do.
  - `Transaction.rebase(commit, new_parents) -> Commit` wraps
    `jj_lib::rewrite::rebase_commit` directly for a *single* commit (no
    `CommitBuilder` step, unlike `set_executable`). Beware: this primitive
    + `rebase_descendants()` does **not** reproduce `jj rebase -r <rev>
    -d <dest>` — real `-r` treats the moved commit's old slot as
    abandoned, grafting its descendants onto its *original* parents, while
    rebase_descendants() drags them along into the new location (a real
    divergence the parity suite caught). For CLI-equivalent `-r`/`-s`
    semantics use `move_commits()` below, like the CLI itself does.
  - `Transaction.move_commits(target_commit_ids, target_root_ids,
    new_parent_ids, new_child_ids) -> MoveCommitsStats` wraps the full
    `jj_lib::rewrite::move_commits`/`compute_move_commits` machinery the
    CLI's own `jj rebase` composes every one of its modes from
    (`cli/src/commands/rebase.rs`) — covers `-r`/`-s` (via exactly one of
    `target_commit_ids`/`target_root_ids` being non-empty; the other must
    be empty, checked and rejected with `JjError` otherwise) and
    `-d`/`-A`/`-B` (via `new_parent_ids`/`new_child_ids` — empty
    `new_child_ids` is a plain `-d`; non-empty splices the moved commits in
    as parents of those children too, `-A`/`-B`). Binds
    `RebaseOptions::default()` only (same defaults `jj rebase` uses without
    `--skip-emptied`) — no exposed way to change `EmptyBehavior` or
    `simplify_ancestor_merge` yet. Computing which ids `-A`/`-B` imply
    (children-of-destination, or destination's-own-original-parents) is
    the caller's job (see `pyjjui/src/pyjjui/mutations.py`'s `rebase()`),
    not this binding's — same split as `cli_util::compute_commit_location`
    vs `move_commits` itself in the real CLI.
- **Annotate (blame)**: `Commit.annotate(repo, path) -> list[AnnotationLine]`
  is `jj file annotate <path>` — wraps `jj_lib::annotate::FileAnnotator`,
  searching the whole repo as the domain (matching the CLI's own current
  default; see its TODO in `cli/src/commands/file/annotate.rs` about
  narrowing it). Each `AnnotationLine` has `commit_id`, `line` (bytes,
  including the trailing newline), and `is_boundary` (`True` only if the
  search ran off the edge of history before finding a definite originator —
  in practice just shallow/truncated history, same as the CLI's own
  boundary marker).
- **Absorb**: `Transaction.absorb(settings, source_commit,
  destinations=None, paths=None) -> AbsorbStats` is `jj absorb` — splits
  `source_commit`'s changes and moves each hunk into the closest ancestor
  (among `destinations`, a revset expression defaulting to `"mutable()"`
  like the CLI — needs `UserSettings(load_config=True)`, the default, since
  that's one of jj's bundled `revsets.toml` aliases) where those lines were
  last modified, using the same file-annotation machinery
  `Commit.annotate()` is built on (`jj_lib::absorb::{AbsorbSource,
  split_hunks_to_trees, absorb_hunks}`). `source_commit` is abandoned if
  every hunk absorbed away and it has no description (`AbsorbStats.source`
  is then `None`); otherwise `.source` is the rewritten (now-diffless, if
  fully absorbed) source, and `.destinations` are the rewritten ancestors
  hunks moved into, in forward topological order. `rebase_descendants()`
  is still required afterward before `commit()`, same as every other
  rewrite here — verified empirically that omitting it panics, even though
  `MutableRepo::transform_descendants` (which this wraps) already rebases
  the specific commits it visits internally; it still leaves a
  pending-rewrite record `Transaction::commit()` asserts must be cleared.
- **Fix**: `jj fix` (`jj_lib::fix`) is exposed as two `Transaction` calls
  instead of a Python-callback-into-Rust-trait bridge:
  `fix_enumerate(settings, revset=None, paths=None) -> list[FileToFix]`
  resolves `revset` (default `"reachable(@, mutable())"`, jj's own
  `revsets.fix` default) and its descendants and returns the deduplicated,
  descendant-propagated `(path, content)` pairs that might need fixing
  (`FileToFix.key`/`.path`/`.content`), changing nothing; then
  `fix_apply(settings, fixes, revset=None, paths=None) -> FixSummary` takes
  a `{FileToFix.key: new_content}` mapping (Python computes it however it
  wants — `subprocess`-ing a formatter, a pure-Python transform — same as
  the CLI's own `ParallelFileFixer` shells out to external tools in
  `cli/src/commands/fix.rs`, just done in Python instead of Rust) and does
  the actual multi-commit rewrite, propagating each fix to descendants that
  didn't touch that file so it isn't lost (`FixSummary.num_checked_commits`,
  `.num_fixed_commits`, `.rewrites` — old commit id -> new). A file whose
  key is missing from `fixes` is left unchanged. `rebase_descendants()` is
  still required before `commit()`, same as every other rewrite here. This
  two-call, data-in/data-out split — not a callback — is the same idiom
  `diff_hunks()` + `squash(hunks=...)`/`split_selected(hunks=...)` already
  use for interactive hunk selection, and `Commit.materialize_conflict()` +
  `Transaction.resolve_conflict()` use for external merge tools: none of
  jj's external-tool-invoking commands (`jj fix`, `jj resolve`, `jj
  diffedit`/`split -i`/`squash -i`) actually need a jj_lib-level trait
  satisfied by calling back into Python — `cli/src/merge_tools/*`'s
  merge/diff-editor invocation is pure `cli`-crate subprocess orchestration
  on top of already-bound `jj_lib` primitives, and even `jj fix`'s
  `FileFixer` trait (the one case that does exist as a real `jj_lib`
  trait) is satisfiable with a plain Rust closure over precomputed data, as
  `RecordingFixer`/`LookupFixer` in `pyjj-bindings/src/fix.rs` do.
- **Shortest unique id prefix**: `ReadonlyRepo.shortest_commit_id_prefix_len(
  commit_id, settings=None) -> int` /
  `.shortest_change_id_prefix_len(change_id, settings=None) -> int` are the
  "shortest unique prefix" `jj log` highlights, via
  `jj_lib::id_prefix::IdPrefixIndex`.

  With no `settings` they disambiguate against every commit in the repo.
  Pass `settings` and they narrow the way `jj` does: `revsets.short-prefixes`
  becomes the set ids are shortened within, falling back to `revsets.log`
  when it is unset, and an empty string for either turns narrowing off. A
  small working set therefore gets short ids even in a large repo -- in a
  60-commit repo with `short-prefixes = "@"`, the working copy needs one
  character instead of two. `pyjj log` passes its settings, so its
  highlighting matches `jj log`'s.

  Both paths go through `IdPrefixIndex`, which also widens a prefix past
  anything a bookmark or tag name would shadow -- an earlier version called
  the bare `Index::shortest_unique_*_prefix_len` and skipped that step, so
  it could return a prefix that no longer resolved to the commit.

  `IdPrefixIndex<'_>` borrows the context that produced it, so the context
  is built and populated inside each call rather than cached on the
  pyclass -- the same shape the `Bisect` entry above describes.
- **Signing**: `CommitBuilder.set_sign_behavior("drop" | "keep" | "own" |
  "force")` and `Commit.is_signed -> bool`/`Commit.verification ->
  Verification | None` wrap `jj_lib`'s signing directly
  — no bespoke pyjj plumbing, since `Signer::from_settings` (called once,
  internally, when a `Workspace`/`ReadonlyRepo` is loaded) already reads the
  real `signing.backend`/`signing.key`/`signing.backends.*` config the same
  way the `jj` CLI does. Real backends (`gpg`, `gpgsm`, `ssh`) all work
  as-is; there's no `key` argument on `set_sign_behavior` because the
  signing key itself comes from `signing.key` config, not a per-call
  parameter. jj's own CLI integration tests use a fake `signing.backend =
  "test"` (`jj_lib::test_signing_backend::TestSigningBackend`) — that's
  gated behind jj-lib's `testing` Cargo feature (see `lib/Cargo.toml`'s
  `testing = ["git"]` and the `#[cfg(feature = "testing")]` arm in
  `lib/src/signing.rs`'s `Signer::from_settings`), which pyjj-bindings
  doesn't enable, so it's not reachable from a real pyjj build —
  `pyjj/tests/test_signing.py` tests against the real `ssh` backend instead
  (a throwaway `ssh-keygen`-generated key), which needs no GPG installed.
  `is_signed` is just "is a signature present" — `verification` actually
  invokes the backend to check it (cached after the first call) and
  returns `None` if unsigned, or a `Verification` with `.status` (`"good"`
  | `"unknown"` | `"bad"`) and backend-provided `.key`/`.display` (may be
  `None`) otherwise.
- **Commit author/committer timestamps on rewrite**: mirrors
  `jj_lib`'s own `CommitBuilder::for_rewrite_from` exactly —
  `Transaction.rewrite_commit()` always bumps the *committer* timestamp to
  "now" (from whichever settings the repo was loaded with), but only
  bumps the *author* timestamp too if the predecessor commit was
  "discardable" (empty diff from its parent, no description) *and*
  author == committer identity. This is `jj describe`'s real behavior:
  the first time you touch a still-blank commit (e.g. an untouched `@`),
  both timestamps advance together; once it has a description, further
  amends only move the committer timestamp forward, leaving the original
  author timestamp frozen. Gotcha: the `settings` argument accepted by
  `start_transaction()`/`new_commit()`/`rewrite_commit()` does **not**
  control this (or any other signature field) — `jj_lib`'s
  `MutableRepo::rewrite_commit` reads `self.base_repo.settings()`, fixed
  at whatever point the `ReadonlyRepo`/`Workspace` was loaded, and ignores
  whatever's passed to those calls. To change the effective
  author/committer identity or `debug.commit-timestamp` mid-session,
  reload with `Workspace.load(new_settings, path)` + `.load_at_head()`
  rather than just passing different settings into `start_transaction()`.
- **`Timestamp`/`Signature` equality**: both are `frozen` pyclasses with
  `__eq__`/`__hash__` (delegating to `jj_lib`'s own `PartialEq`/`Hash`
  derives), matching `CommitId`/`ChangeId`/`TreeId`/`FileId` — needed
  fixing; they were previously compared by Python object identity only,
  so two separately-constructed `Timestamp`s/`Signature`s with identical
  field values compared unequal.
- **Sparse patterns**: `Workspace.sparse_patterns() -> list[str]` (`jj
  sparse list`) and `.set_sparse_patterns(patterns) -> dict` (`jj sparse
  set --clear --add ...`, or `jj sparse reset` for `[""]`) wrap
  `LockedWorkingCopy::sparse_patterns`/`set_sparse_patterns` directly —
  purely workspace-local on-disk state, so unlike everything else in this
  section it doesn't touch the repo's view or create a new jj operation
  (matches real `jj sparse set`, which reuses the current operation id).
  `[""]` (a single empty-string pattern) means "the whole repo," the
  default; each other entry is a directory-prefix path string. No
  `--edit`-style interactive pattern editor (that's inherently a `cli`/TUI
  concern, like the interactive hunk-picker noted under **Squash/split**).
- **Multiple workspaces**: `Workspace.add_workspace(settings,
  destination_path, name=None, revision_ids=None) -> (Workspace, ReadonlyRepo)`
  is `jj workspace add` — creates an independent working-copy directory
  backed by the same repo storage, with its own initial wc commit (parented
  on `revision_ids` if given, else on the *invoking* workspace's own wc
  commit's parents — same default `jj workspace add` uses).
  `Workspace.forget_workspaces(settings, names) -> ReadonlyRepo` is `jj
  workspace forget` — stops tracking the named workspaces' wc commits
  (bundling all of them into one operation, so undo restores them
  together); doesn't touch anything on disk. `Workspace.rename_workspace(
  settings, new_name) -> ReadonlyRepo` is `jj workspace rename` — renames
  *this* `Workspace` object's own workspace (both the repo view and the
  on-disk working-copy state), a no-op if `new_name` already matches.
  `Workspace.workspace_path(name)` looks up any workspace's on-disk
  location (relative to `repo_path`) via `jj_lib::workspace_store`, or
  `None` if unrecorded. `ReadonlyRepo.view()`'s dict (workspace name ->
  wc commit hex) already doubles as `jj workspace list`'s core data — no
  separate listing call needed. No sparse-pattern inheritance control
  (`add_workspace` always gets a full, non-sparse checkout, unlike the
  CLI's `--sparse-patterns` copy/full/empty choice).

  Building this required fixing the same class of gap the conflict-resolution
  feature hit: `add_workspace`/`forget_workspaces` both call `jj_lib`
  operations (`MutableRepo::edit`/`remove_wc_commit`) that can abandon a
  now-unreferenced wc commit — a rewrite — which needs
  `rebase_descendants()` called before `Transaction::commit` even when
  there's nothing to actually rebase (`Transaction::commit` asserts no
  pending rewrites remain; `checkout::snapshot` already had this same
  requirement).
- **Stale working-copy recovery**: `Workspace.update_stale(repo) ->
  dict | None` is `jj workspace update-stale` — pass a freshly-loaded
  `ReadonlyRepo` (e.g. from `load_at_head()`); wraps
  `WorkingCopyFreshness::check_stale` to detect whether this workspace's
  on-disk state is stale relative to `repo`'s view (recorded operation id
  is behind *and* the physical tree actually differs from the target —
  matching a target commit's tree by content, even with a stale operation
  id, correctly counts as "fresh," same as real jj) and, if so, resets the
  working copy to `repo`'s wc commit, returning `check_out()`-shaped stats;
  `None` if nothing needed doing. Deliberately a **simpler subset** of the
  real CLI command: unlike `cli`'s `recover_stale_working_copy`, this does
  *not* snapshot and preserve any uncommitted edits sitting in the stale
  working copy before resetting — callers who need that should snapshot
  against the old operation themselves first (e.g. via a `Workspace`
  loaded at the stale op).
- **Git (colocated + remote)**: `Transaction.git_import_refs()` /
  `.git_export_refs()` wrap `jj_lib::git::{import_refs, export_refs}` with
  jj's own built-in defaults (`abandon_unreachable_commits`/
  `record_synthetic_predecessors` = true, matching
  `lib/src/config/misc.toml`). `Transaction.git_fetch(settings, remote,
  bookmark_names)` fetches specific named bookmarks (no tags);
  `.git_fetch_all(settings, remote)` fetches *every* branch and tag and
  additionally reports `default_branch` (`Optional[str]`, from `git remote
  show`) in its stats dict — the fetch step behind `clone_git()` below.
  Both / `.git_push_bookmark(settings, remote, bookmark)` run real `git
  fetch`/`git push` **subprocesses** (not in-process gix transport), so
  they transparently reuse the system's normal Git authentication (SSH
  agent, credential helpers, `~/.netrc`, etc.) — no custom auth plumbing
  needed. `.git_add_remote()`/`.git_remove_remote()`/`.git_remotes()`
  manage remotes; `.git_rename_remote(old, new)` is `jj git remote rename`
  (also updates every remote-tracking bookmark/tag/Git ref that referred to
  the old name); `.git_set_remote_urls(name, url=None, push_url=None)` is
  `jj git remote set-url` — passing neither argument is a documented no-op,
  not an error, and there's no way to *unset* just one URL this way (same
  contract as `jj_lib::git::set_remote_urls` itself).
  `.git_track_remote_bookmark()`/
  `.git_untrack_remote_bookmark()` control whether a fetched remote
  bookmark merges into the local one of the same name (push uses the
  tracked target as the expected remote position — track before pushing to
  an already-populated remote, or the push may be rejected as
  non-fast-forward). No progress reporting hooked up
  (`GitSubprocessCallback` is a silent no-op).

  `Workspace.clone_git(settings, url, destination_path, remote_name=
  "origin", colocate=True) -> (Workspace, ReadonlyRepo)` is `jj git clone`:
  initializes a workspace, adds the remote, fetches everything via
  `git_fetch_all`, and — if the remote reports a default branch — tracks
  it as a local bookmark and checks it out (via `MutableRepo::check_out`,
  which creates a fresh empty *child* commit on top of the branch, same as
  `jj new <branch>`, not a direct `edit` onto the branch's own commit —
  editing straight onto it would let working-copy edits silently move the
  bookmark). No URL-based destination-directory auto-detection, no
  `--branch`/`--tag`/`--depth`/`--object-hash` filtering — always fetches
  everything, unlike the CLI's more configurable defaults.

  **Caveat**: the Git backend's config (including remotes) is cached for
  the lifetime of a `Workspace` object — matches the real CLI, which is a
  fresh process per command, so this never comes up there. A **long-lived**
  process (like a Python script issuing several transactions) that calls
  `git_add_remote()`/`git_remove_remote()` won't see the change reflected
  in `git_remotes()` on the *same* `Workspace`, even after
  `Workspace.load_at_head()` — you need a fresh `Workspace.load(settings,
  path)` to pick it up. `clone_git()` hits this internally too (its own
  `add_remote` and `fetch_all` steps are two different `Workspace`
  objects, with an explicit reload between them, mirroring `cli`'s own
  `git clone` command) — found via a probe script actually failing with
  "No git remote named 'origin'" before the reload was added, not by
  inspection.
- **Operation log**: `ReadonlyRepo.operation` (current op), `.operation_log()`
  (full ancestor walk via `jj_lib::op_walk::walk_ancestors`, newest first --
  same order as `jj op log`), `.load_operation(op_id_hex)` (load an
  arbitrary past operation by id). `ReadonlyRepo.load_at_operation(op) ->
  ReadonlyRepo` is `jj --at-op=<id>` -- loads a full, independent read-only
  repo view as it was at `op` (`jj_lib::repo::RepoLoader::load_at`), purely
  for historical inspection; doesn't affect the repo it was called on or
  touch any workspace's actual current operation. `Transaction.restore_operation(target_op,
  what=None)` is `jj op restore` -- makes the view match `target_op` (or a
  blend of it and the current view, via `what: ["repo", "remote_tracking"]`,
  default both); doesn't commit on its own.
  `Transaction.undo()`/`.redo()` are `jj undo`/`jj redo` -- built on the same
  view-restore primitive, but each walks jj's own undo/redo-stack-jumping
  rules (mirrors `cli/src/commands/undo.rs`/`redo.rs`) so repeated calls
  behave like repeated `jj undo`/`jj redo` (going further back/forward each
  time) instead of toggling between two states. Both return `(undone_op,
  restored_to_op, description)` -- pass `description` to `.commit()`
  unchanged, since it's not just a message: it embeds the target operation's
  id in the exact format future `undo()`/`redo()` calls look for to detect
  they're looking at a chained undo/redo, and a hand-written description
  would silently break that detection. `undo()` raises `JjError` on the
  root operation or a merge of concurrent operations (matching real jj,
  which also tells you to use `restore_operation`/`jj op restore` there) --
  note that the operation right after `Workspace.init_*` (`repo.operation`)
  is *not* the true 0-parent genesis operation, it's the "add workspace
  'default'" operation on top of it; `repo.operation_log()[-1]` (empty
  description) is the genuine root, and `load_at_operation()` is what makes
  it possible to actually construct and test that "undo at the very root"
  scenario at all.
- **Op abandon**: `Workspace.op_abandon(operation) -> OpAbandonStats` is `jj
  op abandon` -- prunes `operation` (or, with `"root..head"` syntax, either
  side omittable to mean the repo root / current head ops, a contiguous
  range) from the operation log, reparenting descendant operations onto the
  range's root (`jj_lib::op_walk::reparent_range`). Unlike
  `undo()`/`redo()`/`restore_operation()` (all `Transaction` methods that
  create a *new* operation), this edits the op log directly and takes no
  `Transaction`/`commit()` -- reload (`load_at_head()`) to see it.
  `OpAbandonStats` has `.abandoned_count`/`.rewritten_count`/`.changed`
  (`False` if the abandon was a no-op, matching the CLI's own "Nothing
  changed." case). Raises if `operation` resolves to (or its range
  includes) a current head operation, or (single-operation form) the root
  or a merge operation -- same restrictions the CLI enforces.
- **Diffs**: `Commit.diff(other)` returns path-level added/removed/modified
  entries; no copy/rename detection — a rename shows up as a "removed" +
  "added" pair at the two paths. `Commit.diff_with_copies(other)` is the
  copy/rename-aware equivalent: wraps `Store::get_copy_records` +
  `MergedTree::diff_stream_with_copies` (the same primitives `jj diff --git`
  and `jj log --summary` use) to report a single `"renamed"`/`"copied"`
  entry instead, with `DiffEntry.source_path` set to the old location.
  Detection is backend-dependent: the git backend does real
  content-similarity-based rewrite tracking via `gix` (50% similarity
  threshold, matching jj's own default), but only considers a path as a
  copy *source* if it was also modified in the same diff (`gix`'s
  `CopySource::FromSetOfModifiedFiles` — an unmodified copy source won't be
  detected); the in-memory/simple test backend never detects anything (its
  `get_copy_records` is a stub that always returns empty). No separate
  copy-aware hunk-selection primitive is needed on top of this — squash/split's
  `hunks={path: [...]}` selection already operates on whichever path you
  name directly, rename or not, same as real jj. `Commit.read_file(path)`
  reads a file's (or symlink's target's) content as `bytes`;
  `Commit.file_exists(path)` checks presence. Both raise `JjError` on
  unresolved conflicts -- use `materialize_conflict()` (below) for those.
- **Conflicts**: `Commit.materialize_conflict(settings, path) -> bytes`
  renders a conflicted file as conflict-marker text, exactly like a real jj
  working copy would show it (`ui.conflict-marker-style` from `settings`'s
  config controls the marker style, `"diff"` by default -- same as jj; all
  three styles jj supports, `"diff"`/`"snapshot"`/`"git"`, are honored and
  produce genuinely different marker text -- e.g. only `"git"` includes a
  `|||||||` base-content section).
  `Transaction.resolve_conflict(commit, path, content) -> CommitBuilder`
  applies edited text back: pass back fully-resolved content (no markers
  left) to resolve the path outright, or content with some markers still
  intact to partially resolve (any of jj's marker styles are accepted for
  parsing, not just whichever one was used to materialize) -- the marker
  length is re-derived from the conflict itself each time
  (`choose_materialized_conflict_marker_len`), so it's always consistent
  between a `materialize_conflict()` call and the `resolve_conflict()` call
  that follows it, with nothing to track on the Python side. Passing back
  the untouched output of `materialize_conflict()` is a no-op (still
  conflicted). Both raise `JjError` for paths that aren't file conflicts
  (not conflicted at all, or a non-file conflict like a file/directory
  conflict, which can't be materialized as text).
  Two additions back `jj resolve`'s external-merge-tool flow:
  `Commit.conflict_sides(path) -> {"base", "left", "right", "executable"}`
  exposes the raw remove/add contents exactly as `$base`/`$left`/`$right`
  in merge-args (rejecting non-file, >2-sided, and executable-bit
  conflicts — the same restrictions real `jj resolve` enforces), and
  `Transaction.resolve_conflicts(commit, {path: edited_text})` resolves
  every path in ONE tree rewrite (a single committer-timestamp bump
  regardless of path count, matching upstream's apply-all-then-
  set_tree-once shape; empty map still rewrites, since real jj records
  the attempt even when the tool changed nothing).

  The real `jj st`/`jj diff` editing workflow works transparently too, with
  no extra binding: `Workspace.check_out()` on a conflicted commit writes
  conflict-marker text straight to the working-copy file (same rendering
  `materialize_conflict()` produces), and `Workspace.snapshot()` parses
  hand-edited marker text back on the way in — fully resolving the path if
  the markers are gone, leaving it conflicted if the file is untouched or
  still has markers in it. This is `LocalWorkingCopy`'s own
  snapshot/checkout logic (`update_from_content`/materialize, the same
  primitives `resolve_conflict()`/`materialize_conflict()` wrap); no
  separate call is needed to keep disk and the tree in sync for
  conflicts, same as a real jj working copy.

  Building on this required fixing a real bug: `Transaction.new_commit()`
  with more than one parent was only using the *first* parent's tree,
  silently ignoring the rest, instead of actually merging them --
  `jj new a b` in real jj auto-merges and conflicts where the parents
  differ; this binding wasn't doing that at all. Fixed to use
  `jj_lib::rewrite::merge_commit_trees`, the same function real multi-
  parent commit creation uses (a no-op for the single-parent case, so this
  was a pure fix, not a behavior change for existing single-parent
  callers).
- **Squash/split**, both whole-file and hunk (line) granularity:
  `Transaction.squash(source, destination, paths=None, hunks=None,
  keep_emptied=False)` moves the named `paths` (whole files), the specific
  `hunks` (a `{path: [hunk_index, ...]}` map, indices from
  `pyjj.diff_hunks(before, after)`), or — if both are `None` — the source's
  entire change, into the destination. Returns a `CommitBuilder` for the
  rewritten destination, or `None` if the selection matches nothing to move
  (mirrors `jj squash` reporting "nothing to squash").
  `Transaction.split_selected(commit, paths=None, hunks=None)` builds the
  first half of a split the same way (original parents/change_id, tree
  restricted to the selection); `Transaction.split_remainder(commit,
  first)` builds the second half (child of `first`, full original tree,
  `generate_new_change_id()`'d — always whole-tree regardless of how
  `first` was selected, since it's defined as "everything not in `first`").
  As with every other mutation here, the caller is responsible for
  `rebase_descendants()` and `set_wc_commit()` afterward; nothing happens
  implicitly.

  `pyjj.diff_hunks(before, after) -> list[Hunk]` is a pure function (no
  repo access) that runs `jj_lib::diff::ContentDiff::by_line` on two byte
  buffers and returns each *changed* line-level region as a `Hunk(index,
  before, after)` — matching text is omitted, since it's not a selectable
  unit. To hunk-split/squash a path, read its content on both sides (e.g.
  `Commit.read_file(path)` on the commit and on its parent), call
  `diff_hunks(before, after)` to see what's selectable, then pass the
  indices you want back in as `hunks={path: [indices]}`. Internally, the
  hunks not selected are reconstructed from `before` and the ones selected
  from `after`, the result is written as a new file blob
  (`Store::write_file`), and it's set into the selected tree via
  `MergedTreeBuilder` before being handed to the same `jj_lib::rewrite`
   primitives the whole-file path uses.

   `pyjj.hunk` provides an AI-agent-friendly layer on top: `Spec`
   (`{"files": {path: {"hunks": [0,"hunk-..."],"ids":[...],"lines":[[1,5]]}}, "default": "reset"}`)
   mirrors `jj-hunk`'s DSL, validated via **pydantic** (`SpecModel`,
   `FileSpecModel`, `HunkObjectModel`). `lines: [[start,end]]` selects
   hunks overlapping 1-indexed `after` ranges; per-hunk
   `{"index":0,"lines":[0,2]}` selects lines within a hunk's `added`
   block (most common for splitting multi-line inserts). `get_hunks_detailed()`,
   `parse_spec()`, `apply_spec()`, `spec_to_overrides()` expose the
   data-in/data-out split; `pyjj hunk list/split/commit/squash` are the
   CLI wrappers (supporting `--spec`/`--spec-file`/`-` stdin and
   `yaml`).

   This whole feature — including hunk-level selection — is built entirely
   on public, CLI-independent `jj_lib` primitives (`jj_lib::rewrite::{
   restore_tree, CommitWithSelection, squash_commits}`,
   `jj_lib::diff::ContentDiff`, `MergedTreeBuilder`, `Store::write_file`).
   It does **not** reuse jj's own interactive hunk-picker UI
   (`edit_diff_builtin` in `cli/src/merge_tools/builtin.rs`, built on the
   `scm_record` TUI crate) — that lives entirely in the `cli` crate and is
   inherently an interactive-editor concern, not something `lib` exposes or
   something this library depends on. `pyjj.hunk` adds *line-level*
   filtering on top: `lines` ranges are resolved against `after` line
   numbers, per-hunk `lines` are filtered from the hunk's `added`/`removed`
   blocks before reconstruction. (A different, complementary approach
   exists too: `jj-hunk` (github.com/laulauland/jj-hunk) drives the real
   `jj` CLI as a subprocess and registers itself as jj's external
   `merge-tools` diff-editor to answer `jj split -i`/`squash -i`'s callback
   programmatically — reusing jj's actual interactive-split code paths at
  the cost of shelling out per operation. What's implemented here instead
  stays fully in-process against `jj_lib`, with no subprocess or temp-file
  round trip.)
- **Revert (backout)**: `Transaction.revert_commit(commit, new_parent_ids) ->
  CommitBuilder` is `jj revert -r <commit> -d <new_parent_ids>` — computes
  the reverse of `commit`'s own change (relative to its parents) and
  applies it as a 3-way merge (`jj_lib::rewrite::merge_commit_trees` +
  `MergedTree::merge`, the same primitives `cli/src/commands/revert.rs`
  uses) on top of `new_parent_ids`. Like `new_commit`, conflicting when the
  reverse doesn't cleanly apply — e.g. reverting onto a destination that
  diverged from `commit`'s own history — rather than failing outright.
  Reverting several commits in sequence (`jj revert -r a -r b -r c`'s
  chaining) is composed in Python: call `revert_commit` repeatedly, each
  time passing the previous result's id as `new_parent_ids`. Does not
  rebase any existing descendants of `new_parent_ids` onto the new commit
  (the CLI's `--insert-after`/`--insert-before`) — compose that yourself
  with `rewrite_commit(child).set_parents([...])` + `rebase_descendants()`,
  same as arbitrary-destination rebase below.
- **Rebase to an arbitrary destination**: no single dedicated call, but
  fully achievable by composing existing primitives —
  `tx.rewrite_commit(commit).set_parents([dest_id, ...]).write()` then
  `tx.rebase_descendants()` to propagate to `commit`'s own descendants —
  matching what `jj rebase -r <commit> -d <dest>` does under the hood.
- **Not applicable**: sub-repos/submodules — `jj_lib`'s `SubmoduleStore`
  trait (`lib/src/submodule_store.rs`) is a stub (just a `name()` method);
  `DefaultSubmoduleStore` does nothing beyond that. The tree model
  recognizes `TreeValue::GitSubmodule(CommitId)` as a value, but there's no
  actual submodule checkout/update/clone machinery in `jj_lib` to bind to
  yet, experimental or otherwise — nothing for pyjj to expose here until
  upstream builds it.
- **Interdiff**: `ReadonlyRepo.interdiff(from, to, paths=None)` is
  `jj interdiff` -- how the changes `from` makes differ from the changes
  `to` makes. It rebases `from`'s tree onto `to`'s parents
  (`jj_lib::rewrite::rebase_to_dest_parent`) and diffs that against `to`'s
  tree, so unlike a plain diff it leaves out whatever changed between the
  two commits' *parents*.
- **Parallel split**: `Transaction.split_remainder_parallel(target, first)`
  is `jj split --parallel`'s second half. The chained
  `split_remainder()` can keep `target`'s tree, because a child of `first`
  shows the rest as a diff against it; a *sibling* hangs from `target`'s
  own parents, so its tree is `target`'s with the selected changes undone.
- **Reverting one operation**: `Transaction.revert_operation(op, what=None)`
  is `jj op revert`, and it is not `restore_operation` with an older
  target. Restoring makes the view *be* a past view and drops everything
  after it; reverting merges the target operation back out, so only its
  own changes disappear. It records rewrites, so the caller must
  `rebase_descendants()` before `commit()` -- restoring records none.
- **Abandoning without touching descendants**:
  `Transaction.abandon_restoring_descendants(targets, delete_abandoned_bookmarks=False)`
  is `jj abandon --restore-descendants`. A plain abandon rebases the
  descendants and their content can change; this reparents them, keeping
  each tree verbatim. The choice is made per commit inside the rewrite
  callback, so there is no `RebaseOptions` equivalent and this drives
  `transform_descendants` directly.
- **Diffing two operations**: `ReadonlyRepo.operation_diff(other, settings,
  changes_in=None)` is `jj op diff`, with `other` the "from" side. Both
  repos come from `load_at_operation()`. Two things make it more than a
  view comparison. The indexes must merge first, or a commit visible on
  only one side cannot be looked up; the binding does that in a
  transaction it drops and never commits, so the call still only reads.
  And `changes_in` is parsed once but resolved *twice*, against each repo
  separately -- a symbol can name different commits, or none at all, on
  the two sides. `ReadonlyRepo.merge_operations(ops)` comes with it: the
  "from" side of a merge operation is its several parents, and they must
  fold into one operation before a repo view can be loaded from them.
  The result names its two sides `before`/`after`, not jj's `from`/`to`,
  because `from` is a Python keyword and an attribute called that would
  be unreachable.
- **Garbage collection**: `ReadonlyRepo.gc(max_age_secs=0.0)` is
  `jj util gc`. Two stores hold garbage and both are swept -- the
  operation store drops operations unreachable from the current head,
  the commit store drops objects no commit in the index refers to -- and
  what "drop" means is the backend's business, so the Git backend runs
  `git gc`. Anything newer than the cutoff survives whether reachable or
  not, because a concurrent process may not have referenced its new
  objects yet. Two traps. The sweep starts from the repo's *own*
  operation, so collecting from a repo loaded at a past operation would
  delete everything the newer operations added; `jj` refuses that, and
  the caller must make the same check because the binding cannot tell.
  And its effect is invisible through the repo's own API -- what it
  removes was unreachable by definition -- so no test can assert an
  object went, only that the sweep ran and the repo still works.
- **Backend name**: `ReadonlyRepo.backend_name` is `jj util backend
  name` -- the string written to `.jj/repo/store/type` when the repo was
  created. It names the storage format, not the remote or the working
  copy.
- **Whether a snapshot did anything**: `Workspace.snapshot()`'s stats
  dict carries `changed`. The binding already returned early without
  writing when the walk found the same tree; the flag just says which
  path it took. `jj util snapshot` reports exactly this, as the
  difference between "Snapshot complete." and "No snapshot needed."
- **Deliberately deferred**: `jj_lib::rewrite::{find_recursive_merge_commits,
  find_duplicate_divergent_commits}` are internal helpers for the CLI's
  fuller `move_commits`-based multi-revision rebase (divergence detection),
  consistent with that machinery already being out of scope for `rebase()`
  above.

## Reproducible builds

`nix build .#foo` / `nix develop .#foo` (flake installable syntax) are
**banned** in this repo — never use them, including for quick one-off
checks. Flakes copy the *entire* source tree into the Nix store as one unit
before evaluating anything, on every single invocation, which is needless
overhead for a fast local loop. This repo evaluates through `default.nix`
(this repo's real outputs — packages, devShells — the single source of
truth) via [flake-compatish](https://github.com/lillecarl/flake-compatish)
(`nix/compat.nix`), which evaluates flake.nix without the flake CLI's
mandatory store-copy step. `overrides.self` in `nix/compat.nix` points
straight at the live repo directory:

```
nix develop --file . shells.default --command bash   # fast Rust loop for pyjj-bindings
nix develop --file . shells.pyjjui  --command bash   # editable-install dev loop (pyjj/pyjj-cli/pyjjui)
nix build --file . pyjj-bindings                     # native module only
nix build --file . pyjj                              # pythonic wrapper
nix build --file . pyjj-cli                          # CLI
```

**Use `--file .`, never bare `-A`.** On current Nix the legacy
`nix-shell`/`nix-build` front-ends are shims into the unified CLI, and in a
directory containing a `flake.nix` they resolve `-A` against *flake outputs*.
This repo's `flake.nix` deliberately declares none, so
`nix-shell -A shells.pyjjui` fails with "attribute 'shells' not found".
`--file .` bypasses flake resolution and evaluates `default.nix` directly —
no `flake.lock` consultation, no whole-tree store copy.

**Remote builders.** Big Rust builds (jj itself, fresh binding trees) go much
faster delegated to the nix-community build boxes:

```
--builders @/home/lillecarl/tmp/builders --max-jobs 0
```

Append to any `nix build`/`nix develop` invocation (`--max-jobs 0` forces
full delegation; drop it to build locally in parallel). The builders file is
machine-local — check it exists before relying on it.

The top-level `jj` attribute (`nix build --file . jj`) is the reference
CLI binary, pinned via the `jj-vcs` flake input to the same upstream
release as `pyjj-bindings`' jj-lib crate pin — keep that input tag in
sync when bumping the crate. The parity suite prefers whatever
`PYJJ_PARITY_JJ` names, else `jj` on PATH, so point it at this build
(`$(nix-build -L --file . -A jj)/bin/jj`) when you need the
version-matched comparison.

`flake.nix` still exists, but only to pin inputs and produce `flake.lock`
for `nix/compat.nix` (flake-compatish) to read directly — it declares no
packages/devShells outputs of its own, so there's nothing to fan out across
systems and nothing to drift from `default.nix`.

Each project directory (`pyjj-bindings/`, `pyjj/`, `pyjj-cli/`, `pyjjui/`)
*is* its own Nix `src`, full stop — no shared-tree exclude-filter to keep
in sync, unlike when this lived inside the jj monorepo. Editing one project
can never change another's derivation hash. `pyjj-bindings/package.nix`
still excludes `target/` (Rust build artifacts) from its own directory,
same idea, much smaller blast radius.

Both the classic path and the flake path build from the repo's dirty Git
tree, which only reflects files jj has synced into Git's index — and that
sync happens as a side effect of running a `jj` command (any of them; `jj
status` is the cheap one), not automatically the instant a file is
written. Run a `jj` command (so brand new files show up as `A` in `git
status --short`) before building after adding new files, or the build may
fail with a stale-looking "file not found" error for a module that very
much exists on disk.

## Async API

Every sync method keeps working unchanged; `_async` methods are added
alongside as `await`-able siblings. Which mechanism backs a given `_async`
method depends on whether its underlying jj_lib type can safely cross an
OS thread boundary — this is a hard Rust `Send`/`Sync` constraint, not a
design choice:

- **`ReadonlyRepo`/`Commit`** (`Arc<ReadonlyRepo>`/`Commit` — both
  `Send + Sync`): native `pyo3-async-runtimes`/tokio integration
  (`pyjj-bindings/src/aio.rs`'s `spawn_blocking_py`). `revset_async`,
  `resolve_single_async`, `get_commit_async`, `operation_log_async`,
  `load_operation_async`, `load_at_operation_async` on `ReadonlyRepo`;
  `is_empty_async`, `is_discardable_async`, `diff_async`,
  `diff_with_copies_async`, `read_file_async`, `file_exists_async`,
  `materialize_conflict_async` on `Commit`. Each runs on tokio's blocking
  thread-pool (jj_lib's own internals are synchronous I/O under the hood,
  not real non-blocking I/O — see `aio.rs`'s doc comment) and genuinely
  frees the event loop for the duration.
- **`Workspace`** (holds `Box<dyn WorkingCopy>` — `Send` but not `Sync`):
  the pyclass wraps it in `std::sync::Mutex<Workspace>` (supplies the
  missing `Sync`; also matches reality, since a workspace's on-disk state
  is exclusive-access by nature) and each I/O-doing method wraps its locked
  section in `Python::detach` (GIL release). On the Python side
  (`pyjj/pyjj/_async.py`), `snapshot_async`, `check_out_async`,
  `update_stale_async`, `set_sparse_patterns_async`, `add_workspace_async`,
  `forget_workspaces_async`, `rename_workspace_async`, `load_at_head_async`,
  `clone_git_async` wrap the sync methods in `anyio.to_thread.run_sync` —
  genuinely non-blocking, confirmed via a heartbeat-concurrency test
  (`pyjj/tests/test_asyncio.py`), since the GIL really is released while
  the worker thread runs.
- **`Transaction`/`CommitBuilder` have no async API, on purpose.**
  `PyTransaction` is `#[pyclass(unsendable)]` because jj_lib's
  `MutableRepo`/`Transaction` isn't even `Send` (holds a `Box<dyn
  MutableIndex>`, and that trait doesn't declare `Send` — confirmed via a
  throwaway `assert_send::<T>()` compile check, since deleted). There's no
  safe way to move it to a worker thread at all: `to_thread.run_sync` would
  crash with a hard `unsendable` panic (`assertion left == right failed:
  ... is unsendable, but sent to another thread`) the instant it touched a
  Transaction from any thread but the one that created it — confirmed
  empirically, not just reasoned. Use `Transaction` synchronously; it's
  fine to call its methods inline inside an `async def`, they just won't
  yield to the event loop while running, same as any synchronous call.
  (A `Mutex`-based fix like `Workspace`'s doesn't apply here — `Mutex<T>`
  is only `Send`/`Sync` if `T: Send`, and `Transaction` isn't. A dedicated
  single-thread-executor wrapper *could* work in principle, pinning one
  Transaction to one OS thread for its whole lifetime, but was judged not
  worth the complexity.)

## Notes

- `pyjj-bindings/Cargo.toml` pins `jj-lib` to a specific crates.io version
  (currently `0.43.0`) rather than a path dependency into a jj checkout.
  Bumping it can require source changes on this side too: the move off
  `~/Code/jj`'s in-progress `lib/` (which was ahead of the last crates.io
  publish) surfaced that `Workspace::init_internal_git`/
  `init_colocated_git` had gained a third `gix::hash::Kind` parameter
  upstream that crates.io's `0.43.0` doesn't have yet — `src/workspace.rs`
  was adjusted to the published 2-arg signature (defaults to SHA1, same
  effective behavior). Check for similar API drift whenever bumping the
  pin.
- `pyjj-bindings/Cargo.lock` and `pyjj`/`pyjj-cli`/`pyjjui`'s own
  `pyproject.toml`-declared dependencies are independent of each other.
- If `pyjj-bindings`'s public API shape changes, update `pyjj/pyjj/__init__.py`
  (the re-export surface) to match.
- `pyjj-bindings` depends on `pyo3-async-runtimes` (tokio-runtime feature) and
  `tokio` (rt-multi-thread) for the native async surface above.
- `shells.default`'s `shellHook` unsets `PYTHONPATH`: nixpkgs' `python3` wrapper
  sets it to its own site-packages, and if that leaks into a project venv
  built against a *different* python minor version, the venv's `sysconfig`
  can shadow-import the wrong version's `_sysconfigdata_*` module (the
  module name collides on ABI/platform, not version). This silently gives
  tools like `maturin`/`pyo3-build-config` the wrong lib name/dir/ABI tag —
  bit us directly as a `cp313`-built extension module getting saved to disk
  as `....cpython-314-....so`, which the venv's real 3.13 interpreter then
  refused to import.
