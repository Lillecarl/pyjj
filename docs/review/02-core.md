# 02: core of pyjj-bindings, with a crate-wide async/GIL audit

Read-only. Nothing in `~/Code/pyjj` changed. Probes ran against the wheel that
01 built (`wheel2/`, current source plus `experimental-inspect`), with a nix
Python 3.14 env that has anyio and trio. Scratchpad =
`/tmp/claude-1000/-home-lillecarl-Code-pyjj/ec083ca3-e535-474a-b178-c438dd3554da/scratchpad`.

Evidence files (all in the scratchpad):
- `gilaudit.py`, `gilaudit.json`, `gilaudit.out`: name-based call graph, bound fn -> blocking work, detach yes/no.
- `asynctest.py`, `asynctest.log`: async twins under asyncio / anyio-asyncio / anyio-trio, GIL ticker, id and exception probes.
- `deadlock.py`, `deadlock.log`: anyio `snapshot_async` plus a getter on the loop thread. 3 of 3 hang.
- `deadlock_threads.py`, `deadlock_threads.log`: the same with two plain threads, no event loop. 2 of 2 hang.
- `ids.log`: id comparison probes.

`cli/src/config.rs` line numbers below are from `~/Code/jj` (0.45.1+81), used
for context only. jj-lib line numbers are from the 0.46.0 registry source.

## Part A. Async/GIL audit (whole crate)

### A1. What blocks, and who holds the GIL while it does

`gilaudit.out` (heuristic, an upper bound; its regex treats some tokens such as
`ReadonlyRepo` as blocking):

| | count |
|---|---|
| bound fns (non-dunder) | 293 |
| reach blocking jj-lib work | 149 |
| ... with the GIL held (no `detach`, no `spawn_blocking_py`) | 119 |
| use `py.detach` | 14 (12 workspace.rs, 2 run.rs) |
| have a Rust `_async` twin | 17 (repo.rs 7, commit.rs 10) |

`pollster::block_on` appears at about 255 sites in 24 files. Only `aio.rs`
touches tokio.

Measured: 200 iterations of `repo.revset(...)` + `commit.is_empty(repo)`
took 42 ms. A Python ticker thread that sleeps 0.5 ms advanced 5 times, not
about 84 (`asynctest.log`). The sync path holds the GIL.

Sites I read end to end (not heuristic):
- `Transaction.git_fetch`, `git_fetch_all`, `git_push_updates`, `git_push_bookmark` (repo.rs:1110,1128,1672,1685 -> git.rs:341,477,602): spawn a `git` subprocess and wait on the network with the GIL held.
- `Transaction.commit` (repo.rs:1708): op-store and index writes, `pollster::block_on(tx.commit(..))`, GIL held.
- `ReadonlyRepo.revset`, `resolve_single`, `log_graph`, `interdiff`, `operation_diff`, `shortest_*_prefix_len`: GIL held. Some have an async twin, the sync form still holds the GIL.
- `Commit.is_hidden`, `is_divergent`, `change_offset`, `diff_from_parents`, `diff_stats`, `git_diff`, `annotate` and others (commit.rs:121-447): GIL held.
- `Workspace.load`, `init_internal_git`, `init_colocated_git`, `init_external_git`, `is_colocated`, `create_git_worktree`, `unlink_git_worktree` (workspace.rs:269-684): GIL held. `init_*` and `load` have no async twin in `_async.py`.
- `UserSettings()`, `UserSettings.for_repo`, `with_command_args` (settings.rs:134,155,183): config file reads with the GIL held. Small, but they are the first call of every program.
- All 18 `debug_*` pyfunctions (debug.rs): GIL held; the Workspace-taking ones also lock the Workspace mutex under the GIL (see B1).

Consequence: `anyio.to_thread.run_sync(repo.revset, ...)` does not free the
event loop today. The `_async.py` approach works for Workspace only because
those Workspace methods detach.

### A2. pollster and tokio: can it deadlock or starve?

