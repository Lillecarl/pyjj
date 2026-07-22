# Handoff: pyjj extraction from ~/Code/jj

Status as of this handoff: **the migration works end-to-end, is fully
verified, and is now committed** as the initial commit of this repo. Read
`AGENTS.md` first for the actual project docs (binding-surface coverage,
architecture, testing conventions); this file is just "what happened and
what's left," not a replacement for it.

## Why this repo exists

This used to live inside `~/Code/jj` (the jj VCS monorepo itself) as
`pyjj-bindings/`, `pyjj/`, `pyjj-cli/`, `pyjjui/`. Two problems drove moving
it out:

1. Nix packaging for `pyjj-bindings` needed the whole jj monorepo present as
   `src` (it depended on `jj-lib` via `path = "../lib"`, and `lib/` itself
   inherits fields from the monorepo's root `Cargo.toml` workspace), so
   editing *any* file anywhere in the monorepo — even an unrelated
   `pyjjui/` change — could bust `pyjj-bindings`' derivation hash and force
   a full Rust rebuild.
2. Flakes copy the entire source tree into the Nix store as one unit before
   evaluating anything, on every invocation — compounding problem 1 and
   making iteration slow regardless of source filtering.

The fix that was already in flight before the extraction (still relevant,
now simpler): evaluate through `default.nix` via
[flake-compatish](https://github.com/lillecarl/flake-compatish)
(`nix/compat.nix`) instead of flake installable syntax (`nix build .#foo`),
so `overrides.self` points straight at the live repo directory and nothing
gets store-copied. **That pattern is now applied in *both* repos** —
`~/Code/jj` got it first (for the Rust `jujutsu` CLI + the pyjj-* packages
that used to live there), then this repo got its own copy when pyjj-* moved
out. `nix build .#foo` / `nix develop .#foo` are banned in both repos — see
each repo's `AGENTS.md` "Reproducible builds" section.

Moving `pyjj-bindings` out entirely solves problem 1 more thoroughly than
filtering ever could: each project directory here **is** its own Nix `src`,
full stop (see `pyjj-bindings/package.nix` — no exclude-regex list at all,
just `target/`). It also meant swapping `pyjj-bindings`'s `jj-lib`
dependency from a path dep into a normal crates.io dependency (currently
pinned to `0.43.0`) — jj-lib is a published, actively-maintained crate, so
this isn't a hack.

## What's actually verified working

All of this was run and confirmed in this session, inside
`nix-shell default.nix -A shells.pyjjui` (or via `nix-build default.nix -A
<pkg>` for the package builds):

- `nix-build -A pyjj-bindings` — Rust extension compiles against crates.io
  `jj-lib = "0.43.0"`.
- `nix-build -A pyjj -A pyjj-cli -A pyjjui` — all three pure-Python packages
  build via `pyproject-nix`.
- `nix-shell -A shells.pyjjui` enters cleanly, `GIT_ROOT` exports correctly,
  editable installs resolve to real repo paths (not store copies).
- Test suites, run **separately per project** (see gotcha below):
  - `pyjj-bindings/tests/`: **62 passed**
  - `pyjj/tests/`: **304 passed**
  - `pyjjui/tests/`: **17 passed** (including both snapshot tests, after
    regenerating the two baseline `.raw` SVGs — see below)
- `pyjjui/tools/screenshot.py` renders correctly (visually confirmed via a
  PNG render — log view, graph glyphs, preview pane, footer keybindings all
  present and correct).

### Gotcha: run each project's pytest separately

`pyjj/pyproject.toml` and `pyjjui/pyproject.toml` have different
`[tool.pytest.ini_options]` (only `pyjjui`'s sets `anyio_mode = "auto"`).
Running `pytest pyjj/tests pyjjui/tests` in one invocation from the repo
root makes pytest pick only *one* project's config for the whole session —
`pyjjui`'s async tests then fail with "async def functions are not
natively supported" because `anyio_mode` never got applied. Always `cd`
into each project directory and run `pytest` from there (matching what
`AGENTS.md`'s own documented workflow already says to do), or invoke each
separately from the root.

## API drift fixed while swapping to crates.io jj-lib

`~/Code/jj`'s `lib/` was ahead of the last crates.io publish (`0.43.0`,
same version *string*, different code — pre-release/in-progress work). Three
call sites in `pyjj-bindings/src/` needed adjusting to the published
signatures. **If the `jj-lib` version pin in `pyjj-bindings/Cargo.toml` is
ever bumped, re-check these are still correct against that release**:

1. `src/workspace.rs`: `Workspace::init_internal_git`/`init_colocated_git`
   lost a third `gix::hash::Kind` parameter going from local → published
   (i.e. published 0.43.0 only takes 2 args; local dev code had a 3rd).
   Fixed by dropping the arg (defaults to SHA1 either way).
2. `src/git.rs`: `git::fetch(...)` needed a 5th `None` argument
   (`Option<FetchTagsOverride>`, new in published 0.43.0 vs local).
3. `src/git.rs`: `git::add_remote(...)` needed a 5th argument, but as a
   **plain** `gix::remote::fetch::Tags` (not `Option<Tags>`) — used
   `gix::remote::fetch::Tags::default()` (`Tags::Included`, the crate's own
   `#[default]`, matching ordinary `git remote add` behavior).

Also vendored `pyjj-bindings/vendor/revsets.toml` (copied from jj's
`cli/src/config/revsets.toml`) — `src/config.rs` previously reached it via
`include_str!("../../cli/src/config/revsets.toml")`, a relative path into
the jj monorepo's `cli/` crate that no longer exists as a sibling. This is
jj's bundled `mutable()`/`trunk()`/`immutable_heads()` revset-alias
defaults; re-sync it from upstream jj whenever the `jj-lib` pin bumps to a
release with revset-alias changes.

## Not yet done / open decisions

1. **This repo is now committed.** The corresponding changes in `~/Code/jj`
   (flake-compat integration, `nix/pyproject.nix`, etc.) are still sitting
   as uncommitted working-copy state there — review and commit separately
   when ready.
2. **`~/Code/jj` still has copies of `pyjj-bindings/`, `pyjj/`,
   `pyjj-cli/`, `pyjjui/`**, plus `flake.nix`/`default.nix` there still
   reference and build them. This was flagged to the user and not yet
   actioned — needs a decision on:
   - Deleting those four directories from `~/Code/jj`.
   - Reverting `~/Code/jj`'s `flake.nix`/`default.nix`/`AGENTS.md` to drop
     the pyjj-specific packages/devShell, while presumably *keeping* the
     flake-compat + `nix/jujutsu.nix` restructuring there (it benefits the
     plain `jujutsu` Rust build too, independent of pyjj).
   - `~/Code/jj`'s root `AGENTS.md` currently has a `pyjjui/` bullet and a
     large "pyjj workflow" — style header; that content should move/point
     here once the old copies are removed.
3. **`gix` may now be an unused direct dependency** in
   `pyjj-bindings/Cargo.toml` — the only code reference to `gix::` types
   (`gix::hash::Kind::Sha1`) was removed as part of the API-drift fix, and
   a grep found no other `gix::`-qualified usage in `src/` (only mentions
   in doc comments). Worth confirming with `cargo build` warnings and
   trimming the dependency + re-running `cargo generate-lockfile` if
   genuinely dead — not done yet, low priority.
4. **`shells.default`** (the fast Rust loop: bare cargo/rustc/maturin
   shell, `nix-shell -A shells.default`) was written but **not smoke-tested
   this session** — only `shells.pyjjui` (the Python editable-install shell)
   was actually exercised. Worth a quick `maturin develop -m
   pyjj-bindings/Cargo.toml` + `python pyjj-bindings/smoke_test.py` pass to
   confirm it still works standalone, now that `pyjj-bindings` has no
   monorepo dependency to worry about.
5. **`snapshot_report.html`** (pytest-textual-snapshot's failure-report
   artifact) was generated twice this session and deleted both times; now
   gitignored. If you see it again after a snapshot test failure, that's
   expected/disposable, not a bug.
6. Disk ran completely full (`/` at 100%) partway through this session's
   builds — `nix-collect-garbage -d` (user-level, not `sudo`) freed ~13GB
   and builds proceeded fine after. Worth keeping an eye on if builds start
   failing with "No space left on device" again.

## Quick-start commands for the next session

```
cd ~/Code/pyjj
nix-build default.nix -A pyjj-bindings --no-out-link   # or pyjj / pyjj-cli / pyjjui
nix-shell default.nix -A shells.pyjjui                 # editable Python dev loop
nix-shell default.nix -A shells.default                # fast Rust loop (maturin develop)
```

Inside `shells.pyjjui`, `GIT_ROOT` must be exported before running Python
(the shellHook does this automatically on entry; re-export manually if
you're scripting non-interactively, e.g.
`GIT_ROOT=$(git rev-parse --show-toplevel) pytest ...`).

Never use `nix build .#foo` / `nix develop .#foo` — see `AGENTS.md`.
