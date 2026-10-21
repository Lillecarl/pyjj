# Code generation for pyjj-bindings: assessment

Read-only. Nothing in `~/Code/pyjj` or `~/Code/jj` was changed. All trials ran
in a scratch copy under this scratchpad (`stubtry/`).

## Verdict

| # | Question | Verdict | What decided it | Effort |
|---|---|---|---|---|
| 1 | `.pyi` stubs from the existing crate | **Feasible** (measured) | pyo3 0.29 `experimental-inspect` + `maturin build --generate-stubs` produced a 2816-line stub: 65 classes, 473 defs, exception hierarchy correct. Two blockers, both small: the function-style `#[pymodule]` gives a stub of `__getattr__ -> Incomplete` only, and a parameter named `from` makes the stub invalid Python. | ~0.5-1 day: one feature flag, a declarative-module `lib.rs` (done in scratch, compiles first try), rename `from` in 2 methods, return annotations on 17 async methods, stubs for 9 Python-patched `Workspace.*_async` methods, and `--generate-stubs` in `package.nix` (`maturinBuildHook` flags), or the Nix wheel ships no `.pyi`. |
| 2 | Generate the PyO3 wrappers from jj-lib | **No** | Hand count of repo.rs + ids.rs + bookmark.rs + tag.rs (164 bound fns): 7% pure delegation, 63% patterned, 30% real adaptation. The 30% holds most of the code: about 70% of the crate's function-body lines are type (c). On the jj-lib side, 17% of 944 public fns use only std types. The rest need wrappers for domain types, lifetimes, `dyn` or async. pyjj touches about 157 distinct `jj_lib::` paths. A generator would emit many things nobody calls and still leave the hard part to hand-write. | Not worth it. A generator that copes with `CommitBuilder<'repo>`, `&mut MutableRepo` and non-`Send` trait objects is a project bigger than the crate. |
| 3 | Middle routes (macros, partial generators) | **Partial** | `macro_rules!` and pyo3's own `#[pyclass(eq, hash)]` remove about 700-1000 of 12,374 lines (6-8%). Most of that is in ids, async twins, `with_mut_repo` forwards, builder setters and Bookmark/Tag duplication. Generating the Python layer from stubs saves about 0 lines, because only 3 of its 2127 lines are delegation. | 1-2 days for the macros. A proc-macro is not justified. |

## Version check

`~/Code/jj` is **not** 0.46.0. It has no `v0.46.0` tag, and its workspace
`Cargo.toml` says `version = "0.45.1"`. `@` (a40c5ae4fc75, 2026-09-10) is 81
revisions past `v0.45.1`. All jj-lib reasoning below uses the crates.io source
at `~/.cargo/registry/src/index.crates.io-*/jj-lib-0.46.0`.
`pyjj-bindings/vendor/` holds only `revsets.toml`, not jj-lib.

## 1. Stub generation

### Options checked
- **pyo3 `experimental-inspect`** (pyo3 0.29.3, in registry) with **maturin 1.15
  `--generate-stubs`** (on PATH). No source annotations needed. This was tried.
- **pyo3-stub-gen 0.23.1** (crates.io, pyo3 `>=0.27,<0.30`, so it is compatible).
  It needs `#[gen_stub_pyclass]`/`#[gen_stub_pymethods]`/`#[gen_stub_pyfunction]`
  on every item (112 sites in this crate), a `stub_info` binary, and its own
  `create_exception!` wrapper. It gives the same result for more work. Not tried.

