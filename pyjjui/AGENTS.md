# pyjjui — Textual TUI for jj

A terminal UI for Jujutsu, built directly on `pyjj` (no shelling out to the
`jj` binary, no ANSI/text parsing — structured data straight from jj_lib via
pyjj-bindings). See the root `AGENTS.md` for the `pyjj`/`pyjj-bindings`
binding surface this depends on; this file only covers `pyjjui` itself.

Inspiration (UX, not implementation): `~/Code/jjui` (Go/bubbletea). jjui
shells out to `jj log` and re-parses its ANSI art; pyjjui instead consumes
`ReadonlyRepo.log_graph()` (structured `GraphNode`/`GraphEdge` data) and
does its own lane-layout in `graph_layout.py` — the one piece jjui gets for
free that we don't.

## Layout

- `src/pyjjui/state.py` — `AppState`: holds `Workspace`/`ReadonlyRepo`/
  `UserSettings` plus the active revset string. `refresh()` reloads the repo
  and re-evaluates `log_graph()`. `run_mutation()` is the one sanctioned way
  to touch a `Transaction`.
- `src/pyjjui/mutations.py` — one sync function per mutating action
  (`new_child`, `edit`, `describe`, `abandon`, `rebase`, `squash`,
  `duplicate`, `set_bookmark`, `undo`, `redo`, `restore_operation`), each
  shaped `(workspace, repo, settings, ...) -> ReadonlyRepo` for
  `run_mutation()`.
- `src/pyjjui/graph_layout.py` — pure-Python lane/column assignment over
  `list[GraphNode]`, feeding `widgets/log_view.py`'s rendering. Lanes track
  `(commit_id, edge_type)`, not just an id: when a second (or later) lane
  reaches the same ancestor another lane already claimed, its edge is
  redirected to converge into that ancestor's own column and the lane is
  retired -- without this, a fork's second branch just ran on forever as a
  disconnected same-column "pass" line that never visually reconnected
  (`n` on an ancestor commit looked like it created a straight line, no
  tree, even though the underlying commit graph *was* correctly forked).
  `log_view.py`'s `_render_glyphs` draws these convergences as `╮`/`╭`
  (forking away from this row, downward) or `╯`/`╰` (an earlier row's lane
  closing back into this one) plus `─` fill between the two columns, not
  just parallel `│` bars.
- `src/pyjjui/widgets/` — Textual widgets (`log_view.py` -- also renders
  each commit's local bookmarks from `ReadonlyRepo.bookmarks()`,
  `preview.py`).
- **Keybindings, hjkl included**: `j`/`k` move the log selection (same as
  down/up) and scroll the preview pane once it has focus. `l`/`h` move
  focus log->preview / preview->log -- adapted from `~/Code/jjui`'s
  convention (which uses the same keys to open/close a separate
  revision-details panel) to pyjjui's own layout, where both panes are
  always visible side by side rather than toggled. Preview's focus state
  is shown via `border-left` switching between the `$border`/
  `$border-blurred` theme tokens (the same convention Textual's own
  `Input`/`DataTable` use for focus, not a hardcoded color pair) --
  respects whatever theme is active instead of assuming dark-mode accent
  colors. Focus never crosses siblings directly: `LogView`/`Preview` each
  post a `FocusPreview`/`FocusLog` message on `l`/`h` instead of doing
  `self.screen.query_one(...)` on each other, and `PyjjuiApp` handles both
  (`on_log_view_focus_preview`/`on_preview_focus_log`) -- the same
  "attributes down, messages up" pattern `CommitSelected` already used.
- **Marking commits for bulk operations**: `space` toggles a mark on the
  cursor commit (shown as a `"✓ "` prefix in the summary column), `escape`
  clears all marks. `LogView.selection` is what actions should read
  instead of `selected_commit` directly -- it returns the marked commits in
  display order, or falls back to just the cursor commit if nothing is
  marked, so marking is opt-in and every existing single-commit action
  keeps working unchanged. `action_new_child` (`n`) uses this to build a
  merge commit when 2+ commits are marked; `action_abandon` (`a`) uses it
  to abandon the whole marked set in one transaction (see
  `mutations.new_child`/`mutations.abandon`, both take `list[pyjj.Commit]`
  for this reason). Toggling a mark repaints only the affected row via
  `DataTable.update_cell` (`LogView._update_row_mark`), not a full
  `clear()`+rebuild -- `_redraw()` stays reserved for `update_nodes()`,
  where the underlying data (not just marks) actually changed.