No, as deployed (verified by reading, the watchman path not run):
- `spawn_blocking_py` (aio.rs:338) is the only tokio entry. It always goes through `tokio::task::spawn_blocking`, so every `pollster::block_on` in an async twin runs on a blocking-pool thread, never on a runtime worker. No worker starvation.
- Sync callers run outside any runtime context.
- One subtle path: jj-lib's watchman code (`local_working_copy.rs:1249,1277`) checks `Handle::try_current()`. On a `spawn_blocking` thread that succeeds, so jj-lib awaits tokio I/O futures directly under `pollster`. That works only because pyo3-async-runtimes builds a multi-thread runtime with `enable_all()` (`pyo3-async-runtimes-0.29.0/src/tokio.rs:204-205`), so another thread drives the reactor. Under a current-thread runtime it would hang. No async twin reaches watchman today (snapshot is Workspace-only), so this is latent.
- `spawn_blocking` work cannot be cancelled. An asyncio cancel drops the result; the jj-lib work runs to the end.

### A3. Async surface: two mechanisms, split by module

| Mechanism | Where | Count | trio | Typed |
|---|---|---|---|---|
| Rust `future_into_py` + `spawn_blocking` | ReadonlyRepo, Commit | 17 | **fails** | `-> Any` |
| Python `anyio.to_thread.run_sync`, `setattr` at import | Workspace | 9 | works | invisible |
| none | Transaction, CommitBuilder, Bisector, RunPool, debug, settings, every other method | rest | - | - |

Measured (`asynctest.log`):
```
asyncio        rust_async OK    py_async OK
anyio-asyncio  rust_async OK    py_async OK
anyio-trio     rust_async FAIL RuntimeError no running event loop   py_async OK
```
The Rust twins call `asyncio.get_running_loop()` (pyo3-async-runtimes
`generic.rs:103`), so every Rust `_async` method raises under trio at call
time. Under anyio's asyncio backend they work.

Gaps in the twin coverage: `interdiff`, `commits_graph`, `evolution_log`,
`operation_diff`, `shortest_*`, `find_divergent_changes` on ReadonlyRepo, and
`untrack_paths`, `reset`, `op_abandon`, `load`, `init_*` on Workspace, have
no async form. The three Workspace ones already detach, so only the
`_async.py` tuple is missing them.

### A4. `pyjj/pyjj/_async.py`

- It mutates `pyjj_bindings.Workspace` at import of `pyjj` (`pyjj/__init__.py:76`). A user who imports only `pyjj_bindings` gets no `_async` methods. It works only because pyo3 type objects are mutable by default; `#[pyclass(immutable_type)]` or a future pyo3 default breaks it with `TypeError`.
- Type checkers cannot see the 9 methods (01 noted the stub gap). Also no `from __future__ import annotations` and no annotations at all, against the house rubric.
- `functools.wraps` copies `__name__`, `__qualname__` and the docstring of the sync method, so `Workspace.snapshot_async.__name__ == "snapshot"` and tracebacks and docs name the wrong method.
- The docstring says the Rust side releases the GIL "for the duration of each call". True for the 9 listed, untrue for the class as a whole (A1).
- anyio semantics are right: `run_sync` without `abandon_on_cancel` waits for the thread, so a cancelled `snapshot_async` does not leave the working-copy lock half-held.
- Two thread pools exist side by side: anyio's limiter (40) for Workspace and tokio's blocking pool (512) for ReadonlyRepo/Commit.

### A5. The single pattern to adopt

