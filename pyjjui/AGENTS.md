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
  (`new_child`, `edit`, `describe`, `abandon`, `set_bookmark`, `undo`,
  `redo`), each shaped `(workspace, repo, settings, ...) -> ReadonlyRepo`
  for `run_mutation()`.
- `src/pyjjui/graph_layout.py` — pure-Python lane/column assignment over
  `list[GraphNode]`, feeding `widgets/log_view.py`'s rendering.
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
  colors.
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
