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
  `duplicate`, `split`, `set_bookmark`, `undo`, `redo`,
  `restore_operation`), each shaped `(workspace, repo, settings, ...) ->
  ReadonlyRepo` for
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
  plain `jj squash` doesn't infer either -- not supported here yet). Its
  confirm prompt passes the source-vs-parent diff as `ConfirmScreen`'s
  `detail` (see the "don't ask again" bullet below for what that is) --
  showing exactly what's about to be absorbed into the parent, not just
  the two change ids. `y`
  duplicates `LogView.selection` (marked commits, or just the cursor
  commit) onto their own original parents via `Transaction.duplicate()` --
  originals untouched, no working-copy/bookmark changes, so no
  `rebase_descendants()`/`_sync_working_copy()` needed in
  `mutations.duplicate()`.
- **Split**: `x` opens `screens/split.py`'s `SplitScreen` over the cursor
  commit's changed paths (`Commit.diff()` against its single parent --
  same merge-commit restriction `squash` has, since there is no single
  parent tree to diff against otherwise; `app.py` warns instead of
  opening the modal). A `SelectionList` (checkbox list, `space` toggles,
  `j`/`k` added alongside its own up/down) picks which paths go into the
  first commit; `mutations.split()` wraps the existing
  `Transaction.split_selected()`/`split_remainder()` pair (already in
  pyjj-bindings/pyjj from earlier work, no Rust changes needed) --
  `split_selected` keeps the target's own change id for the first
  (selected-paths) commit, `split_remainder` gives the second (everything
  else) a fresh change id as the first's child. Both halves keep the
  target's original description; editing each one's message separately
  isn't exposed here yet, the same gap `squash` has for merge-commit
  sources. If the target was the working copy, `@` moves to the second
  commit afterward -- matching plain `jj split`'s own behavior.