1. **Every bound fn that reaches jj-lib I/O runs its body inside `py.detach`, and the body returns plain Rust values.** Conversion to Python happens after `detach` returns. No `Python::attach` inside a detach region (B1 shows why). `PyDict` stats become `#[pyclass(get_all)]` structs built from Rust structs, which 01 already wants for typing.
2. **The async surface is Python, explicit and typed:** one `async def x_async(self, ...) -> T: return await anyio.to_thread.run_sync(partial(self.x, ...))` per method, written in a `pyjj` subclass or wrapper (or generated from the stub), never `setattr` on the extension type. Drop the 17 Rust twins, `aio.rs`, `pyo3-async-runtimes` and `tokio`. That gives trio support, real return types, one thread pool, and one cancellation semantic. The Rust twins buy nothing over this: they already run jj-lib synchronously on a pool thread.
3. **Transaction is the wall.** `&mut MutableRepo` is `!Send`, so `py.detach` cannot capture it without `unsafe`. Two routes:
   - (a, recommended) Give `ReadonlyRepo`/`Workspace` methods that open, run and commit their own transaction inside `detach` for the long operations (fetch, push, rebase, fix, absorb), the way `Workspace.snapshot` already does. No `unsafe`.
   - (b) An `AssertUngil<T>` newtype with `unsafe impl Send` around the `&mut MutableRepo`. Sound only because `detach` stays on the same OS thread and the closure touches no Python object; pyo3's `unsendable` check turns access from another thread into a panic, not UB. Releases the GIL for other threads, but does not free the event loop thread itself.

## Part B. Findings

### [high] Workspace mutex and GIL taken in opposite orders: process-wide deadlock
- Where: lock taken, then GIL re-taken inside `detach`: checkout.rs:132,184,314 (`Python::attach` in `snapshot`/`check_out` while `self.inner` is locked at workspace.rs:723,755), workspace.rs:842,893, workspace.rs:185 (nested `set_sparse_patterns` under the outer lock), git.rs:70,125,367,490,563,630,657 when reached from a detached Workspace method. GIL held, then lock taken: getters workspace.rs:589 (`workspace_root`), 600, 615, 635, 646, 859, and `lock().unwrap()` in 12 debug.rs pyfunctions.
- What: thread A runs `snapshot` → `detach` → locks the Workspace mutex → `Python::attach` waits for the GIL. Thread B holds the GIL and calls `ws.workspace_root` → waits for the mutex. Neither moves.
- Why it matters: the natural `_async.py` usage hangs the interpreter for good: `await ws.snapshot_async(...)` in one anyio task while another task reads `ws.workspace_root`. Measured 3/3 hangs (`deadlock.log`, 30 s timeout; control without the getter finishes in 2.3 s) and 2/2 with two plain threads and no event loop (`deadlock_threads.log`).
- Fix: never attach while the mutex is held. Return Rust structs from `checkout::*`, `git::*` and convert after `detach`. Never lock while attached: `workspace_root`, `workspace_path`, `repo_path` do not change for the object's lifetime, so store them beside the `Mutex`; `workspace_name` changes on rename, so read it inside `detach`.

### [high] Repo/workspace config errors are swallowed, so `immutable_heads()` silently stops applying
- Where: config.rs:241-249 (`existing_scoped_config`, `.ok()??`), used by config.rs:266-269 (`load_config_for_repo` → `UserSettings.for_repo`).
- What: every `SecureConfigError` becomes "no config". jj-lib returns errors for a malformed `config-id` (`BadConfigIdError`, jj-lib-0.46.0 `secure_config.rs:375-378`), unreadable metadata, or a failed write. jj's CLI propagates them (`cli/src/config.rs:455-466`, `?`). pyjj also drops `LoadedSecureConfig.warnings`, which jj prints (migration, copied repo, config not found).
- Why it matters: the module doc (config.rs:27-29) names this exact outcome as the danger: a corrupted `.jj/repo/config-id` makes `for_repo` load without the repo layer, so `immutable_heads()` set with `jj config set --repo` is ignored and a rewrite jj refuses goes through. No error, no warning.
- Fix: return `Result` from `existing_scoped_config`, map to a `ConfigError` class, and return the warnings (list on `UserSettings`, or `warnings.warn`).

