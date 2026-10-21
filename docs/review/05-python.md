# 05: the Python wrapper `pyjj/pyjj/*.py` and `pyjj/pyproject.toml`

Read-only. Nothing in `~/Code/pyjj` changed. Probes ran against `wheel2/` with
`PYTHONPATH=wheel2:~/Code/pyjj/pyjj`, a scratch `HOME`/`XDG_CONFIG_HOME` (the
real jj config has `signing.backend = "gpg"`; with it, `snapshot` hangs in the
sandbox and then raises `BackendError: Could not write object of type commit`).

Evidence (scratchpad `r05/`):
- `sessprobe.py`, `sessprobe.log`, `sessprobe-rebase.log`: `Repo`/`Atomic` cases, one subprocess each.
- `hunkprobe.py`, `hunkprobe.log`: hunk.py edge cases.
- `dotprobe.py`, `dotprobe.log`: graph_dot planning.
- `ruff.log`, `ruff-stats.log`, `mypy-strict.log`, `mypy-default.log`, `bp-standard.json`, `bp-recommended.json`: lint and type runs.
- `stubs/pyjj_bindings/__init__.pyi`: 01's stub with `from` renamed to `from_` (the original does not parse, so no checker can use it).
- Tools env: `r05/envpath` (ruff, basedpyright, mypy, python 3.14 with anyio/pydantic/pyyaml/pygraphviz).

Not repeated: `_async.py` (02 A4), hunk numbering difflib vs jj (04), the
Rust-side hunk selection defects (04), `IndexError` shadowing (02).

Counts: 0 critical, 4 high, 15 medium, 7 low.

## Does the wrapper earn its existence?

- `__init__.py` is 157 lines. 150 are two hand-kept lists of the same 67 names (import list and `__all__`). It adds no API of its own. The real wrapper is `session.py` (574), `hunk.py` (890) and the graph modules (435).
- Coverage: the stub has 93 top-level names; `pyjj` re-exports 67. Missing: 7 result types that methods return (`ConfigLayer`, `DiffStat`, `ModifiedChange`, `MoveCommitsStats`, `OperationDiff`, `RefChange`, `RefTargetSummary`), 18 `debug_*` functions, `secure_config_file`. So pyjj-cli imports `pyjj_bindings` directly in `commands/config/paths.py`, `commands/debug.py`, `commands/python_repl.py`, against AGENTS.md.
- `VERSION` is imported but not in `__all__` (ruff F401).
- No `py.typed` in `pyjj/pyjj`. Even with a shipped `.pyi` for `pyjj_bindings`, PEP 561 checkers treat an installed `pyjj` as untyped.
- Verdict: today the wrapper is a re-export plus three real modules. It earns its place only if it becomes the typed, async, single import surface. Short of that, `from pyjj_bindings import *` driven by the stub's `__all__` removes 150 lines and the drift.

## Lint and type-check results

ruff 0.x, `--select E,F,B,UP,SIM,RUF,ASYNC,TID,ANN,PT,BLE,S,PLC0415,TC,FA --target-version py39`: 182 findings.
- Noise for this review: E501 99 (all in hunk.py, mostly the comment block), ANN* 58 (a real gap, but one finding: no annotations), RUF100 7 (the `noqa: BLE001`s are unneeded because each `except` re-raises), RUF022 1.
- Signal: FA102 x2 (graph_layout.py:135,144, see the pyproject finding), B904 x2 (hunk.py:168,431), PLC0415 x3 (hunk.py:264,877,878), BLE001 x2 (hunk.py:828,832, silent), B007 (hunk.py:854), SIM102/SIM110 x4.
- No ASYNC, S, TID or PT hits.

mypy (patched stub on `MYPYPATH`):
- default: 6 errors. graph_dot.py:99/101 (`parents` reused as list then set), graph_layout.py:75/99 (lane type `CommitId` vs `object`), hunk.py:435 (`idx` reused), pygraphviz untyped.
- `--strict`: 86 errors. 41 no-untyped-def, 13 no-untyped-call, 10 unused-ignore (hunk.py `# type: ignore`), 9 type-arg, 5 no-any-return, 4 arg-type, 2 assignment.

basedpyright:
- standard: 11 errors. 5 possibly-unbound (`PydanticField`, `yaml` behind `try: import`), 4 pygraphviz attr access (no stubs), 2 graph_layout arg-type.
- recommended: 33 errors, 647 warnings. 363 are in session.py, nearly all `reportUnknown*`: `Repo.__init__(self, workspace, settings)` is unannotated, so every value derived from it is Unknown although the stub types all of it. 12 `reportPrivateUsage` (`self._repo._repo` from `Atomic`).

