# 03: repo.rs, workspace.rs, commit.rs

Read-only. Nothing in `~/Code/pyjj` changed. jj-lib line numbers are from the
0.46.0 registry source. jj-cli 0.46.0 is not in the registry, so CLI line
numbers are from `~/Code/jj` (0.45.1+81) and are context only.

Evidence (scratchpad):
- `txprobe.py`, `txprobe.log`: Transaction/CommitBuilder probes against `wheel2/`, one subprocess per case.

GIL held during blocking work, the Workspace mutex/GIL deadlock, the error
taxonomy, the async split, `lock().unwrap()` poisoning and `unwrap_or(false)`
in `is_empty`/`is_discardable`: see 02. Not repeated here.

Counts: 1 critical, 4 high, 9 medium, 4 low.

### [critical] CommitBuilder `'static` transmute: use-after-free and aliased `&mut MutableRepo`
- Where: repo.rs:1737 (field `Option<CommitBuilder<'static>>`), repo.rs:1744 (transmute). Every `PyCommitBuilder::from_rust` caller inherits it: 18 sites, in repo.rs (`new_commit` 742, `rewrite_commit` 754), rewrite.rs, conflicts.rs and revert.rs. Every Transaction method that returns `CommitBuilder` (`squash`, `split_*`, `edit_commit_tree`, `resolve_conflict(s)`, `pick_conflict_sides`, `revert_commit`, `set_executable`, `restore`) gets the builder this way.
- What: jj-lib's `CommitBuilder<'repo>` holds `mut_repo: &'repo mut MutableRepo` (commit_builder.rs:42-43). The `MutableRepo` sits by value in `PyTransaction.inner: RefCell<Option<Transaction>>`. `PyCommitBuilder` holds no reference to the `PyTransaction`, so nothing keeps the repo alive or in place.
  - (a) Use-after-free. `Transaction.commit()` (1709) `take()`s the transaction out of the RefCell and consumes it. The builder still points at the old slot. A later `write()`/`abandon()` reaches `mut_repo.is_backed_by_default_index()`, `add_head`, etc. (commit_builder.rs:401-464) through freed `Arc`/`HashMap`/`Box<dyn MutableIndex>` pointers. Dropping the Python `Transaction` frees the whole object.
  - (b) Aliasing. While a builder is alive, every `with_mut_repo` call (691-700) creates a second `&mut MutableRepo`. That is UB under Rust's aliasing rules even when nothing crashes (e.g. `b = tx.rewrite_commit(...); tx.set_bookmark(...); b.write(repo)`).
- Reproduced (`txprobe.log`): both crash with SIGSEGV (exit -11).
  - `builder = tx.new_commit(s, [root]); tx.commit("x"); builder.write(repo)`.
  - `builder = repo.start_transaction(s).new_commit(s, [root])`: a one-line chain, so the temporary transaction is gone at once.
- Fix: jj-lib already has the owned form. `CommitBuilder::detach() -> DetachedCommitBuilder` (commit_builder.rs:50) and `DetachedCommitBuilder::attach(&mut MutableRepo)` (276). `DetachedCommitBuilder` has every setter pyjj forwards (`set_description/author/committer/parents/predecessors/change_id/sign_behavior`, `generate_new_change_id`, `clear_rewrite_source`, `parents`, `predecessors`, `change_id`). The CLI uses it the same way (`workspace/add.rs:145`).
  - Shape: `PyCommitBuilder { inner: Option<DetachedCommitBuilder>, tx: Py<PyTransaction> }`, built with `builder.detach()`.
  - `write(py)` = `with_mut_repo(&tx, |r| block_on(b.write(r)))`; `abandon()` the same way.
  - Results: no `unsafe`; a write after `commit()` raises the one `TransactionError`; `write()` no longer needs the `repo` argument (see the `_repo` finding below). The root check can use the builder's own store.

