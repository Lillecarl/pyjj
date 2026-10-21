# pyjj review: summary of 01-05

Scope: `pyjj-bindings/src/*.rs` and `pyjj/pyjj/*.py`. All five reviews are
read-only. Probes ran against `wheel2/` (01's build of the current source).
Each item names its source report. Full detail is in that report.

## Codegen verdict (01)

- Stubs: **yes**. pyo3 `experimental-inspect` plus `maturin --generate-stubs` gives a 2816-line stub. Two small blockers: the function-style `#[pymodule]`, and a parameter named `from`. About 0.5-1 day.
- Generating the wrappers from jj-lib: **no**. About 70% of the body lines are real adaptation. A generator would emit unused code and leave the hard part.
- Macros: **partly**. They remove about 700-1000 of 12,374 lines (6-8%).

## Counts

| report | critical | high | medium | low |
|---|---|---|---|---|
| 01 codegen (6 bugs in passing, not rated by 01; rated here) | 1 | 2 | 2 | 1 |
| 02 core + async/GIL audit | 0 | 2 (+ A1 audit) | 8 | 6 |
| 03 repo/workspace/commit | 1 (same as 01) | 4 | 9 | 4 |
| 04 leaf Rust | 1 | 7 | 7 | 5 |
| 05 Python wrapper | 0 | 4 | 15 | 7 |

## Critical

1. CommitBuilder `'static` transmute: use-after-free and aliased `&mut MutableRepo`, SIGSEGV reproduced. repo.rs:1737,1744 (01, 03).
2. `ReadonlyRepo.gc()` defaults to "expire now" and sweeps from a stale operation. It deletes the head operation and the repo stops loading. repo.rs:619-621, gc.rs:36-51 (04).

## High

Concurrency and the GIL
- Workspace mutex and GIL taken in opposite orders: process-wide deadlock, 3/3 reproduced. checkout.rs:132,184,314; workspace.rs:589-646,723,755 (02).
- 119 bound fns hold the GIL during blocking jj-lib work, including git fetch/push and `Transaction.commit`. `to_thread` frees nothing for them. repo.rs:1110,1128,1672,1685,1708 and others (02 A1).

Data loss or a wrong repository state
- `snapshot` of a stale working copy reverts a rewrite of `@` made elsewhere. checkout.rs:88-195 (04).
- `snapshot` amends an immutable `@`, ignores the global gitignore and `snapshot.auto-track`. checkout.rs:115-121,145 (04).
- Repo/workspace config errors are swallowed, so `immutable_heads()` silently stops applying. config.rs:241-249 (02).
- `rebase_descendants` ignores the immutable set. repo.rs:941-945 (03).
- Git import ignores `abandon-unreachable-commits` and `auto-track-bookmarks`. git.rs:56-62 (04).
- `fix` keys files by content hash, so one result lands on every path with the same bytes. fix.rs:84,157 (04).
- Hunk selection with `paths=None` moves every other change; a full deletion becomes an empty file. rewrite.rs:81-152 (04).
- Python spec path does the same deletion-to-empty-file. hunk.py:814-866 (05, extends 04).
- Python (difflib) and Rust (jj) number hunks differently: 105/304 cases disagree. hunks.rs:86-131, hunk.py:259-312 (04).
- Per-hunk `lines` with an `id` selects the whole hunk under pydantic. hunk.py:356-373 (05).
- `Atomic.split` moves `@` onto the remainder for any revision. session.py:419 (05).
- `Atomic.rebase(after=)` resolves children in the starting repo, not the transaction. session.py:450-453 (05).
- `clone_git` leaves a partly built destination on failure. workspace.rs:379-571 (03).
- Workspace-level transactions are not stamped, so the 0.46 cross-workspace undo guard skips them. workspace.rs:172,412,522,553,1029,1088 (03).

Panics that escape as `PanicException`
- `Transaction.commit()` without `rebase_descendants()`: panic, and the transaction is lost. repo.rs:1708-1712 (03).
- Any path string goes into a tree: `""` panics; `..`, `.git/...`, `.jj/...` are written. tree.rs:18-20 (04).
- `clone_git` `unwrap()` on the default branch. workspace.rs:556 (01).
- `CommitId.short(n)` with `n > 40`. ids.rs:26 (01, 02).

## Medium, by theme

- **Async and typing surface**: two async mechanisms (Rust twins fail under trio, `setattr` twins are invisible) (02 A3/A4). 28 `-> Any` returns and an unparseable stub (01). No `py.typed`; mypy `--strict` gives 86 errors; session.py is untyped (05). The session API has no async form (05).
- **Error model**: the class is chosen per call site and the source chain is dropped (02). Backend errors become `False` (02). `IndexError` shadows the builtin (02). Panic policy and mutex poisoning (02). `PyjjError` hides the jj class (05). CLI wording lives in Rust (04).
- **jj parity**: workspace layer labelled `Repo` (02); queries load at head and can write an op (03); `update_stale` on a sibling op (03); rename before lock (03); sparse default (03); `push_bookmark` skips jj's checks (04); `at_operation()` to a newer op (04); two settings objects per transaction (03); `Atomic.new` leaks empty commits; `squash` on a merge (05).
- **Wrapper correctness**: a failed block still writes the snapshot, and the commit phase is outside the guard (05); hunk line semantics and silent binary handling (05); `resolve_abandons` emits duplicate parents (05); `RunPool.acquire` cannot be interrupted (04).
- **DRY**: macros for ids, twins and forwards (01); a transaction helper for 7 sites (03); PyDict stats into pyclasses (01, 03, 04); converge triplets and git stats (04); two hunk validators and 150 lines of re-exports (05); graph layout twice: Rust renderdag should own it (04, 05).
- **API shape**: redundant arguments, stringly enums, bare tuples, no keyword-only arguments, `str` paths (03); id types unhashable, ChangeId does not round-trip, no `module=` (02).
- **Packaging**: `requires-python >=3.9` is false; pygraphviz is a core dependency; no lint or type config (05).

## Fix order

Fixes that share a root cause are grouped. Do each group as one change set.

1. **Memory safety.** Use `DetachedCommitBuilder` with `Py<PyTransaction>` and one `tx_mut()` accessor (03). This removes the transmute, gives one "transaction finished" error, and drops the `repo` argument of `write()` and the dead `_repo` field (03). In the same pass, check `has_rewrites()` in `commit()`, or rebase automatically (03).
2. **Data-loss guards.** `gc`: head check, 14-day default, checked `Duration` (04). One `snapshot_options()` helper with `check_stale`, base ignores, auto-track and an immutable `@` (04). This also removes the prelude duplication in checkout.rs and run.rs.
3. **The detach pattern (02 A5).** Each bound fn runs its jj-lib work inside `py.detach` and returns Rust values. Convert to Python after that. Never attach while the Workspace mutex is held. This one change fixes the deadlock and the GIL audit. Typed `#[pyclass(get_all)]` results replace the PyDict stats (01, 03, 04 DRY). Then the async surface becomes typed Python `anyio.to_thread` wrappers: drop the 17 Rust twins, `aio.rs`, tokio and the `setattr` in `_async.py`. trio then works (02 A3). Long Transaction work moves to self-contained repo methods (02 A5a).
4. **One transaction helper** `open_tx(repo, settings, ws_name, args)` (03). It stamps the workspace and args, fixes the start time, and removes 7 copies. Add `rebase_descendants` with the immutable set, and one settings object per repo (03).
5. **Honour the user's config.** Propagate config errors and warnings; use `ConfigSource::Workspace` (02). Use `GitSettings`/`RemoteSettings` for import and fetch (04). Report alias errors as warnings (04).
6. **Hunks, one model.** Rust owns diffing, numbering, ids and ranges (04). Track file presence in Rust `select` and in Python `spec_to_overrides` (04, 05). Keep one pydantic validator and delete the fallback, the stub and the dead code (05). Fix the `fix` key (04). Fix `Atomic.split` and `Atomic.rebase` in the same pass (05).
7. **Inputs and panics.** Validate repo paths (04). Fix `CommitId.short` and the `clone_git` unwrap (01), the debug unwrap (04) and lock poisoning (02). Then decide one panic policy. Add `clone_git` cleanup (03).
8. **Error taxonomy.** A `JjErrorClass` trait with the source chain, a `ConfigError`, and a renamed `IndexError` (02). `PyjjError` keeps the jj class (05). Return data, not CLI text (04).
9. **Types and packaging.** Use the declarative module, `experimental-inspect` and rename `from` (01). Ship `py.typed`. Build `pyjj.__all__` from the stub. Set `requires-python >=3.11` and move pygraphviz to an extra. Gate CI on ruff and `mypy --strict` (05).
10. **Shape and DRY.** Add the macros (01). Use keyword-only arguments, enums and `PathBuf` (03). Expose renderdag rows to Python and make graph_layout.py a glyph adapter (04, 05).

Groups 1 and 2 stop crashes and data loss. Group 3 has the largest reach: one pattern closes the deadlock, the GIL audit, the async split and most of the typing gap.