### [high] `Atomic.split` moves the working copy onto the second half, for any revision
- Where: session.py:419 (`self._tx.set_wc_commit(workspace_name, second.id)`, unconditional).
- What: `jj split -r X` moves `@` only when X is `@`. pyjj moves `@` onto the remainder whatever X is.
- Reproduced (`sessprobe.log`, `split_non_wc`): `@-` = "ab", `@` empty. `tx.split("@-", paths=["a"])`. After: `@` is the "ab" remainder; the old empty `@` is gone.
- Why it matters: the next snapshot amends a finished commit. A scripted split deep in a stack silently re-targets the user's edits.
- Fix: call `set_wc_commit` only when `target.id` equals the transaction's current wc commit id. The rebase of the rewritten target already carries `@` when it pointed at the target.

### [high] `Atomic.rebase(after=...)` reads children from the starting repo, not the transaction
- Where: session.py:450-453 (`self._repo.revset(...)`, which is `ReadonlyRepo.revset`).
- What: `_commit`'s own docstring (283-288) says every lookup in a block must go through the transaction. This one does not. The `after` commits are already resolved in the transaction, then their hex ids are fed to the base repo.
- Reproduced (`sessprobe-rebase.log`): `describe(y) ; rebase(x, after=y2)` in one block raises `revset '37d3c2…+': Revision ... doesn't exist`. Without the earlier rewrite, children created earlier in the block are missed and stay on the old parent.
- Fix: `self._tx.revset(settings, ...)` and map ids with `get_commit`; exclude the moved targets from `children`, as `jj rebase -A` does.

### [high] Per-hunk `lines` with an `id` selects the whole hunk under pydantic, and raises without it
- Where: hunk.py:356-373 (pydantic branch: `entry.id` set, `lines` dropped, comment admits it) vs hunk.py:450-462 (manual branch raises "not yet supported").
- Reproduced (`hunkprobe.log`): `{"hunks": [{"id": "hunk-ab", "lines": [0]}]}` gives `ids={'hunk-ab'}, per_hunk_lines={}`: the whole hunk is selected, not line 0.
- Why it matters: an agent asks for one line and the split or squash moves the whole hunk. The two validators also disagree on `True` (index `True` vs `1`).
- Fix: one validator. pydantic is a hard dependency (pyproject), so delete the manual branch (about 130 lines) and reject `id`+`lines` in `HunkObjectModel` until it is supported.

### [high] `spec_to_overrides` turns a kept deletion into an empty file (extends 04)
- Where: hunk.py:814-837 (`collect_file_contents_for_commit` maps absent to `b""`), 854-866 (returns `b""`, never the `None` its docstring promises for deletion). Callers: pyjj-cli `hunk/split.py`, `hunk/commit.py` into `split_selected_edited`.
- Reproduced (`hunkprobe.log`): `gone.txt` deleted in `@`, `default: keep` gives `{'gone.txt': b''}`.
- Fix: carry presence: `dict[str, tuple[bytes | None, bytes | None]]`, and return `None` when the selected side is absent. Same root as 04's Rust finding; fix both together.

### [medium] Errors from inside a block lose their class
- Where: session.py:186-192, 239-247; also `resolve`/`revset` (133-143) and `_commit` (292-295).
- What: a `JjError` subclass becomes `PyjjError`, wrapped twice inside `atomic` (`PyjjError` -> `PyjjError` -> `RevsetEvalError`, `sessprobe.log` `error_type`). `except pyjj.RevsetEvalError` never matches. Non-jj errors are re-raised as `raise e from e`, so `e.__cause__ is e` (probe `failed_block_writes`).
- Fix: make `PyjjError` a mixin and raise a subclass per jj class, or re-raise the original and attach the note with `e.add_note(...)` (3.11+). Use `raise` (bare) for non-jj errors.

### [medium] "A failed block writes nothing" is false; the commit phase is outside the guard
- Where: session.py:22-26 and 166-171 (docstrings), 179 (`self.snapshot()` before the transaction), 193-202.
- What: the snapshot runs and commits a working-copy operation before the block body. Reproduced: a dirty working copy plus `raise` in the block changes the op id (`failed_block_writes`). Separately, `rebase_descendants`, `_export_git_refs`, `commit`, `reload` and `_checkout_if_moved` run after the `try`. A failure there leaves `rolled_back == False` with no explanation; a failure after `commit` (in checkout) leaves the operation written and the disk not updated.
- Fix: say "nothing but the snapshot". Move the commit phase into the guard, set `_discarded` only before `commit`, and raise a distinct error for "committed but not checked out".