### [high] `Transaction.commit()` without `rebase_descendants()` raises PanicException and loses the transaction
- Where: repo.rs:1708-1712, and jj-lib transaction.rs:141-144 (`assert!(!mut_repo.has_rewrites(), "BUG: Descendants have not been rebased...")`.
- What: `commit()` `take()`s the transaction first. Then `tx.commit()` asserts. The panic surfaces as `pyo3_runtime.PanicException`, which is a `BaseException`, not a `JjError`. The transaction is already gone: `repr(tx)` reads `Transaction(consumed)`, so the caller cannot call `rebase_descendants()` and retry. All its in-memory work is lost.
- Reproduced (`txprobe.log`, `commit_without_rebase`): rewrite a commit that has a child, then `commit()`.
- Why: every rewrite (`rewrite_commit().write`, `abandon_commit`, `edit` abandoning the old `@`, `squash`, ...) sets up this trap. The docstrings tell callers to call `rebase_descendants()` first, so a forgotten call is the expected mistake. The jj CLI never meets the assert, because `finish()` always rebases (cli_util.rs:2852).
- Fix: before the `take()`, check `MutableRepo::has_rewrites()` (pub, jj-lib repo.rs:1175). Either raise `TransactionError("call rebase_descendants() first")`, or rebase automatically as the CLI does and return or report the count.

### [high] `rebase_descendants` ignores the immutable set
- Where: repo.rs:941-945 (`rebase_descendants_with_options(&RevsetExpression::none(), ...)`).
- What: jj passes `resolve_immutable_expression(tx.base_repo())` (cli_util.rs:2983-2998, `rebase_mutable_descendants`). Its comment says why: "jj git fetch can update immutable commits ... Their immutable descendants shouldn't be rebased." jj-lib repo.rs:1570-1572: "Commits within the `immutable` set are left unchanged, which also prevents their further descendants from being rebased."
- Why it matters: after `git_fetch`/`git_import_refs` abandons or moves commits, `session.py:198` (`rebase_descendants(False)`) rewrites immutable descendants that jj leaves alone. The result is new commit ids for shared history. Verified by reading. The exact repo shape is PLAUSIBLE: it needs an immutable commit that descends from an abandoned one, for example through a configured `immutable_heads()`.
- Fix: `rebase_descendants(settings=None, *, delete_abandoned_bookmarks=False)`, which resolves `immutable_heads()` against the base repo. `rewrite::check_rewritable` already does this resolution.

### [high] Workspace-level transactions are not stamped with the workspace, so the 0.46 undo guard skips them
- Where: `JjTransaction::new(mut_repo, &settings.0)` at workspace.rs:172 (`add_workspace`), 412, 522 and 553 (`clone_git`), 1029 (`forget_workspaces`), 1088 (`rename_workspace`). Compare repo.rs:81-84, which stamps. Related: `undo`/`redo` (repo.rs:1633-1664) default `workspace_name=None`.
- What: none of the six sites calls `set_workspace_name` or sets `args`. The jj CLI stamps both on every transaction (`start_repo_transaction`, cli_util.rs:2939-2950). `check_cross_workspace` (oplog.rs:36-38) returns `Ok` when an operation has no workspace name.
- Why it matters:
  - Undoing a `forget`, `rename`, `add` or `clone` operation from another workspace goes through. jj refuses it without `--allow-cross-workspace`.
  - `jj op log` shows these operations without a workspace or command line.
  - `undo()` with no argument skips the check for every operation, although the transaction knows its own `workspace_name` (repo.rs:687).
  - The operation start time is also wrong: `Transaction::new` records `start = now` (jj-lib transaction.rs:183-188) and is called after the work, so the recorded duration is about 0.
- Fix: one helper, `fn open_tx(repo: &Arc<ReadonlyRepo>, settings, ws_name, args) -> Transaction`, called at the start of the work. `PyReadonlyRepo::start_transaction` uses it too (7 sites). `undo`/`redo` default to `self.workspace_name`. checkout.rs and git.rs are outside this slice; check them for the same gap.

### [high] `clone_git` leaves a partly built destination when it fails
- Where: workspace.rs:379-571. Caller: pyjj-cli `commands/git/clone.py:50` catches the error and removes nothing.
- What: on any error after init (bad URL, network, auth, a bad branch pattern), `.jj` and, when colocated, `.git` stay in `destination_path`. If pyjj created the directory, the directory stays too. The jj CLI cleans all of these up (`commands/git/clone.rs:262-283`).
- Why it matters: the retry fails with "destination path exists and is not an empty directory". The user must delete it by hand.
- Fix: wrap the body after `create_dir_all`. On `Err`, remove `.jj` and `.git` (ignore `NotFound`), and remove the directory if it did not exist before. (The `unwrap()` at 556 is 01's finding.)

### [medium] Two settings objects drive one transaction; the `settings` parameter of `new_commit`/`rewrite_commit` does nothing
- Where: repo.rs:72-77 (`Transaction::new(mut_repo, &settings.0)`), 722 and 749 (`_settings`, unused). jj-lib repo.rs:1092-1101 builds every `CommitBuilder` from `self.base_repo.settings()`.
- What: the operation metadata (user, host) follows the settings passed to `start_transaction`. Commit author, committer, signing and change-id RNG follow the settings the repo was loaded with. Reproduced (`settings_split`): with "Passed Settings" passed to both calls, the author is "Repo Settings". jj-lib's own `start_transaction` (repo.rs:353-356) uses one settings object for both.
- Fix: remove `_settings` from `new_commit`/`rewrite_commit`, or document that only the operation metadata honours `start_transaction(settings)`. Better: keep the settings on `ReadonlyRepo` (jj-lib already has `ReadonlyRepo::settings()`) and stop passing them per call.

### [medium] Queries load the repo at head, which can write a merge operation
- Where: workspace.rs:649 (`is_colocated`), 665 (`create_git_worktree`), 691 (`unlink_git_worktree`), 91 (`add_workspace`, which does need the repo).
- What: these only need the `Store`, and `RepoLoader::store()` exists (jj-lib repo.rs:782). `load_at_head` resolves the operation heads. When there are several, it merges them and writes a "reconcile divergent operations" operation (jj-lib repo.rs:802-815).
- Why it matters: `is_colocated()` reads like a query, but it can write to the operation log, and it pays for a full head load each time.
- Fix: `inner.repo_loader().store()`. Same idea for `workspace_path` (616-625): it opens a `SimpleWorkspaceStore` by hand, while forget/rename already use `repo.loader().workspace_store()`.

### [medium] `update_stale` overwrites the working copy on `SiblingOperation`
- Where: workspace.rs:835-841.
- What: here jj refuses, with "The repo was loaded at operation X, which seems to be a sibling..." and a `jj op integrate` hint (cli_util.rs:3050-3062). pyjj checks out over the working copy. pyjj also skips the colocated Git HEAD reset that the CLI does first (cli_util.rs:686-697).
- Why it matters: the docstring admits that pyjj does not snapshot first. This second case is not documented, and it can throw away the working-copy operation's state without a word.
- Fix: return an error, or a distinct result, for `SiblingOperation`. Document the HEAD reset, or do it.

### [medium] `rename_workspace` renames the workspace store before it takes the working-copy lock
- Where: workspace.rs:1072-1081.
- What: pyjj calls `workspace_store.rename` (1075) and then `start_working_copy_mutation` (1079). The CLI takes the lock first (`workspace/rename.rs`).
- Why it matters: if another process holds the working-copy lock, or the lock fails, the store already has the new name. The view and the working copy still have the old one.
- Fix: take the lock before any mutation.

### [medium] `add_workspace` sparse default differs from the CLI
- Where: workspace.rs:921-922, 183-186.
- What: `jj workspace add` defaults to `--sparse-patterns=copy` (add.rs:107, 198-207). In pyjj, `sparse_patterns=None` means unrestricted. The parent's patterns are one line away (`inner.working_copy().sparse_patterns()`).
- Fix: default to copying the parent's patterns, or take an enum `copy|full|empty` that defaults to `copy`.

### [medium] "Transaction finished" is checked ad hoc, in three places with two messages, and builders skip it
- Where: `with_mut_repo` 695-698 ("already consumed"), `set_attribute` 1700-1703 (an inline copy, "already committed"), `commit` 1709-1711 ("already committed"), `__repr__` 1721. `CommitBuilder` never checks (see the critical finding).
- Fix: one `fn tx_mut(&self) -> PyResult<RefMut<'_, Transaction>>` (via `RefMut::filter_map`), used everywhere, builders included through `Py<PyTransaction>`. Add an `is_open` property instead of parsing `repr`.

### [medium] `PyCommit._repo` is dead, while half of `Commit`'s methods ask for `repo` again
- Where: commit.rs:42-43 (`#[allow(dead_code)]`, never read). It is `Some(base)` from `write()` (repo.rs:1893) and `None` from `Transaction.check_out` (repo.rs:815-818). `is_hidden`, `is_divergent`, `change_offset`, `is_empty`, `is_discardable`, `diff_from_parents`, `parent_contents` and `annotate` take `repo:`. `diff`, `read_file` and `list_files` do not. `PyTransaction.base_repo` (repo.rs:684-685) is dead as well.
- Why it matters: a commit written inside a transaction is bound to the base repo, which cannot see it. `c.is_hidden(repo)` returns `True` for the commit just written (`txprobe.log`, `write_wrong_repo`). The field holds a whole repo view (index plus view) alive and nothing uses it, because `Commit` already holds `Arc<Store>`.
- Fix: choose one model. Either drop `_repo` and keep explicit `repo` parameters, or bind each commit to its repo and drop the parameters. For transaction commits, have `Transaction` methods answer the repo-relative questions.

### [medium] DRY: repeated blocks in these files
- Open a transaction, work, commit (`MutableRepo::new` + `JjTransaction::new` + `block_on(tx.commit)` + `map_err`): 7 sites, about 5-7 lines each, about 40 lines. repo.rs:73-77; workspace.rs:129-131/172-177, 408-414, 433-435/522-524, 536-538/553-558, 996-998/1029-1031, 1069-1071/1088-1090. The `open_tx` helper from the high finding removes them.
- `resolve_single` body duplicated: repo.rs:440-449 and 464-473 (10 lines). A `fn single(commits, revision) -> PyResult<PyCommit>`.
- `PyReadonlyRepo { inner, workspace_root, workspace_name }` built by hand at repo.rs:570, 589, 1713 and workspace.rs:200, although `wrap_repo` exists. Add `PyReadonlyRepo::with_repo(&self, Arc<ReadonlyRepo>)`.
- `load_at_head` under the mutex: 7 sites in workspace.rs (91, 649, 665, 691, 706, 980, 1054).
- Checkout stats dict: workspace.rs:843-848 and 894-899 (identical), plus checkout.rs. A `#[pyclass(get_all)] CheckoutStats` (01's dict finding, also at these sites).
- `WorkspaceNameBuf::from(workspace_name.as_str())` with a local `use`: 5 sites in repo.rs (765, 794, 810, 1021, and git_head 111).
- `.map(|id| id.0)` id unwrapping: 21 sites crate-wide. `impl FromPyObject for CommitId` via a newtype, or a `fn ids(v: Vec<PyCommitId>) -> Vec<CommitId>`.
- `JjError::new_err(err.to_string())`: 13 sites in workspace.rs. Also falls under 02's error taxonomy finding.
- `bookmarks`/`get_bookmark`/`tags`/`get_tag` on both ReadonlyRepo (251, 376, 405, 426) and Transaction (856-920). These extend 01's twin finding: one `fn x(view: &View)` each.

### [medium] API shape: the transaction already knows things it asks for; stringly enums; no keyword-only arguments
- Redundant arguments:
  - `Transaction.edit/check_out/set_wc_commit/clear_git_head(workspace_name, ...)` and `git_reset_head(workspace_name, workspace_root)` take what `PyTransaction` already holds (repo.rs:686-687). Make them `Optional`, defaulting to the transaction's own values.
  - `Commit.match_filesets(settings, workspace_root, ...)` takes a root that `ReadonlyRepo` holds.
- The same role takes different types:
  - `set_wc_commit(commit_id)` but `edit(commit)`.
  - `rebase(commit, new_parents: [CommitId])`, `duplicate([Commit])`, `abandon_restoring_descendants([CommitId])`.
  - `load_operation(op_id: str)`, while everything else takes id objects.
  - `operation_id -> str` next to `operation -> Operation`.
  - `run_rewrite(new_trees: dict[str hex, TreeId])`: `CommitId` is hashable, so it can be the key.
  - `ReadonlyRepo.revset -> [Commit]` but `Transaction.revset -> [CommitId]`.
- Stringly enums: `set_sign_behavior(str)` (an unknown value raises `JjError`, not `ValueError`), `restore_operation(what=[str])`, `Commit.diff_stats(compare=str)`, `file_kind -> str`, `Verification.status`, `pick_conflict_sides(side: int)`. Use a `#[pyclass(eq)] enum` or a `Literal` in the stub.
- Bare tuples and dicts: `undo`/`redo -> (Operation, Operation, str)`, `walk_revs_count`, `conflicted_paths -> (str, int, int, [str])`, `Commit.conflict_sides -> dict` (commit.rs:430-443, not in 01's dict list), `view() -> dict[str, str hex]`.
- No `*` in any signature. `move_commits` takes four `list[CommitId]` positionally (easy to swap without an error). Positional bools: `rebase_descendants(False)` (session.py), `squash(..., keep_emptied)`, `git_fetch(..., tracked)`.
- Paths are `String` in and `display().to_string()` out (workspace.rs:589-637, `init_*`, `load`, `clone_git`). A `pathlib.Path` is rejected, and a non-UTF-8 path becomes lossy on output. Use `PathBuf`.
- `verification` is a `#[getter]` that runs the signing backend (commit.rs:98-105). A property should not do I/O; make it a method.
- `start_transaction(args: str)` leaves the CLI's shell quoting (cli_util.rs:2952-2980) to the caller. Accept `list[str]` and quote in Rust.

### [low] `id_prefix_context` swallows a bad `revsets.log` type and surfaces a bad `short-prefixes` one
- Where: repo.rs:41-51. The comment says type errors must surface, but `.unwrap_or_else(|_| String::new())` on `revsets.log` turns them into "no narrowing".
- Fix: the same `match` as for the first key.

### [low] `forget_store` docstring may be wrong (PLAUSIBLE)
- Where: workspace.rs:953-958. It says `jj workspace forget` keeps the store entry. The only CLI source available (0.45.1+81, `workspace/forget.rs`) calls `workspace_store.forget` unconditionally. jj-cli 0.46.0 source was not available to settle which is right.

### [low] Reentrancy trap in `with_mut_repo` closures that receive `self`
- Where: repo.rs:1376 (`absorb`), 1407 (`converge`), 1446 and 1468 (`fix_*`). Today they only read `workspace_root`/`workspace_name`, so this is safe. Any future `tx.*` call inside them panics on `BorrowMutError`. Pass the two fields, not `&PyTransaction`.

### [low] Misc
- `forget_workspaces` and `rename_workspace` descriptions use `as_str()`, where jj uses `as_symbol()` (quoting). A name with spaces prints differently from jj.
- `forget_workspaces` raises on an unknown name. jj warns and continues with the rest (forget.rs). The docstring does not say which behaviour pyjj has.

## Unwraps and expects reachable from Python
- repo.rs:442 and 466 are guarded by `len() == 1`. `&root.hex()[..12]` (repo.rs:1887) is on fixed-width hex. workspace.rs:556 is 01's. `lock().unwrap()` (19 sites) is 02's.
- New: the `has_rewrites` assert in jj-lib is reachable through `commit()` (high finding above), and two SIGSEGVs through `CommitBuilder` (critical finding).
