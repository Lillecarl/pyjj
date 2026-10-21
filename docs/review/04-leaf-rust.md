# 04: leaf Rust modules of pyjj-bindings

Read-only. Nothing in `~/Code/pyjj` changed. Probes ran against `wheel2/`
(01's build of the current source) with the nix Python 3.14, one temp repo per
case under `probe4/`. jj-lib line numbers are from the 0.46.0 registry source
(`RepoPath` lives in `jj-core-0.46.0`). jj-cli 0.46.0 is not in the registry,
so CLI references are from `~/Code/jj` (0.45.1+81), context only.

Evidence (scratchpad):
- `leafprobe.py`, `leafprobe.log`: hunk selection in split, fix key collision.
- `hunkdiff.py`, `hunkdiff.log`: Rust `diff_hunks` vs Python `hunk.get_hunks_detailed`.
- `staleprobe.py`, `staleprobe.log`: snapshot of a stale working copy.
- `gcprobe.py`, `gcprobe.log`: gc from a stale repo object; gc panics.
- `pathprobe.py`, `pathprobe.log`: path strings accepted into trees.
- `atopprobe.py`, `atopprobe.log`: `at_operation()` to a newer op.

Crate-wide patterns (GIL held, mutex/GIL deadlock, error taxonomy, async
split, CommitBuilder transmute, transaction helper, missing
rebase/immutable handling, PyDict stats, stringly enums): see 02/03. Not
repeated. `Python::attach` inside detached work at git.rs:70,125,367,490,563,
630,657 and checkout.rs:132,184,314 is 02's deadlock finding.

Read end to end: run.rs, fix.rs, git.rs, rewrite.rs, absorb.rs, bisect.rs,
converge.rs, checkout.rs, hunks.rs, oplog.rs, revset.rs, graph.rs, gc.rs,
revert.rs, annotate.rs. Skimmed (grep for panics, paths, I/O, plus first
screens): tree.rs, file.rs, conflicts.rs (1-220, 300-340), debug.rs,
opdiff.rs, evolution.rs, operation.rs, bookmark.rs/tag.rs (diffed against
each other only; 01 owns their duplication).

Counts: 1 critical, 7 high, 7 medium, 5 low.

### [critical] `ReadonlyRepo.gc()` defaults to "expire now" and sweeps from whatever operation the object holds
- Where: repo.rs:619-621 (`max_age_secs=0.0` default), gc.rs:36-51.
- What: jj defaults `--expire` to 14 days and refuses a non-head operation (`util/gc.rs`, `is_at_head_operation`). pyjj's default is 0, and the docstring hands the head check to the caller. `SimpleOpStore::gc` (simple_op_store.rs:274-311) deletes every operation not reachable from the given ids and older than the cutoff. With a cutoff of 0 that includes the real head.
- Reproduced (`gcprobe.log`): `old = <repo>; tx ...; tx.commit(); old.gc()`. The head operation's file is deleted. `Workspace.load_at_head()` then raises `RepoLoadError: Object 08e5da2e... of type operation not found`. The repository no longer loads. The git-backend sweep runs against the stale index too, so objects only newer commits use become prunable (PLAUSIBLE, not tested).
- Also: `gc(float("inf"))` and `gc(1e20)` raise `PanicException` (`Duration::from_secs_f64`, gc.rs:37). A large finite value that passes would still panic in `SystemTime - Duration`.
- Fix: in gc.rs, load the current op heads (`op_walk::get_current_head_ops`) and raise unless `repo.op_id()` is the single head. Default `max_age_secs` to 14 days. Use `Duration::try_from_secs_f64` and `SystemTime::checked_sub`, and raise `ValueError` on failure.

### [high] `snapshot` of a stale working copy silently reverts a rewrite of `@` made elsewhere
- Where: checkout.rs:88-195 (`snapshot`), reached from `Workspace.snapshot` (workspace.rs:723).
- What: pyjj loads the repo at head and snapshots the disk against the working copy's recorded tree. It never calls `WorkingCopyFreshness::check_stale`. jj does (`handle_stale_working_copy`, cli_util.rs:3011-3065) and refuses with "The working copy is stale". It also reloads at the working copy's operation when that one is newer.
- Reproduced (`staleprobe.log`): `@` has `f`. A transaction (standing in for another workspace or process) adds `g` to `@`. `ws.snapshot(s)` then reports `changed: True`, and `@` has only `f`. The other operation's change is undone with no error. It survives only in the op log.
- Why it matters: any `pyjj status`-like call in a secondary workspace after `jj rebase` or `jj squash` from the main one rewrites `@` back to its old content.
- Fix: after `start_working_copy_mutation`, run `check_stale(locked_wc, &wc_commit, &repo)`. On `Updated(op)` reload at that op. On `WorkingCopyStale`/`SiblingOperation` raise `WorkingCopyError` with jj's wording. On a missing workspace, return "not changed" as jj does.

### [high] `snapshot` amends an immutable `@` and tracks files the user ignores globally
- Where: checkout.rs:115-121, 145-146, 259-265; run.rs:70-81 (run slots).
- What, three gaps against `snapshot_working_copy` (cli_util.rs:2088-2160):
  - Immutable `@`: jj creates a new commit on top and warns. pyjj rewrites the immutable commit in place (checkout.rs:145), so a pushed commit gets a new id.
  - `base_ignores` is `GitIgnoreFile::empty()`. jj chains `core.excludesFile` (default `$XDG_CONFIG_HOME/git/ignore`) and `.git/info/exclude` (`base_ignores`, cli_util.rs:1673-1710). The module doc admits this.
  - `snapshot.auto-track` is ignored. `start_tracking_matcher` is always `EverythingMatcher`.
- Why it matters: a file that the user's global git ignore covers (`.env`, `.envrc`, editor state) is committed into `@` by pyjj and not by jj. The next push publishes it. A user with `snapshot.auto-track = "none()"` gets every new file tracked.
- Fix: one `snapshot_options(settings, workspace, repo)` helper. It reads the excludes the way the CLI does, and parses `snapshot.auto-track` as a fileset. checkout.rs and its two callers share it. For an immutable `@`, use `new_commit([wc], tree)` and return a flag so Python can warn.

### [high] Hunk selection with `paths=None` moves every other change, and a full deletion becomes an empty file
- Where: rewrite.rs:126-152 (`select`), 81-119 (`apply_hunks`). Callers: `Transaction.squash`/`split_selected` (repo.rs:1141), `Session.squash`/`Session.split(hunks=...)` (session.py:381,406), pyjj-cli `hunk/squash.py:84`.
- What, three defects:
  - With `paths=None`, `select` restores the whole commit tree (`EverythingMatcher`), then overlays only the paths named in `hunks`. Every unnamed file moves whole. pyjj-cli's comment at hunk/squash.py:80-83 assumes the opposite ("assume default is reset").
  - A path whose selection is a no-op (`continue` at 98-100) keeps the base tree's value, which is the full change.
  - A file the commit deletes reads as `b""` (`read_tree_file_bytes` maps absent to empty). Selecting all its hunks writes an empty regular file instead of removing the path. The reverse holds for a file the commit adds.
- Reproduced (`leafprobe.log`): `c2` deletes `a.txt`, changes `b.txt`, adds `c.txt`. `split_selected(c2, None, {"a.txt": [0]})` gives a first commit with `a.txt: b''`, `b.txt` and `c.txt`. `split_selected(c2, None, {"c.txt": []})` gives `b.txt` and `c.txt`.
- Fix: when `hunks` is given, start from `parent_tree` for those paths, not `selected_tree`. Restrict the matcher to `paths` only, so that `paths=None, hunks={...}` selects only the hunks. Track presence separately from content: absent before plus everything selected means absent, and the reverse. Take the executable bit from the parent when the commit deletes the file.

### [high] Python and Rust number hunks with different diff algorithms
- Where: Rust `hunks::diff_hunks`/`apply_hunk_selection` (hunks.rs:86-131, jj `ContentDiff::by_line`). Python `pyjj/hunk.py:259-312` `get_hunks_detailed` (`difflib.SequenceMatcher`). pyjj-cli `hunk/squash.py:66-74` resolves hunk ids through the Python function and sends the indices to Rust `tx.squash(hunks=...)`. `list_hunks_for_commit` (hunk.py:799) shows the user Python's numbering.
- What: the user picks hunk N from difflib's list, and Rust applies hunk N of jj's diff.
- Reproduced (`hunkdiff.log`): 105 of 304 random and hand-made cases disagree. Example: `'a\nb\nc\n' -> 'c\nb\na\n'`. Rust has `[('a\nb\n',''), ('','b\na\n')]`, Python has `[('','c\nb\n'), ('b\nc\n','')]`.
- Why it matters: `pyjj hunk squash` with ids or indices moves a different line than the one shown. hunk.py's comment ("Use similar's TextDiff via Python difflib as approx") shows that the gap is known.
- Fix: one algorithm. Expose ids, ranges and context from Rust (`diff_hunks` already has the hunks; add line numbers) and delete the difflib copy. Or do all reconstruction in Python and have Rust take only bytes (`squash_edited`/`split_selected_edited` already take bytes).

### [high] `fix` keys files by content hash, so one formatter result lands on every path with the same bytes
- Where: fix.rs:84 (`LookupFixer`, `fixes.get(&file_to_fix.file_id.hex())`), fix.rs:157 (`key: file_id.hex()`).
- What: jj-lib's `FileToFix` is `(file_id, base_file_id, repo_path)` (jj-lib fix.rs:50-64), and jj-lib documents the path as an input to the fixer. pyjj collapses it to `file_id`. Two entries with the same key come back from `fix_enumerate`, and `fix_apply` applies one result to both.
- Reproduced (`leafprobe.log`): `x.rs` and `x.txt` with identical content. The caller gives new content only for the `.rs` key. After `fix_apply`, both files read `FORMATTED`.
- Why it matters: pyjj-cli picks tools by path pattern and substitutes `$path` (fix.py:79,97). A `*.rs` formatter rewrites a `.txt` file or a vendored copy. With `line-range-arg` the ranges depend on `base_content`, so results differ by base too. `fixes[f.key] = cur` (fix.py:110) is then last-writer-wins in `HashSet` order, which is not deterministic.
- Fix: key on all three fields (for example `f"{file_id}:{base or ''}:{path}"`, or an index into a stored `Vec<FileToFix>`), and match on the full struct in `LookupFixer`.

### [high] Any path string is accepted into a tree: `""` panics, `..`, `.git/...` and `.jj/...` are written
- Where: tree.rs:18-20 (`repo_path` = `RepoPathBuf::from_internal_string`, which only rejects a leading or trailing `/` and `//`: jj-core repo_path.rs:634-636). Used by rewrite.rs (overlay_contents, apply_hunks, set_executable, restore, paths_matcher), conflicts.rs, checkout.rs:233 (untrack), run.rs:130, file.rs, absorb.rs, fix.rs.
- Reproduced (`pathprobe.log`): `edit_commit_tree(c, {"": b"x"})` raises `PanicException: assertion failed: !path.is_root()` (jj-lib tree_builder.rs:72). `..`, `a/../b`, `.`, `.git/hooks/post-checkout` and `.jj/repo/x` are accepted and appear in `list_files()`.
- Why it matters: jj never builds these, because CLI paths go through `from_relative_path`/fileset parsing. A pyjj script can write such a commit and push it. That git fsck rejects it and that jj refuses to check it out is PLAUSIBLE, not tested here.
- Fix: validate in `repo_path`: reject empty strings, `.`/`..` components, and the reserved `.git`/`.jj` components (or use `RepoPathBuf::from_relative_path`). Raise `ValueError`. Keep a separate `repo_dir_path` for callers that mean the root.

### [high] Git import ignores the user's import config (auto-track, abandon-unreachable)
- Where: git.rs:56-62 (`default_import_options`), used by `import_refs` (67), `fetch` (352), `fetch_all_inner` (442), and so by `clone_git`.
- What: jj builds `GitImportOptions` from `GitSettings` (`git.abandon-unreachable-commits`, `git.record-synthetic-predecessors`) and from `remotes.<name>.auto-track-bookmarks` (git_util.rs:204-213, revset_util.rs:410-423). pyjj hard-codes `true, true, {}`. jj-lib already parses these: `GitSettings::from_settings` (jj-lib git.rs:111-124) and `RemoteSettings` (settings.rs:67-80).
- Why it matters: with `remotes.origin.auto-track-bookmarks = "*"`, pyjj fetches new remote bookmarks untracked (jj-lib git.rs:1125-1140) where jj tracks them. With `git.abandon-unreachable-commits = false`, pyjj abandons commits the user asked to keep. `remotes.<name>.fetch-bookmarks`/`fetch-tags` are skipped too (git.rs:275-279, documented).
- Fix: take `settings` in `import_refs` and build the options from it once. Read the remote's `fetch-bookmarks`/`fetch-tags` in `fetch_expressions` with the same `RemoteSettings` table.

### [medium] `push_bookmark` pushes what `jj git push` refuses, and pushes drop `unexported_bookmarks`
- Where: git.rs:602-685 (`push_bookmark`), 527-591 (`push_updates`).
- What: the docstring sends the selection logic to pyjj-cli, but `push_bookmark` is a complete push primitive. It skips jj's checks on the commits: conflicted, no description, no author, `git.private-commits`, and signing (`git.sign-on-push`). Both functions drop `GitPushStats.unexported_bookmarks` (jj-lib git.rs:3530-3550), which jj warns about. A bookmark appears in `pushed` while the view was not updated.
- Fix: run the commit checks in `push_bookmark` or remove it in favour of `push_updates` plus the CLI logic. Return `unexported` in the result.

### [medium] `at_operation()` to a newer or sibling operation fails with "index might be corrupted"
- Where: revset.rs:173-179 (`.into_inner().0` drops `other_repos`). Every revset entry point goes through it.
- Reproduced (`atopprobe.log`): `old.revset(s, "at_operation(<newer op>, visible_heads())")` raises `RevsetEvalError: Commit ID ... not found in index (index or view might be corrupted)`. jj-lib carries `other_repos` and a merged index for exactly this (revset.rs:709-723).
- Fix: keep the `ResolvedRevset` and evaluate through it, as 0.46 intends. At minimum, raise "at_operation() outside this repo's history is unsupported".

### [medium] `RunPool.acquire` waits forever and cannot be interrupted
- Where: run.rs:148-150, 228-243.
- What: an unbounded `sleep`/`try_lock` loop inside `py.detach`. Ctrl-C is never checked (`Python::check_signals` cannot run while detached). The docstring describes the self-deadlock (two acquisitions on a 1-slot pool), and nothing breaks it. Each pass also calls `create_dir_all` for every slot, so `size` in the millions makes millions of directories.
- Fix: take `timeout: float | None`. Every few backoffs, `Python::attach(|py| py.check_signals())`, and return the error. Create slot directories once in `new`, or lazily per locked slot.

### [medium] Graph layout exists twice, in Rust and in Python
- Where: graph.rs:146-218 (`GraphRenderer`, Sapling `renderdag`, used by pyjj-cli log/op log/evolog) and `pyjj/graph_layout.py` (149 lines, lane allocation, used by pyjjui and graph_dot.py).
- What: two column-assignment engines for the same `GraphNode` stream. graph.rs's own doc gives the reason against a second engine ("a second drawing that agrees with jj's only until one of them changes"). `to_ancestors` maps an unknown `edge_type` string to `Parent` without an error.
- Fix: expose renderdag's per-row column state (or `GraphRowRenderer` rows without glyphs) to Python, and build pyjjui's lanes on it. Otherwise document why pyjjui needs its own. Use a pyclass enum for edge types.

### [medium] Presentation and CLI wording live in Rust
- Where: oplog.rs:42-46 (error text with an embedded `Hint:` line and `--allow-cross-workspace` flag names), checkout.rs:39-53 (`untracked_reason` formats `HumanByteSize`), rewrite.rs:639-645 and 657-662 (short-hash messages), debug.rs (all output is `writeln!` text, about 60 `.unwrap()` on `String` writes), git.rs:613-620.
- What: a library raises text that names flags of a CLI it does not have. Callers that want structured data (an op id, a byte count) must parse the message.
- Fix: return data (`CrossWorkspaceError(op_id, workspace)`, `(size, max_size)`) and let pyjj-cli format it. debug.rs output can stay text, but it is the CLI's job.

### [medium] DRY in this slice
- git.rs: the import-stats dict built 3 times (73-87, 368-385, 491-505) and the push-stats dict twice plus an empty variant (563-590, 630-636, 657-684), about 110 lines. One `#[pyclass(get_all)] ImportStats`/`PushStats` with `From<GitImportStats>` removes them (01's dict finding, new sites).
- converge.rs: `ConvergedAuthor`/`ConvergedDescription`/`ConvergedParents` are 3 copies of about 55 lines (36-212). One generic `ConvergedAttribute` with `value: Py<PyAny>`, or a `macro_rules!`, saves about 110 lines.
- graph.rs: `commits_graph` and `log_graph` repeat the 30-line stream-to-`PyGraphNode` loop (59-144).
- checkout.rs: `snapshot` and `untrack_paths` repeat the load-head, wc-commit lookup, colocated check and lock prelude (93-113 and 215-239), and two `SnapshotOptions` literals (115-121, 259-265) plus run.rs:70-81.
- rewrite.rs: `squash`/`squash_edited` and `split_selected`/`split_selected_edited` differ only in how the selected tree is built. `apply_hunks` and `overlay_contents` repeat the exec-bit lookup plus `write_file` plus `Merge::normal(File{..})` (101-116, 271-290). One `fn file_value(store, path, bytes, exec)` and one `Selection` enum (`Paths`, `Hunks`, `Contents`) cover all four.
- `SilentCallback` plus `GitSubprocessOptions::from_settings` repeated per entry point (git.rs:350, 440, 548, 644).
- About 300 removable lines in this slice. Bookmark/Tag twins are 01's (the diff shows only doc-comment differences).

### [medium] Executable bit and copy id handled three different ways
- Where: rewrite.rs:101-108 and 271-281 (exec bit from the commit tree only; a lookup error is swallowed by `.ok()`; `CopyId::placeholder()`), rewrite.rs:491-503 (`set_executable` keeps `copy_id`), conflicts.rs:120-124 (keeps the materialized `copy_id`).
- What: hunk and editor edits reset the copy id that `set_executable` and conflict resolution keep. A partly selected deletion takes `executable=false`, not the parent's bit. A backend error during the lookup becomes "not executable".
- Fix: one helper that reads the existing value (raising errors) and keeps `executable` and `copy_id` from whichever side has the file.

### [low] Alias tables: a bad declaration is dropped without notice, and both maps are rebuilt per call
- Where: revset.rs:28-50, 138-140.
- What: `let _ = aliases_map.insert(...)` drops a bad declaration in a higher layer, so the lower layer's definition of the same name wins with no message. Every `revset()`, `check_rewritable`, `fix`, `absorb` and `bisect` call walks all config layers twice.
- Fix: collect insert errors into warnings on `UserSettings` (alongside 02's dropped config warnings), and cache the maps on `PyUserSettings`.

### [low] `squash` docstring names the wrong diff base for `hunks`
- Where: rewrite.rs:171-174 says hunk indices diff "that path's content in `destination` against `source`". The code diffs `source`'s parent against `source` (`select`, 132-145). They differ when `destination` is not the parent.

### [low] `op_abandon` drops jj's warning when the working-copy operation is not remapped
- Where: oplog.rs:173-178. jj warns "The working copy operation X is not updated because it differs from the repo" (operation/abandon.rs). pyjj returns `changed=True` and nothing else. Add a field to `OpAbandonStats`.

### [low] Bisect results are strings
- Where: bisect.rs:60-71 (`kind`, `result`: `"evaluate"`, `"done"`, `"found"`, `"found-despite-skips"`, ...), 74-84, 343-351. Extends 03's stringly-enum list. The replay design and the mark validation are sound: they match jj-lib bisect.rs:200-231 asserts, and no assert is reachable.

### [low] `debug_index_changed_paths` unwraps an `Option`
- Where: debug.rs:419. Mirrors jj (`index_changed_paths.rs:63`), but in a library the `None` case (nothing indexed) becomes `PanicException`. Return `None`.

## Checked and fine
- run.rs: no subprocess in Rust (pyjj-cli runs the command). Slot dirty-marker logic is sound. `to_fs_path_unchecked` at 278/350 only sees paths from a disk walk. `run_rewrite`'s 3-way merge (`new - old + rebased`) is correct.
- absorb.rs and revert.rs match the CLI primitives. bisect.rs replay is sound. oplog undo/redo stack-jumping matches undo.rs. gc.rs matches the CLI apart from the critical finding.
- git.rs: subprocess, auth, signals and env are jj-lib's `GitSubprocessOptions`. Nothing added by pyjj.