### [medium] `Atomic.new` does not abandon the old empty working-copy commit
- Where: session.py:356-358 (`set_wc_commit`).
- What: `jj new` uses `MutableRepo::edit`, which abandons the previous `@` when it is discardable. Reproduced (`new_leaves_empty`): one empty, undescribed commit is left behind per `new()`. `commit()` calls `new()`, so every `commit()` call leaks one too when `@` was already empty.
- Fix: `self._tx.edit(...)` (it exists on Transaction), not `set_wc_commit`.

### [medium] `squash` default destination: merges and root children
- Where: session.py:378-379 (`source.parent_ids[0]`).
- What: a merge squashes into its first parent without error; jj refuses ("Cannot squash merge commits without a specified destination"). A child of root raises builtin `IndexError`, not `PyjjError` (`sessprobe.log`).
- Fix: require exactly one parent and raise `PyjjError` otherwise.

### [medium] No async surface for the session API
- Where: all of session.py. `pyjj.open`, `Repo.snapshot`, `reload`, `resolve`, `revset`, `log` and every `Atomic` verb are sync; per 02 A1 most also hold the GIL.
- Why it matters: session.py calls itself "the API an agent reaches for", and the house rubric is async by default. An `await`-based agent calling it blocks its loop. Transaction is unsendable (02 A5), so `atomic` cannot move to a thread as is.
- Fix: follows 02 A5(a). Make `Repo`'s reads `async` through `anyio.to_thread.run_sync` (they touch only `ReadonlyRepo`/`Workspace`), and make `atomic` an `asynccontextmanager` whose body runs as a plan that a worker thread executes inside its own transaction.

### [medium] The wrapper is untyped where the stub could type it (see the counts above)
- Where: session.py:86 (`__init__(self, workspace, settings)`), 105/111/126/138/145/150/275/280/302 (no or bare `list` returns), every verb returns an unannotated binding object; hunk.py `dict[str, Any]` hunk records (259-312); graph_layout.py `layout_keyed(items)`, `reverse_graph(items)`; `edge_type: str` while graph_dot.py:32 defines `EdgeType`; action strings `"keep"|"reset"` as `str` in `FileSpec`/`Spec` (74, 85).
- Fix: annotate with the stub types under `TYPE_CHECKING`; a frozen `@dataclass Hunk` (or the pydantic model already present) for hunk records; reuse `EdgeType`; `Literal["keep", "reset"]`. Add `py.typed`. Gate CI on `mypy --strict` (86 today) once 01's stub parses.