### Trial 1: feature flag only
Changed in the scratch `Cargo.toml`: `pyo3 = { ..., features = ["extension-module", "experimental-inspect"] }`.
`maturin build --generate-stubs -i python3 --offline` built in 2m10s (cold).
Log: `maturin-stubs.log`.
Result: a 6-line stub, `def __getattr__(name: str) -> Incomplete: ...`.
Cause: `lib.rs` uses a function-style `#[pymodule] fn pyjj_bindings(m)` with
`m.add_class`. pyo3 marks those modules incomplete (CHANGELOG #5207).

### Trial 2: declarative module
`mkdecl.py` rewrote the scratch `lib.rs` to `#[pymodule] mod pyjj_bindings { #[pymodule_export] use ...; }`,
with 91 exports plus `#[pymodule_export] const VERSION/__version__`. `cargo
check` passed with only the 7 pre-existing warnings. The rebuild took 50s
(log `maturin-stubs2.log`). The stub is at
`wheel2/pyjj_bindings/__init__.pyi`.

- 2816 lines, 65 classes, 473 `def`s, with docstrings carried over.
- Properties, `Sequence[str] | None = None` defaults and tuple returns are correct.
  `Cow<[u8]>`, `HashMap<..>` and `Vec<Option<String>>` map correctly.
- Exceptions are correct. `class JjError(Exception)` has `__new__(message)` and
  `message`, and all 15 `py_error!` subclasses derive from `JjError`.
  The crate has no `#[pyclass]` enums: `grep -B2 'enum '` over `src/*.rs`
  finds 0. So that pattern was not tested.
- **Invalid Python**: `ast.parse` fails at
  `def interdiff(self, /, from: Commit, ...)`. Both `ReadonlyRepo.interdiff`
  and `interdiff_files` have a parameter named `from`. Python callers cannot
  pass it by keyword anyway. The fix is to rename it in Rust (for example
  `from_`). After renaming, the stub parses.
- **`Any` returns in 28 methods**:
  - 17 `*_async` methods (`future_into_py` returns `Bound<PyAny>`).
  - 11 that return `Py<PyAny>` dicts: `view`, `git_fetch`, `git_fetch_all`,
    `git_import_refs`, `git_export_refs`, `git_push_*`, `snapshot`,
    `check_out`, `set_sparse_patterns`, `update_stale`.
  - Fix for async: pyo3 0.29 accepts a return annotation in
    `#[pyo3(signature = (...) -> "Awaitable[Commit]")]`. The annotation is a
    string literal (`PyTypeAnnotation(syn::LitStr)`,
    `pyo3-macros-backend-0.29.3/src/pyfunction/signature.rs:241`; pyo3 guide
    `type-stub.md:46`).
  - Fix for dicts: turn the 15 `PyDict::new` / 51 `set_item` sites into
    `#[pyclass(get_all)]` structs. That also gives typed results.
- **Missing**: `pyjj/_async.py` attaches 9 `Workspace.*_async` methods with
  `setattr` at import time. The stub cannot see them. They need a
  hand-written `.pyi` fragment, or they move to Rust.

Recommendation: adopt `experimental-inspect`. Ship the stub from the build
(maturin puts it in the wheel) and add a CI check that it parses and that
`mypy --strict` passes on `pyjj/`. "Experimental" means the feature can change
between pyo3 minor versions. The crate already pins pyo3 0.29, so the risk is
one re-check at each pyo3 bump.

## 2. Generating the wrapper code from jj-lib

### Hand classification (files named in the task)
Definitions: (a) one jj-lib call, no conversion beyond `map_err`. (b) a
type-table pattern: id newtype wrap/unwrap, `Arc` clone, `pollster::block_on`,
`with_mut_repo`, `spawn_blocking_py` twin, iterate the view and map to a py
struct, dunder methods. (c) multi-step logic, jj CLI behaviour reimplemented,
or the result reshaped for Python.

A method that only forwards to an in-crate helper (`crate::rewrite::squash(...)`)
takes the class of that helper. Of the 58 helpers that repo.rs reaches, 19
have bodies of 8 lines or fewer (b) and 39 are longer (c).

| File | Bound fns | a | b | c |
|---|---|---|---|---|
| ids.rs | 35 | ~9 (`hex`, field getters) | ~26 (hex ctor, repr/eq/hash) | 0 |
| bookmark.rs + tag.rs | 8 (+2 `from_target`) | 0 | 8 | 0 |
| repo.rs ReadonlyRepo | 42 | 3 | 18 + ~5 fwd | 6 + ~10 fwd |
| repo.rs Transaction | 66 | 0 | 19 + ~15 fwd | 2 + ~30 fwd |
| repo.rs CommitBuilder | 13 | 0 | 12 | 1 (`write` root guard) |
| **Sample total** | **164** | **12 (7%)** | **~103 (63%)** | **~49 (30%)** |

Examples of (c) in repo.rs: `start_transaction` (stamps the workspace name and
args the way the CLI does), `materialize_merge`, `resolve_single`(+`_async`),
the two `shortest_*_prefix_len` (they reimplement the CLI's
`revsets.short-prefixes` fallback), `new_commit` (merges the parent trees),
`rebase_descendants` (an options struct plus a counting callback), and
`CommitBuilder.write`.

### Crate-wide heuristic (`classify.py`, results in `fns.json`)
- 333 bound fns, 187 non-bound helper fns.
- Body lines: bound 2166, helpers 3502. The crate has 12,374 lines in total:
  2446 doc-comment lines, 839 blank lines, and about 8.9k code lines.
- Bound fns by bucket:
  - 136 short (8 body lines or fewer)
  - 72 thin forwards
  - 40 dunders
  - 17 async twins
  - 10 builder setters
  - 39 of 9-20 lines
  - 19 of more than 20 lines
- Estimate: about 73% of bound fns are (a)/(b) by count, but about 70% of
  body lines are (c). Of the helpers, 34 are longer than 30 lines. The
  largest are `operation_diff` (205), `add_workspace_inner` (112), `snapshot`
  (79), `op_abandon` (76) and `push_bookmark` (72).
- 77 lines in repo.rs (26 in workspace.rs, 25 in rewrite.rs) refer to a `jj`
  command or `cli/src` code that the method reproduces.
  That is CLI behaviour, not something jj-lib exposes.

### Generator sources
- **rustdoc JSON works without nightly.**
  `RUSTC_BOOTSTRAP=1 cargo rustdoc -p jj-lib --lib -- -Z unstable-options --output-format json`
  ran in 22s with warm deps and wrote format_version 60, 12 MB
  (`stubtry/target/doc/jj_lib.json`). It resolves paths, generics, `async`
  and reachability, so it is a better source than `syn` over the source tree.
  `syn` sees 995 `pub fn` (from `jjsigs.py`) but cannot tell which ones are
  reachable or what a type alias resolves to.
- **jj-lib 0.46.0 public surface** (`rdjson.py`): 944 reachable fns and
  inherent methods, and 36 public traits.

  | Kind | Count | Share |
  |---|---|---|
  | async | 161 | 17% |
  | generic / `impl Trait` | 137 | 15% |
  | named lifetime | 56 | 6% |
  | `dyn` | 56 | 6% |
  | closure | 14 | 1% |
  | otherwise "simple" | 520 | 55% |
  | simple and using only std types | 159 | 17% |

  140 methods take `&mut self`. The rest of the "simple" ones take or return
  jj-lib domain types (`Store`, `Commit`, `RepoPath`, `MergedTree`, `View`,
  ...). Each of those needs its own wrapper first, and that pulls in their
  whole transitive surface.

### Structural blockers that a generator cannot decide
- `CommitBuilder<'repo>` borrows `&mut MutableRepo`. The crate transmutes it to
  `'static` (repo.rs:1744). This is a per-type ownership design choice, and
  it is unsound as written (see Bugs).
- `Transaction` owns `MutableRepo`. The crate uses `RefCell<Option<Transaction>>`
  plus `take()` on commit, and `with_mut_repo` for every mutator.
  `#[pyclass(unsendable)]` is needed because `Box<dyn MutableIndex>` is not
  `Send`.
- `Workspace` holds `Box<dyn WorkingCopy>`, which is not `Sync`. The crate
  wraps it in a `Mutex` and releases the GIL with `py.detach`.
- jj-lib's async fns are not real non-blocking I/O, so each one needs a
  sync/async policy decision: `pollster::block_on`, or `spawn_blocking`.
- Errors: jj-lib 0.46.0 has 66 distinct `pub enum *Error` types, and the
  crate maps them to 15 Python classes. Which class each one maps to is a
  semantic choice.
- Iterators that borrow from the view (`local_bookmarks()`) must be collected
  into owned py structs.

## 3. Middle routes

| Route | Lines removed (est.) | Notes |
|---|---|---|
| `#[pyclass(eq, hash, frozen)]` (pyo3 0.29, supported by inspect) instead of hand `__eq__`/`__hash__` | ~120 | 18 dunders in ids.rs alone, plus Bookmark/Tag/Commit/Operation. |
| `hex_id!` macro for CommitId/ChangeId/TreeId/FileId | ~120 of ids.rs's 258 | ChangeId keeps `reverse_hex` as an extra arm. |
| Bookmark/Tag and RemoteBookmark/RemoteTag: one macro or generic, plus a shared `remote_ref_to_py` | ~100 of 191 + ~40 in repo.rs | `remote_bookmarks`/`remote_tags` and `get_bookmark`/`get_tag` are copy-paste twins in both ReadonlyRepo and Transaction. |
| `sync_and_async!` for the 17 `*_async` twins | ~150-250 | Removes duplicated bodies, for example `resolve_single_async` repeats `resolve_single`. An option that removes more: drop the Rust twins and use the anyio `to_thread` wrapper that `_async.py` already uses for Workspace. The Rust side only calls `spawn_blocking` anyway. |
| `tx_method!` for the ~60 `with_mut_repo(self, \|r\| crate::x::y(r, ...))` forwards | ~150-200 | The signatures and doc comments stay, so the gain is about 3 lines each. |
| CommitBuilder setter macro | ~50 | 10 setters with the same take/replace body. |
| `PyDict` stats into `#[pyclass(get_all)]` structs | about ±0 | Improves typing more than it saves lines (see Q1). |
| Generator only for id/value types | ~same as the macro rows | Not worth a build step when `macro_rules!` does it. |
| Python wrapper layer from stubs | ~0 | `pyjj/pyjj` has 2127 lines: `hunk.py` 890, `session.py` 574 and graph rendering 435 are real logic. 3 lines are `return self._x.y(` delegation. `_async.py` is already a 71-line `setattr` loop. |

Total: about 700-1000 lines, or 6-8% of 12,374. The crate already factors
errors (`py_error!`, `map_err_as!`, `IntoPyResult`), so less boilerplate
remains than the line count suggests. The 2446 doc-comment lines (20%) are
written by hand and record behaviour. A generator would lose them, not save
them.

## Bugs noticed in passing (not reviewed in depth)

1. **Unsound transmute** at repo.rs:1744. `PyCommitBuilder` holds a
   `CommitBuilder<'static>` that borrows `&mut MutableRepo` inside
   `PyTransaction.inner`. If Python keeps a builder after `Transaction.commit()`
   (which `take()`s the transaction) or after the transaction is dropped,
   `write()` reads freed memory. Each builder also holds a `&mut` alias while
   other `with_mut_repo` calls borrow the same repo mutably.
2. **Panic** at workspace.rs:556 (`clone_git`). `fetch_result.default_branch.as_ref().unwrap()`
   is reached when a `branches` pattern picked the working branch but the
   remote reported no default branch. The message is also wrong when the
   working branch is not the default branch.
3. **Panic** in ids.rs:26 `CommitId.short(n)`: `self.0.hex()[..n]` with `n > 40`
   raises `PanicException`, which is a `BaseException`, not a `JjError`.
4. **`__eq__` ignores `removed_ids`** on Bookmark/Tag (bookmark.rs:49,
   tag.rs:52). Two conflicted refs with different removed sides compare
   equal.
5. **Misplaced doc comments**. `squash_edited` carries the doc of
   `split_selected` (repo.rs:1154-1161), so `split_selected` has none.
   "Commit this transaction and publish the operation." sits on
   `set_attribute` (repo.rs:1696), not on `commit()`. Stubs would show both
   errors.
6. Seven pyo3 deprecation warnings (`HasAutomaticFromPyObject`) on converge.rs
   pyclasses that lack `from_py_object`/`skip_from_py_object`.

## Files in this scratchpad
- `classify.py`, `fns.json`: per-fn classifier over the crate
- `jjsigs.py`, `jjsigs.out`: `syn`-style scan of jj-lib signatures
- `rdjson.py`, `rdjson.out`: rustdoc-JSON classification of jj-lib
- `stubtry/`: scratch crate copy (feature flag plus declarative `lib.rs`; the original is in `src/lib.rs.orig`)
- `mkdecl.py`: generator for the declarative `lib.rs`
- `maturin-stubs.log`, `maturin-stubs2.log`, `rustdoc.log`: build logs
- `wheel2/pyjj_bindings/__init__.pyi`: the generated stub