- **File browser**: `f` opens `screens/files.py`'s `FilesScreen` over the
  cursor commit's full tree, listed via `Commit.list_files()` (a flat,
  sorted, repo-relative path list -- no directory-tree nesting, since
  these repos aren't big enough yet to need it). Same two-pane shape as
  `OpLogScreen`: `_FileTable` (a `DataTable`) beside a `ContentPane`
  showing whichever path is highlighted, read via `Commit.read_file()` and
  decoded as UTF-8 (`errors="replace"`, so a binary file just shows
  replacement characters rather than crashing the read -- files over
  512KiB skip the read entirely and show a placeholder instead, same
  threshold `render/diff.py` uses for the same reason). Same hjkl
  convention as `_OpTable`/`DiffPane` (`j`/`k` in the table, `l`/`h` to
  move focus into/out of the content pane). Unlike the other modals, it
  composes its own `Footer()` -- with two real actions living here
  (`d`/`r`, below) alongside `escape`, a plain instructional `Label`
  wasn't enough to keep them discoverable, the same reasoning the main
  screen's `Footer` already serves.
  - **`d` -- diff vs working copy**: toggles `ContentPane` between raw
    content and `render/diff.py`'s new `render_file_diff(after, before,
    path)` (a `render_commit_diff` sibling scoped to one path between two
    *arbitrary* commits, not necessarily parent/child) comparing the
    browsed commit's version of the highlighted path against the
    *current* working copy's -- "what would change if I restored this
    now", not a diff against the browsed commit's own parent.
  - **Marking, and `r` -- restore into the working copy**: `space` marks
    any number of paths (a `"mark"` `DataTable` column, same `✓` convention
    as `OpLogScreen`'s, but a genuine multi-path `set[str]` rather than a
    single index -- more like `LogView`'s own marking). `r` restores
    `_selected_paths()` -- the marked paths in list order, or just the
    highlighted one if nothing's marked, the same "marked, or fall back to
    the cursor" rule `LogView.selection` uses -- via `mutations.restore_files()`
    (`jj restore --from <browsed-commit> <paths>...` equivalent, wrapping
    the existing `Transaction.restore()` binding -- already in
    pyjj-bindings/pyjj, no Rust changes needed), one transaction for the
    whole batch, not one per path. Always restores into `@` specifically
    (never an arbitrary destination) -- rewrites the working-copy commit
    in place via `CommitBuilder`, same `tx.set_wc_commit()` +
    `tx.rebase_descendants()` shape `mutations.describe()` uses for its
    `was_wc` branch, since `into` is unconditionally `@` here. Routes
    through the same `_confirm()`/"don't ask again" gate every other
    mutation does (action key `"restore_file"`, even for a multi-file
    restore -- same precedent as `"abandon"`/`"rebase"`/`"duplicate"`
    being singular action-key names regardless of batch size), passing
    `render_file_diff()`/`render_files_diff()` (one path vs several, each
    under its own path header) as the confirm's `detail` -- so the
    restore confirm shows exactly what's about to change. A no-op guard
    (browsing `@` itself) skips the confirm entirely and just notifies
    "nothing to restore" -- restoring a commit into itself is
    meaningless, not just harmless. Restoring doesn't dismiss the screen:
    `FilesScreen` calls `app._run_mutation()` and `app.action_refresh_log()`
    directly (reaching into `self.app`'s private-by-convention helpers --
    acceptable here since `FilesScreen` lives in the same package and
    browsing is meant to continue uninterrupted after a restore), clears
    the marks that were just restored, then re-renders the current pane
    so a diff-mode view immediately reflects the new "no difference".
- **Operation log browsing**: `o` opens `screens/oplog.py`'s `OpLogScreen`
  over `ReadonlyRepo.operation_log()` (newest first, same order as `jj op
  log`) -- a two-pane modal, `_OpTable` (a `DataTable` of every past
  operation's end time and description) beside a `DiffPane`, the same
  `LogView`/`Preview` side-by-side shape the main screen uses. Enter (or a
  row click, `DataTable`'s own `RowSelected`) dismisses with that
  `Operation`; `app.py` then confirms via the same `ConfirmScreen`
  `abandon` uses before calling `mutations.restore_operation()`. Distinct
  from the single-step `u`/`U` undo/redo bindings: this can jump straight
  to *any* past operation, not just one step back/forward, mirroring `jj
  op restore` rather than `jj undo`. `mutations.restore_operation()`
  always restores both the repo and remote-tracking portions of the
  target view (`Transaction.restore_operation()`'s `what` parameter
  exists for a partial restore, but the screen has no UI for choosing a
  subset -- not needed yet). Its confirm prompt isn't just text: `app.py`
  computes the working-copy diff between the *current* live repo and the
  target operation (`render_commit_diff(target_wc, current)`, the same
  renderer `DiffPane`/`Preview` use) and passes it as `ConfirmScreen`'s
  `detail`, so what a restore would actually change is visible right
  before confirming it -- not just the operation's id/description.
  - **hjkl**: `_OpTable` binds `j`/`k` to cursor down/up (`DataTable` only
    binds arrow keys itself) and `l` to focus `DiffPane`; `DiffPane` binds
    `j`/`k` to scroll and `h` back to the table -- same convention as
    `LogView`/`Preview`, but resolved with direct `self.screen.query_one()`
    calls instead of the `FocusPreview`/`FocusLog` message pair, since
    both widgets live only inside this one screen (no cross-`App` reuse
    to decouple, unlike the main screen's pair).
  - **Diffing between two points in history, not just restoring to one**:
    highlighting a row shows the diff between that operation's working-
    copy tree and a base -- `space` marks any row as that base (checkmark
    in the `mark` column, moving to a newly-marked row un-marks the old
    one); with nothing marked the base is the *current* repo state (what
    was loaded when `o` was pressed), answering "what changed since now"
    directly. Both sides are computed via `ReadonlyRepo.load_at_operation
    (op).resolve_single(settings, "@")` -- the working-copy commit as of
    that operation -- then `render_commit_diff()` (already used by
    `Preview`), reused as-is since it only needs two `Commit`s regardless
    of whether they're parent/child or two unrelated operations' working
    copies.
  - **`f` -- browse that operation's files**: pushes the same
    `FilesScreen` the main log's `f` binding opens (`screens/oplog.py`
    imports it directly -- no cycle, since `files.py` doesn't import
    `oplog.py`), over the highlighted row's working-copy commit
    (`ReadonlyRepo.load_at_operation(op).resolve_single(settings, "@")`,
    the same resolve `_show_diff()` already does). One nuance:
    `self.app.push_screen_wait(...)`, not `self.push_screen_wait(...)` --
    `push_screen_wait` is an `App` method, not a `Screen` one, so pushing
    a screen *from* a screen (rather than from an `App` action) has to
    go through `self.app` explicitly. `FilesScreen` itself needed no
    changes: its diff/restore logic already reads `self.app.state` for
    "the live working copy", which is correct regardless of whether it
    was opened from the main log or from an arbitrary historic operation
    here.
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
- **Confirmation before every history-rewriting mutation**: `describe`,
  `squash`, `split`, `rebase`, and `duplicate` (alongside `abandon` and
  the op-log `restore_operation`, which already had one) each push a
  `ConfirmScreen` naming exactly what's about to happen -- the affected
  change id(s), and for `describe`/`squash`/`split`/`rebase`
  specifically, a preview of the actual effect (`describe`'s new first
  line, `squash`'s destination, `split`'s path count, `rebase`'s mode and
  destination) -- right before the `_run_mutation()` call, even when the
  action already went through a parameter-picking modal first
  (`rebase`'s mode picker, `split`'s path picker). The two are
  deliberately separate steps, not one merged dialog: the first modal
  answers "how", the `ConfirmScreen` answers "are you sure", and skipping
  the second because the first already required a click was explicitly
  rejected -- every mutation that touches an *existing* commit (rewrite,
  discard, or copy) gets the same final gate, regardless of whatever
  picker preceded it. Bulk actions (`abandon`/`rebase`/`duplicate` acting
  on 2+ marked commits) still get exactly **one** `ConfirmScreen` for the
  whole batch (`f"... {len(commits)} commits?"`), never one per commit --
  the prompt-building `if len(commits) > 1: ... else: ...` branch is the
  same shape in all three. `new_child`/`edit`/`set_bookmark` don't get
  one: neither creates, rewrites, nor discards an existing commit (a
  brand-new commit, a plain checkout, or a bookmark move).
- **"Don't ask again" for confirmations**: `ConfirmScreen` (`screens/confirm.py`)
  dismisses with a `ConfirmResult(confirmed, remember)` instead of a bare
  `bool`. When constructed with `remember_key=<action>` (every confirmable
  action except op-log's `restore_operation`, see below) it renders two
  mutually-exclusive `Checkbox`es -- "this session" / "ever" -- and
  `remember` comes back as `"session"`, `"ever"`, or `None`. `app.py`'s
  `_confirm(action, prompt)` is the single gate every confirmable action
  calls instead of pushing `ConfirmScreen` directly: it short-circuits to
  `True` if `AppState.should_confirm(action)` is already `False`, otherwise
  shows the modal and calls `state.remember_skip(action, result.remember)`
  when a box was checked. Skip state is tracked per action-name string
  (`"describe"`, `"squash"`, `"split"`, `"rebase"`, `"duplicate"`,
  `"abandon"`) -- deliberately not one global toggle, so skipping squash
  confirmations doesn't silently also skip rebase ones.
  `AppState._skipped_confirmations` is a `set[str]`, seeded at startup from
  `pyjjui.config.load_skipped_confirmations()`; `"session"` only adds to
  that in-memory set, `"ever"` also calls
  `pyjjui.config.persist_skip_confirmation(action)`, writing to a small
  JSON file (`$XDG_CONFIG_HOME/pyjjui/confirmations.json`, override via
  `PYJJUI_CONFIG_DIR` -- what `conftest.py`'s autouse `pyjjui_config_dir`
  fixture points at a tmp dir for test isolation) -- deliberately a
  pyjjui-only preferences file, not a `jj` config value, since it's UI
  state no other jj frontend would ever read. Op-log's `restore_operation`
  confirm is the one deliberate exception: it always pushes a bare
  `ConfirmScreen(prompt)` (no `remember_key`, bypassing `_confirm()`
  entirely) since restoring to an arbitrary past operation is rare and the
  highest-blast-radius action here (can silently move bookmarks/heads/wc
  backward) -- it should never be silenceable. `ConfirmScreen` itself
  gained an optional `detail: RenderableType | None` param (rendered in a
  bordered, scrollable `VerticalScroll#detail` below the message) purely
  to support this -- see the op-log bullet above for the one caller that
  uses it.
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