### [medium] Re-export layer is hand-kept, incomplete and leaks the binding import
- Where: `__init__.py:3-157`. Details in the section above.
- Fix: `from pyjj_bindings import *` plus `__all__ = [*pyjj_bindings.__all__, "open", "Repo", ...]`, with the declarative module from 01 producing `__all__`. Rename `open` (shadows the builtin on `import *`, like 02's `IndexError`).

### [medium] hunk.py: two validators, optional imports for hard dependencies, dead code
- Where: hunk.py:39-53 (`try: import yaml/pydantic`), 88-181 and 383-512 (two parsers of the same DSL), 799-811 (`list_hunks_for_commit` always returns `{}`), 528-551 (`file_spec_decides_keep`, unused), 253 (`_count_lines`, unused), 664 (dead `before_lines`), 643-755 and 715-727 (about 120 lines of thinking-aloud comments), 264/877/878 (imports in functions).
- Correction to 04: `list_hunks_for_commit` does not show users anything; it is a stub. pyjj-cli lists hunks through `get_hunks_detailed`.
- Fix: pyproject already requires pydantic and pyyaml, so import them at the top and delete the fallback. Delete the stub, the unused helpers and the comment block (keep the one decision it reaches: per-hunk lines are defined for insert hunks).

### [medium] hunk.py line-level semantics are surprising and undocumented
- Where: hunk.py:699-729, 515-525, 143/507.
- Reproduced (`hunkprobe.log`):
  - Replace hunk `old1,old2 -> new1,new2`, keep added line 0: result `new1\n`. Both old lines are deleted although none was selected for deletion.
  - `removed_lines: [0]` on a delete hunk keeps line 0 in the file: the name says the opposite.
  - A delete hunk is never matched by `lines` ranges (its after-length is 0), so `lines: [[1,3]]` around a deletion keeps the line.
  - `lines: [[2,2]]` is accepted, an empty range under the documented end-exclusive rule.
- Fix: define per-hunk selection as two sets, removed lines to drop and added lines to add, and rebuild the hunk from both. Match delete hunks on the before-range. Reject `start == end`.

### [medium] hunk.py drops binary and unreadable files silently
- Where: hunk.py:585-594 and 638-642 (binary: any hunk or line selection returns `before`), 826-835 (`except Exception` maps read errors and conflicts to `b""`; on an `after` failure it also blanks `before`).
- Reproduced: `{"hunks": [0]}` on a binary file returns the old bytes, no error.
- Fix: raise `ValueError("binary file: use action keep/reset")` for a hunk or line selection on undecodable content. Let read errors propagate; for conflicts use the materialized content or raise.

### [medium] `resolve_abandons` emits duplicate parents, so `resolve_plan` refuses a valid plan
- Where: graph_dot.py:271-283.
- What: jj-lib's `rewritten_ids_with` (repo.rs:1197-1234) skips visited ids. Here, M = merge(A, B), A on B, abandon A gives M parents `[B, B]`, and `resolve_plan` raises "names parent B twice" (`dotprobe.log`).
- Fix: dedupe in `resolve_target`'s caller, keeping first occurrence order.

### [medium] Graph layout: Rust should own it (extends 04) -- declined
- Outcome: declined. pyjj keeps graph_layout.py and its Jinja templates by choice, where jj's Rust could serve.
- Where: graph_layout.py:54-149 vs graph.rs:146-218.
- Decision: Rust. renderdag is jj's own layout and pyjj's parity suite compares against jj. renderdag's `GraphRowRenderer` already yields structured rows (node column, per-column `LinkLine` flags) keyed by any `Hash + Eq` type, so `String` keys serve log, op log and evolog. Expose that as a `GraphRow` pyclass, and reduce graph_layout.py to a glyph adapter for pyjjui. Keep `reverse_graph`, `resolve_plan` and `resolve_abandons` in Python: they are pure, small and have no jj counterpart to drift from.

### [medium] pyproject.toml: wrong Python floor, no tool config, heavy core dependency
- Where: pyjj/pyproject.toml.
- What: `requires-python = ">=3.9"`, but graph_layout.py:135,144 evaluate `tuple[...] | None` at def time (no `from __future__ import annotations`), which raises `TypeError` on 3.9 at import, and the pydantic models (hunk.py:92-120) use `int | None`, which pydantic cannot evaluate on 3.9 (by reading; no 3.9 interpreter here). No `[tool.ruff]`, `[tool.mypy]` or pyright config. `pygraphviz` (a C extension needing libgraphviz) is a core dependency, though only graph_dot.py imports it. No version bounds on anyio, pyyaml, pygraphviz.
- Fix: `>=3.11` (also enables `add_note`, `StrEnum`); `from __future__ import annotations` everywhere; move pygraphviz to an extra `dot`; add ruff and mypy sections matching the rule set above.

### [low] Colocation check differs from jj
- Where: session.py:232-233 (`os.path.exists(root/.git)`).
- What: jj exports only when `open_git_repo_at_workdir` finds the repo's own git dir (`git_util.rs:67-77`). An unrelated `.git` (or a nested repo) triggers export and HEAD reset here. Use the binding's `is_colocated()` once 03's load-at-head issue is fixed.

### [low] Docstrings say a jj-lib assert kills the interpreter
- Where: session.py:193-196, 320-323. It raises `PanicException` (03's high finding). The guard is right; the reason is wrong.

### [low] `Repo` context manager does nothing
- Where: session.py:91-95. `with pyjj.open()` suggests a release; nothing is held. Either drop it or release the loaded repo.

### [low] graph_dot parse edge cases
- Where: graph_dot.py:199-205. A real node labelled `(not shown)` is dropped (`dotprobe.log`); `style="dashed,bold"` reads as `direct`. graph_dot.py:96-103 is O(n^2) (`list.pop(0)`, `child not in order`). Use a node attribute for the placeholder, split `style` on commas, and `collections.deque`.

### [low] Lane typing mismatch
- Where: graph_layout.py:14-18, 135-149. Helpers typed for `CommitId` lanes are called with `object` keys (both checkers flag it). `GraphNode`/`CommitId` aliases are runtime imports used only for typing. Make the helpers generic over a `Hashable` key and import under `TYPE_CHECKING`.

### [low] `revert` and `commit` duplicate CLI templates in Python
- Where: session.py:535-539. The revert description is jj's default template, hand-copied. Fine today; note it with the other CLI-wording findings (04).

### [low] Unused `noqa` and `type: ignore`
- Where: session.py:72,135,142,294; __init__.py:76-78; 10 in hunk.py. Remove once tool config exists.

## Checked and fine
- `_async.py`: nothing beyond 02. The wrapped Workspace methods take `ReadonlyRepo`/`Commit`, which are not `unsendable`, so running them on a worker thread is safe.
- `_commit` resolves through the transaction and loads via the shared store: correct.
- `_refuse_conflicts` compares against conflicts present at block start: correct, and run inside the guard.
- hunk.py text handling: no trailing newline, CRLF, ` ` and empty files round-trip (`hunkprobe.log`).
- graph_dot `render_dot`/`parse_dot` round-trip through libcgraph; `resolve_plan` cycle and self-parent checks work.