- **Rebase, all destination modes**: `m` opens `screens/rebase.py`'s
  `RebaseScreen` with `LogView.marked_commits` (must be non-empty -- marks
  are the *source*, never falling back to the cursor commit the way
  `selection` does) as the source set and the cursor commit as the
  destination. The modal picks `mutations.rebase()`'s `mode` ("onto" /
  "after" / "before" -- `-d`/`-A`/`-B`) and whether to pull the source's
  descendants along too (`include_descendants`, `-s` vs the default `-r`;
  only meaningful with exactly one marked commit). `mutations.rebase()`
  itself only computes which ids `-A`/`-B` imply
  (`children(destination)`/`destination.parent_ids`) before delegating the
  actual graph surgery to `Transaction.move_commits` -- see root
  `AGENTS.md`'s "Rebase" section for why that logic isn't reimplemented in
  Python. Combining `-A` and `-B` together (splicing between two distinct
  boundary commits, not just one) isn't exposed in the modal yet, though
  the binding underneath already supports it.
- **Squash and duplicate**: `s` squashes the cursor commit into its own
  parent (plain `jj squash`, no explicit destination -- always the cursor
  commit, never `LogView.selection`, since squash is inherently one source
  into one destination). `mutations.squash()` stands in for `jj squash`'s
  editor-based message-combining step: keeps the destination's message if
  it already has one, otherwise falls back to the source's. Raises
  `pyjj.JjError` for a merge-commit source (needs an explicit destination
  plain `jj squash` doesn't infer either -- not supported here yet). `y`
  duplicates `LogView.selection` (marked commits, or just the cursor
  commit) onto their own original parents via `Transaction.duplicate()` --
  originals untouched, no working-copy/bookmark changes, so no
  `rebase_descendants()`/`_sync_working_copy()` needed in
  `mutations.duplicate()`.
- **Operation log browsing**: `o` opens `screens/oplog.py`'s `OpLogScreen`
  over `ReadonlyRepo.operation_log()` (newest first, same order as `jj op
  log`) -- a `DataTable` of every past operation's end time and
  description. Enter (or a row click, `DataTable`'s own `RowSelected`)
  dismisses with that `Operation`; `app.py` then confirms via the same
  `ConfirmScreen` `abandon` uses before calling
  `mutations.restore_operation()`. Distinct from the single-step `u`/`U`
  undo/redo bindings: this can jump straight to *any* past operation, not
  just one step back/forward, mirroring `jj op restore` rather than `jj
  undo`. `mutations.restore_operation()` always restores both the repo and
  remote-tracking portions of the target view (`Transaction
  .restore_operation()`'s `what` parameter exists for a partial restore,
  but the screen has no UI for choosing a subset -- not needed yet).
- **Error handling boundary**: `app.py`'s `action_refresh_log()` and
  `_run_mutation()` are the only places that catch `pyjj.JjError` (the
  common base for revset-parse errors, transaction errors, etc.) and
  surface it via `self.notify(..., severity="error")` instead of letting
  it propagate and crash the whole app. Every action that can fail for a
  user-reachable reason (bad revset syntax, describing something that
  can't be rewritten, nothing to undo) must route through one of these two
  -- don't call `state.refresh()`/`state.run_mutation()` directly from a
  new action and skip the try/except, or a bad revset typed into the UI
  takes the whole app down with it (this actually happened before these
  existed).
- `src/pyjjui/render/diff.py` — presentation-only diff formatting (built on
  `pyjj_bindings.diff_hunks`); stays here, not a pyjj binding, since it's
  pure UI formatting with no jj_lib logic behind it.
- `src/pyjjui/app.py` — the Textual `App` subclass tying state + widgets +
  keybindings together.

## The one load-bearing async rule

`Transaction`/`CommitBuilder` are `unsendable` on the Rust side (jj_lib's
`MutableRepo` isn't `Send`) — a `Transaction` must be created, mutated, and
committed on a single thread, and can never be awaited across or passed
between threads mid-transaction. `AppState.run_mutation()` is the only
place this happens: it runs a whole synchronous `mutations.py` function
(create tx → mutate → commit, all in one call) via
`anyio.to_thread.run_sync()`. Never call `repo.start_transaction()` (or
anything transaction-shaped) directly from a widget or from `async def`
code outside `mutations.py` — route it through `run_mutation()`.

## Async library: anyio, not bare asyncio

Use `anyio` (`anyio.to_thread.run_sync`, `anyio.create_task_group()`, etc.),
not `asyncio` directly, for any new async code — this is a firm project
convention here, not a style nit. anyio detects Textual's running asyncio
loop automatically (via `sniffio`), so there's no conflict running on top
of Textual's own event loop. Reference implementation: `~/Code/anyio`.

## Testing

- Async tests are plain `async def test_...()` — no `@pytest.mark.asyncio`
  marker, no `pytest-asyncio`. `anyio_mode = "auto"` in `pyproject.toml`
  enables anyio's own built-in pytest plugin repo-wide for this package.
- Interaction tests drive the app via Textual's `App.run_test()` →
  `Pilot` (`async with app.run_test() as pilot: await pilot.press("n")`).
- Snapshot ("print-screening") tests use `pytest-textual-snapshot`'s
  `snap_compare` fixture — SVG regression screenshots committed under
  `tests/__snapshots__/`.
- For live manual debugging (not part of automated tests): `textual run
  --dev -- python -m pyjjui` plus `textual console` in a second terminal.

## Packaging: Nix only, no pip, ever

Package builds (`pyjj.nix`, `pyjj-cli.nix`, `pyjjui.nix`) are rendered from
each project's own `pyproject.toml` via `pyproject-nix`
(`nix/pyproject.nix`'s `renderPyproject` — dependencies/build-system/entry
points read straight from the TOML, not hand-duplicated in Nix). Wired into
`default.nix`'s outputs (and re-exposed per-system by `flake.nix`).

Build via classic (non-flake) evaluation — `nix build .#pyjjui` /
`nix develop .#pyjjui` are banned repo-wide, see root `AGENTS.md`'s
"Reproducible builds" section for why (flakes force a whole-repo store
copy on every invocation, which busts `pyjj-bindings`' cache on unrelated
changes):

```
nix build --file . pyjjui
nix-build -A pyjjui
```

### Dev loop: `nix-shell -A shells.pyjjui`, editable installs, no PYTHONPATH

`shells.pyjjui` (in `default.nix`, evaluated via `nix/compat.nix`'s
flake-compatish shim) uses `nix/pyproject.nix`'s `renderEditablePyproject`
+ nixpkgs' `mkPythonEditablePackage` to install `pyjj`, `pyjj-cli`, and
`pyjjui` as PEP-660 editable packages pointed at `$GIT_ROOT` (exported by
the shell's own `shellHook`, real filesystem path, not a Nix store copy).
Editing any `.py` file under `pyjj/pyjj/`, `pyjj-cli/src/`, or
`pyjjui/src/` takes effect immediately in the next `python`/`pytest`
invocation in that shell — no `PYTHONPATH`, no reinstall step, no Nix
rebuild:

```
nix-shell -A shells.pyjjui
python -m pyjjui
pytest pyjjui/tests
```

`pyjj-bindings` (the compiled Rust extension) is *not* editable here --
for fast Rust iteration use `nix-shell -A shells.default` + `maturin
develop`, then re-enter `nix-shell -A shells.pyjjui` to pick up the freshly
built extension.

No `pip install` anywhere, at any point, for any reason.

## Visual review: `pyjjui/tools/screenshot.py`

Renders the app to SVG or PNG without a real terminal, for visual review of
UI changes (by a human or by Claude, which can view PNGs but not raw
terminal output):

```
python pyjjui/tools/screenshot.py --out /tmp/log.png
python pyjjui/tools/screenshot.py --out /tmp/merge.png --scenario merge
python pyjjui/tools/screenshot.py --out /tmp/modal.svg --press d
```

Builds a throwaway demo repo via `pyjjui/tests/testutils.py` (the same
factory the test suite's fixtures use — don't reimplement repo setup in a
new script; extend `testutils.py` and this tool together instead) and calls
Textual's own `take_svg_screenshot`. PNG output goes through `cairosvg`
(in `devShells.pyjjui`), not `resvg`: `resvg`'s SVG parser rejects the
`clip-path` syntax Rich's SVG export uses and silently drops all text;
`cairosvg` (same underlying engine family as `librsvg`, which does handle
it) renders correctly — confirmed empirically. `--out` ending in `.svg`
skips the PNG conversion entirely.