### [medium] `existing_scoped_config` documents "reading never creates", but it writes
- Where: config.rs:230-235 (doc) and the `maybe_load_config` call through secure_config.rs:354.
- What: jj-lib's `maybe_load_config` migrates a legacy `.jj/repo/config.toml` (new dir plus symlink), regenerates missing metadata (`generate_initial_config`), copies the config when it detects a copied repo, and updates metadata when the repo moved (jj-lib-0.46.0 `secure_config.rs:219-310,359-406`).
- Why it matters: `UserSettings.for_repo` on a read-only inspection writes into `~/.config/jj/repos` and `.jj/repo`. On a read-only checkout the write fails, and with the finding above the failure is silent.
- Fix: correct the doc, or name the side effect in `for_repo`'s docstring. The behaviour itself matches jj.

### [medium] Workspace config layer is labelled `ConfigSource::Repo`
- Where: config.rs:266-269.
- What: both scoped files load with `ConfigSource::Repo`. jj uses `ConfigSource::Workspace` for the workspace file (`cli/src/config.rs:659-663`).
- Why it matters: precedence is still right (insertion order), but `UserSettings.config_layers()` reports `source == "repo"` for workspace settings, so `jj config list` with a `source` template shows the wrong scope, and any caller that removes or selects layers by source gets the wrong one.
- Fix: map `"repo"` → `Repo`, `"workspace"` → `Workspace`.

### [medium] Error taxonomy: class chosen per call site, source chain dropped
- Where: errors.rs:263-306 and all callers. 133 `map_py_err` (generic `JjError`) + 111 ad-hoc `JjError::new_err(...)`, against 3-110 uses per specific helper (`map_backend_err` 110, `map_revset_eval_err` 36, `map_index_err` 4, `map_revset_parse_err` 1 site).
- What: the same jj-lib error type lands in different classes at different sites; `map_err_as!` uses `err.to_string()`, which drops the `source()` chain. Only settings.rs has `error_chain_body`. `RepoInitError` is defined and exported but never raised. Unknown revset symbols (`resolve_user_expression`) raise `RevsetEvalError`, not a resolution or parse class. Config failures have no class (`JjError`).
- Why it matters: `except BackendError` cannot be relied on, and messages lose the cause jj prints (jj-lib errors carry the cause in `#[source]`, so the user sees "Error when reading object X" with no reason).
- Fix: a sealed `trait JjErrorClass { fn py_err(self) -> PyErr; }` implemented once per jj-lib error type (orphan rule blocks `From<E> for PyErr`), plus a `.py()?` extension on `Result<T, E: JjErrorClass>`. Format with the chain (`error_chain_body`) in one place. Add `ConfigError`, drop or use `RepoInitError`.

### [medium] Errors swallowed to defaults
- Where: commit.rs:171,183,189,201 (`is_empty`, `is_discardable` and twins: `.unwrap_or(false)`), config.rs:247 (above), secure_config.rs:370 (`read_metadata` any error → `None`, including permission errors).
- What: a backend read failure reports "not empty" / "not discardable" instead of raising.
- Why it matters: callers that abandon or hide discardable commits decide on a value that is an I/O error.
- Fix: return `PyResult<bool>`; in secure_config.rs map only `NotFound` to `None`.

### [medium] `IndexError` shadows the builtin and is not a `LookupError`
- Where: errors.rs:240; re-exported in pyjj/__init__.py.
- What: `from pyjj import IndexError` (or `*`) replaces Python's `IndexError` in that module. `issubclass(pyjj_bindings.IndexError, LookupError)` is `False` (`asynctest.log`).
- Why it matters: `except IndexError` around list code in a module that imported it catches the wrong thing and misses real index errors.
- Fix: rename to `JjIndexError` or `RepoIndexError`.

### [medium] Panic handling differs between sync and async paths; mutex poisoning is permanent
- Where: aio.rs:344-348 (`JoinError` → `JjError`); 31 `lock().unwrap()` (workspace.rs 19, debug.rs 12).
- What: a panic in a sync method escapes as `PanicException` (a `BaseException`); the same panic in an async twin becomes `JjError`. Any panic while the Workspace mutex is held poisons it, and every later call on that object raises `PanicException`.
- Fix: `lock().unwrap_or_else(PoisonError::into_inner)` (jj's on-disk lock is the real guard) or map poisoning to `WorkingCopyError`. Decide one panic policy; the cleanest is to keep `PanicException` everywhere and remove the reachable panics.

### [medium] `repo_configs_root_dir` re-derives the config dir differently from `secure_config_root`
- Where: secure_config.rs:393-404 vs config.rs:222-228.
- What: the first reads `$XDG_CONFIG_HOME` / `$HOME/.config` by hand; the second uses `etcetera::choose_base_strategy()`. etcetera ignores a relative `XDG_CONFIG_HOME` (etcetera xdg.rs:175-180) and uses the Windows strategy on Windows.
- Why it matters: with `XDG_CONFIG_HOME=rel/dir` (or on Windows), `jj config gc` via pyjj scans a directory that jj never writes.
- Fix: `secure_config_root("repos")`.

### [medium] Id types: hand-written eq/hash, two unhashable, ChangeId does not round-trip
- Where: ids.rs (all 6 classes).
- What: `CommitId`, `ChangeId`, `Timestamp`, `Signature` derive `PartialEq, Eq, Hash` and then hand-write `__eq__`/`__hash__` (4 copies of the same hasher). `TreeId` and `FileId` define `__eq__` without `__hash__`, so `hash(TreeId(...))` raises `TypeError: unhashable type` (`asynctest.log`). `ChangeId(hex)` takes forward hex but `str()`/`repr()` print reverse hex, so `ChangeId(str(cid))` raises `JjError` (`ids.log`). No ordering, so `sorted(ids)` fails. Every class has `__module__ == "builtins"` (no `module = "pyjj_bindings"`), so exceptions do not pickle (`PicklingError`), which breaks error propagation through `ProcessPoolExecutor`/multiprocessing.
- Fix: `#[pyclass(frozen, eq, hash, ord, module = "pyjj_bindings")]` plus a `hex_id!` macro (01 sized it); `ChangeId.from_reverse_hex` or accept both forms; `repr` as `ChangeId("…")` that evaluates back; `module = ...` on every pyclass and on `py_error!`.

### [low] Four config getters duplicate parse-and-NotFound logic
- Where: settings.rs:263-315.
- Fix: one generic `fn get_opt<T: DeserializeOwned>(&self, key) -> PyResult<Option<T>>` and four one-line wrappers.

### [low] `load_default_config` and `load_config_for_repo` duplicate the layer prelude
- Where: config.rs:206-214, 257-273. Fix: one function with `Option<(repo_path, workspace_root)>`.

### [low] Stringly scopes and arg kinds
- Where: secure_config.rs:301-319 (`kind: &str` "repo"/"workspace", matched twice), config.rs:266, settings.rs:188-222 (`"config"`/`"config-file"`).
- Fix: a pyo3 enum (`#[pyclass(eq)] enum ConfigScope`) or `Literal[...]` in the stub.

### [low] `flatten_layer` key quoting is not TOML
- Where: settings.rs:29-38.
- What: a top-level key is never quoted; nested non-bare keys use Rust `{:?}` (Rust escapes such as `\u{7f}`, not TOML); `is_alphanumeric` accepts non-ASCII letters, which TOML bare keys do not.
- Fix: use `toml_edit::Key::display_repr()`.

### [low] `ConfigLayer.entries` is a `HashMap`, so document order is lost (PLAUSIBLE impact)
- Where: settings.rs:15. pyjj-cli sorts the keys (`config_list.py:58`); whether jj prints in document order was not checked.

### [low] Module registration is one long imperative list
- Where: lib.rs:68-175. Extends 01's declarative-module finding: the 18-item debug loop and the mixed `use` / `crate::x::Py*` spellings go away with `#[pymodule] mod`.

## Not re-reported (01 owns them)
`CommitId.short` panic (ids.rs:26; reproduced, `PanicException`), `clone_git` unwrap, CommitBuilder transmute, Bookmark/Tag `__eq__`, `from` parameter, stub gaps.
