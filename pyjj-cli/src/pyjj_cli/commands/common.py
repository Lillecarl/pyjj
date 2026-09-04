"""Shared helpers for CLI commands."""
"""CLI command implementations exercising pyjj bindings."""
import json
import os
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

import pyjj
import pyjj.hunk as hunk_mod
def complete_newline(s: str) -> str:
    """The real CLI's text_util::complete_newline: append exactly one
    trailing newline to non-empty text lacking one; empty stays empty.
    jj_lib stores descriptions verbatim, so this normalization lives at
    the frontend."""
    if s and not s.endswith("\n"):
        return s + "\n"
    return s

def join_message_paragraphs(paragraphs) -> str:
    """The real CLI's description_util::join_message_paragraphs: each -m
    becomes a paragraph completed with a newline, paragraphs separated by
    one blank line."""
    return "\n".join(complete_newline(p) for p in paragraphs)

class CommandError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message

def _run_editor(settings, content: str) -> str:
    """Run $EDITOR (or ui.editor) over `content`, then clean it up exactly
    like the real CLI's description_util::edit_description: strip "JJ:"
    comment lines (stopping at "JJ: ignore-rest"), trim blank edges, and
    complete the trailing newline."""
    editor_cmd = (
        settings.get_string("ui.editor")
        or os.environ.get("JJ_EDITOR")
        or os.environ.get("VISUAL")
        or os.environ.get("EDITOR")
        or "nano"
    )
    argv = shlex.split(editor_cmd)

    prepped = content
    if prepped and not prepped.endswith("\n"):
        prepped += "\n"
    last_line = prepped.splitlines()[-1] if prepped.splitlines() else ""
    prepped += "JJ:\n" if last_line.startswith("JJ:") else "\n"
    prepped += 'JJ: Lines starting with "JJ:" (like this one) will be removed.\n'

    with tempfile.NamedTemporaryFile(
        "w", suffix=".jjdescription", delete=False
    ) as f:
        f.write(prepped)
        path = f.name
    try:
        subprocess.run([*argv, path], check=True)
        with open(path, encoding="utf-8") as f:
            edited = f.read()
    finally:
        os.unlink(path)

    kept: list[str] = []
    for line in edited.splitlines():
        if line.startswith("JJ: ignore-rest"):
            break
        if line.startswith("JJ:"):
            continue
        kept.append(line)
    return complete_newline("\n".join(kept).strip("\n"))

# `--ignore-working-copy` -- and `--at-operation`, which implies it --
# decide once per process whether this command may touch the working
# copy. That is what jj models too, so a module-level setting is the
# honest shape: threading one boolean through every command's call to
# `_finish` would say the same thing in forty places.
_IGNORE_WORKING_COPY = False


def set_ignore_working_copy(value: bool) -> None:
    """Called once by `main()` from the parsed globals."""
    global _IGNORE_WORKING_COPY
    _IGNORE_WORKING_COPY = bool(value)


def _workspace_path(args) -> str:
    """The workspace directory this command should load.

    `-R` names it outright. Without `-R`, jj walks up from the current
    directory looking for a `.jj`, so a command works anywhere inside a
    workspace and not only at its root (`find_workspace_dir` in
    `cli/src/cli_util.rs`). A search that finds nothing falls back to the
    current directory, which then fails with the same "no repo here"
    error as before.
    """
    if args.repository is not None:
        return args.repository
    cwd = Path(os.getcwd()).resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".jj").is_dir():
            return str(candidate)
    return str(cwd)


def _open(settings, args):
    """The repo this command should act on.

    Normally that is the head, snapshotted first like every real jj
    workspace command does. `--at-operation` names a past operation
    instead, and jj documents that as implying `--ignore-working-copy`:
    a snapshot would write into a view the command is only visiting.
    """
    ws = pyjj.Workspace.load(settings, _workspace_path(args))
    at_op = getattr(args, "at_operation", None)
    if at_op:
        repo = ws.load_at_head()
        return ws, repo.load_at_operation(_resolve_operation(repo, at_op))
    if _IGNORE_WORKING_COPY:
        return ws, ws.load_at_head()
    repo, _stats = ws.snapshot(settings)
    return ws, repo


def _load(args):
    """Load settings + workspace at the -R path, snapshotting the working
    copy first like every real jj workspace command does."""
    settings = pyjj.UserSettings()
    ws, repo = _open(settings, args)
    return settings, ws, repo

def _reload(settings, args):
    """Re-open the workspace at its current head, reusing `settings`.

    Not `_load()`: that builds a fresh `UserSettings`, and jj_lib seeds a
    new change-id RNG from `debug.randomness-seed` every time one is
    built. A command that reloads mid-run would restart that sequence and
    draw the same change id again, where `jj` -- which builds its
    settings once per process -- draws the next one. Only commands that
    write commits after a reload can tell, but for those it is the
    difference between matching `jj` and not."""
    return _open(settings, args)

def _resolve_all(repo, settings, expressions):
    """Resolve positional REVSETS the way the real CLI does for target
    SETS (describe/abandon/duplicate/...): as ONE union expression, so
    evaluation order -- which drives seeded change-id draws -- matches
    `jj` exactly."""
    if not expressions:
        return []
    if len(expressions) == 1:
        return repo.revset(settings, expressions[0])
    union = " | ".join(f"({expr})" for expr in expressions)
    return repo.revset(settings, union)

def _resolve_in_arg_order(repo, settings, expressions):
    """Resolve expressions where the ARGUMENT ORDER is semantic (parents
    of a new commit, rebases' -d destinations): evaluate each positional
    separately and concatenate, like the real CLI's parent-list handling."""
    commits = []
    for expr in expressions:
        commits.extend(repo.revset(settings, expr))
    return commits

def _resolve_one(repo, settings, expression):
    matches = repo.revset(settings, expression)
    if len(matches) != 1:
        raise CommandError(f"revset `{expression}` resolved to {len(matches)} revisions")
    return matches[0]

def _wc_commit(repo, ws):
    return repo.get_commit(pyjj.CommitId(repo.view()[ws.workspace_name]))

def _checkout_if_moved(settings, ws, old_wc_hex) -> None:
    """Mirror the real CLI's transaction-finish behavior: when the current
    view's working-copy commit differs from `old_wc_hex`, update the
    on-disk working copy to match."""
    if _IGNORE_WORKING_COPY:
        # jj's `--ignore-working-copy` is both halves: don't snapshot at
        # the start, and don't update the working copy at the end.
        return
    fresh_ws = pyjj.Workspace.load(settings, ws.workspace_root)
    fresh_repo = fresh_ws.load_at_head()
    new_wc_hex = fresh_repo.view()[fresh_ws.workspace_name]
    if new_wc_hex != old_wc_hex:
        fresh_ws.check_out(fresh_repo, fresh_repo.get_commit(pyjj.CommitId(new_wc_hex)))

def _split_remote_ref(name: str, default_remote):
    """`BOOKMARK@REMOTE` -> `("BOOKMARK", "REMOTE")`.

    jj takes the remote in the name itself, and `--remote` only supplies
    it for names that leave it out. A name with no remote and no
    `--remote` is an error, not a guess at `origin`.
    """
    bookmark, sep, remote = name.rpartition("@")
    if sep:
        return bookmark, remote
    if not default_remote:
        raise CommandError(
            f"Bookmark {name} has no remote; use NAME@REMOTE or --remote"
        )
    return name, default_remote

def _wants_edit(args) -> bool:
    """`--edit`/`--no-edit` for `jj next`/`jj prev`. The last flag wins in
    jj's parser, and argparse's default store_true/store_false pair gives
    the same result."""
    return bool(getattr(args, "edit", False))

def _walk(repo, settings, start_hexes, direction, steps, exclude=()):
    """Walk `steps` graph edges from `start_hexes`, forward or backward.

    Returns the hex ids reached, or `[]` when the walk runs out of edges.
    `exclude` drops commits from every level -- `jj next` needs it to
    ignore the working copy itself when stepping forward from its parent.
    """
    current = list(start_hexes)
    for _ in range(steps):
        if not current:
            return []
        expression = f"{direction}({'|'.join(current)})"
        reached = [
            c.id.hex()
            for c in repo.revset(settings, expression)
            if c.id.hex() not in exclude
        ]
        if not reached:
            return []
        current = reached
    return current

def _commit_location(repo, settings, ontos, afters, befores):
    """jj's `compute_commit_location`: the new parents and new children a
    placement flag asks for.

    `--onto`/`-d` names the parents outright and moves nothing else.
    `-A` puts the commit after the named revisions, so their children
    become its children. `-B` puts it before them, so they become its
    children and their parents become its parents. `-A` and `-B` together
    name both sides directly. Argument order is kept, because a merge's
    parent order is part of its commit id.
    """
    if ontos:
        return [c.id for c in _resolve_in_arg_order(repo, settings, ontos)], []
    if afters and befores:
        return ([c.id for c in _resolve_in_arg_order(repo, settings, afters)],
                [c.id for c in _resolve_in_arg_order(repo, settings, befores)])
    if afters:
        parents = _resolve_in_arg_order(repo, settings, afters)
        expression = " | ".join(f"children({after})" for after in afters)
        return ([c.id for c in parents],
                [c.id for c in repo.revset(settings, expression)])
    # `-B` alone. jj resolves the parents from the commits themselves
    # rather than through a `parents()` revset, to keep their order.
    children = _resolve_in_arg_order(repo, settings, befores)
    seen: dict[str, object] = {}
    for child in children:
        for parent_id in child.parent_ids:
            seen.setdefault(parent_id.hex(), parent_id)
    return list(seen.values()), [c.id for c in children]


def _insert_between(tx, repo, new_parent_ids, new_child_ids, head_id):
    """Hook the named children onto a commit inserted above them.

    jj's rule, shared by `new` and `revert`: a child parent that is one of
    the insertion point's own parents gets replaced by the inserted
    commit, and every other parent stays. The inserted commit is then
    added if it is not there already, so a child that hangs from
    somewhere else keeps that edge and gains a second one.

    Rebasing rather than setting the parents matters: the child's tree has
    to be re-merged against the parents it now has.
    """
    parent_hexes = {parent.hex() for parent in new_parent_ids}
    for child_id in new_child_ids:
        child = repo.get_commit(child_id)
        parents = []
        seen = set()
        for old_parent in child.parent_ids:
            chosen = head_id if old_parent.hex() in parent_hexes else old_parent
            if chosen.hex() not in seen:
                seen.add(chosen.hex())
                parents.append(chosen)
        if head_id.hex() not in seen:
            parents.append(head_id)
        tx.rebase(child, parents)


def _check_rewritable(tx, settings, commits) -> None:
    """`jj`'s guard against rewriting shared history: refuse when any of
    `commits` falls inside `immutable()`.

    Every rewrite command in `jj` runs this before it writes, so pyjj-cli
    runs it too. `jj` checks before it opens a transaction; here the
    transaction already exists, which changes nothing: raising before
    `tx.commit()` leaves the transaction unwritten, so no operation is
    recorded either way.

    Takes `Commit`s or bare `CommitId`s, because the call sites hold one
    or the other.
    """
    ids = [getattr(commit, "id", commit) for commit in commits]
    tx.check_rewritable(settings, ids)


def _move_to(args, settings, ws, repo, targets, edit: bool, name: str) -> int:
    """Land `jj next`/`jj prev` on `targets`: edit the target itself, or
    create a new empty commit on top of it."""
    if len(targets) > 1:
        print(f"Error: Ambiguous target for {name}: "
              f"{', '.join(t[:12] for t in targets)}", file=sys.stderr)
        return 1
    target = repo.get_commit(pyjj.CommitId(targets[0]))
    tx = repo.start_transaction(settings)
    if edit:
        _check_rewritable(tx, settings, [target])
        tx.edit(ws.workspace_name, target)
        _finish(tx, f"{name} to {target.id.hex()}", settings, ws, repo)
    else:
        child = tx.new_commit(settings, [target.id]).write(repo)
        tx.set_wc_commit(ws.workspace_name, child.id)
        _finish(tx, "new empty commit", settings, ws, repo)
    return 0

def _export_git_refs(tx, ws) -> None:
    """Write the transaction's bookmarks and tags out to the git repo.

    jj does this on every transaction it finishes, but only when the
    working copy is shared with git -- see the
    `working_copy_shared_with_git` guard in `cli/src/cli_util.rs`. The
    pinned `jj git init` colocates by default, so this is the common
    case, and without it every bookmark move leaves `<name>@git` behind
    on the commit the bookmark used to point at.

    A non-colocated repo keeps its git refs inside `.jj`, and jj never
    exports there, so neither does this.
    """
    if not (Path(ws.workspace_root) / ".git").exists():
        return
    # jj resets HEAD first, then exports. HEAD tracks `@`'s first parent,
    # so a command that only moves `@` still has to update it.
    tx.git_reset_head(ws.workspace_name)
    tx.git_export_refs()


def _finish(tx, description, settings, ws, base_repo, *, delete_abandoned_bookmarks=False):
    """Commit the transaction, then mirror the real CLI's
    transaction-finish behavior: when a rewrite moved the working-copy
    commit (e.g. an abandon or rebase rebased it), update the on-disk
    working copy to match."""
    old_wc_hex = base_repo.view()[ws.workspace_name]
    tx.rebase_descendants(delete_abandoned_bookmarks)
    _export_git_refs(tx, ws)
    tx.commit(description)
    _checkout_if_moved(settings, ws, old_wc_hex)

def _restore_view_command(tx, description, settings, ws, repo):
    """Shared tail for view-restoring operations (undo/redo/op restore):
    they produce no rewrites to rebase and take their operation description
    verbatim from the binding -- for undo/redo it encodes the target op so
    future stack jumps keep working."""
    old_wc_hex = repo.view()[ws.workspace_name]
    _export_git_refs(tx, ws)
    tx.commit(description)
    _checkout_if_moved(settings, ws, old_wc_hex)


# -- commands --------------------------------------------------------------

def _changed_files(repo, settings, from_commit, to_commit):
    """{path: (before_bytes_or_absent, after_bytes_or_absent)} for the diff
    between two commits, using the same sentinel-absence convention the
    diff-editor protocol needs."""
    changed = {}
    for entry in from_commit.diff(to_commit):
        path = entry.path

        def read(commit, p=path):
            return commit.read_file(p) if commit.file_exists(p) else None

        changed[path] = (read(from_commit), read(to_commit))
    return changed

def _run_diff_tool(settings, tool: str, before: dict, after: dict) -> dict:
    """The merge-tools edit protocol: materialize $left/$right temp dirs
    holding exactly the changed paths (left = before, read-only in spirit;
    right = editable), invoke merge-tools.<tool>.edit-args with the
    placeholders substituted, then snapshot the RIGHT directory --
    surviving files carry their edited bytes, deleted files become None,
    and brand-new files are picked up too."""
    args_tmpl = settings.get_string_list(f"merge-tools.{tool}.edit-args")
    if not args_tmpl:
        raise CommandError(
            f"No edit-args configured for diff editor '{tool}' "
            "(set merge-tools.<name>.edit-args)"
        )
    # The program is merge-tools.<name>.program (default: the tool name,
    # resolved via PATH), mirroring upstream's ExternalMergeTool.
    program = settings.get_string(f"merge-tools.{tool}.program") or tool
    with tempfile.TemporaryDirectory(prefix="pyjj-diff-") as td:
        left_dir = Path(td) / "left"
        right_dir = Path(td) / "right"
        for base, files in ((left_dir, before), (right_dir, after)):
            for rel, content in files.items():
                p = base / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                if content is not None:
                    p.write_bytes(content)
        argv = [program] + [
            arg.replace("$left", str(left_dir))
            .replace("$right", str(right_dir))
            .replace("$output", str(right_dir))
            for arg in args_tmpl
        ]
        subprocess.run(argv, check=True)

        selections: dict[str, bytes | None] = {}
        for rel in set(before) | set(after):
            rp = right_dir / rel
            selections[rel] = rp.read_bytes() if rp.exists() else None
        for p in right_dir.rglob("*"):
            if p.is_file():
                rel = p.relative_to(right_dir).as_posix()
                if rel not in selections:
                    selections[rel] = p.read_bytes()
        return selections

def _selection_is_empty(selections: dict, before: dict) -> bool:
    """True when every path ended up identical to its before-state."""
    for rel, content in selections.items():
        if content != before.get(rel):
            return False
    return True

def _merge_marker_len(materialized: bytes) -> int:
    """The marker length jj would have chosen to render this conflict
    (max of the 7-char minimum and the longest marker run actually
    present) -- used for the $marker_length substitution."""
    longest = 7
    for line in materialized.split(b"\n"):
        if line.startswith(b"<"):
            longest = max(longest, len(line) - len(line.lstrip(b"<")))
    return longest

def _run_merge_tool(settings, tool: str, sides: dict, path: str,
                    edits_markers: bool, materialized: bytes) -> bytes:
    """The 3-way merge-tool protocol for one conflicted file: materialize
    $base/$left/$right (read-only) plus $output into a temp dir named like
    upstream's (`{role}_{filename}`), invoke
    merge-tools.<tool>.program with merge-args substituted, and return the
    output file's final bytes. The caller decides whether those bytes mean
    full resolution, partial markers, or an unchanged no-op."""
    args_tmpl = settings.get_string_list(f"merge-tools.{tool}.merge-args")
    if not args_tmpl:
        raise CommandError(
            f"No merge-args configured for merge tool '{tool}' "
            "(set merge-tools.<name>.merge-args)"
        )
    program = settings.get_string(f"merge-tools.{tool}.program") or tool
    filename = PurePosixPath(path).name or "file"
    with tempfile.TemporaryDirectory(prefix="jj-resolve-") as td:
        roles = {
            "base": sides["base"],
            "left": sides["left"],
            "right": sides["right"],
            "output": materialized if edits_markers else b"",
        }
        variables = {}
        for role, content in roles.items():
            p = Path(td) / f"{role}_{filename}"
            p.write_bytes(content)
            if role != "output":
                p.chmod(0o444)
            variables[f"${role}"] = str(p)
        variables["$path"] = path
        variables["$marker_length"] = str(_merge_marker_len(materialized))
        argv = [program] + [
            arg.replace("$base", variables["$base"])
            .replace("$left", variables["$left"])
            .replace("$right", variables["$right"])
            .replace("$output", variables["$output"])
            .replace("$path", variables["$path"])
            .replace("$marker_length", variables["$marker_length"])
            for arg in args_tmpl
        ]
        proc = subprocess.run(argv)
        if proc.returncode != 0:
            # Mirrors upstream's ToolAborted: a failing tool aborts the
            # whole command before anything is written.
            raise CommandError(
                f"Tool exited with status {proc.returncode}, "
                "but did not produce a valid resolution"
            )
        return Path(variables["$output"]).read_bytes()

def _fix_pattern_matches(pattern: str, path: str) -> bool:
    """Match a fix.tools pattern (e.g. ``glob:'**/*.py'``) against a repo path."""
    pat = pattern.strip()
    # Strip ``glob:`` prefix if present
    if pat.startswith("glob:"):
        pat = pat[5:].strip()
        # Strip surrounding quotes (single or double)
        if len(pat) >= 2 and ((pat[0] == "'" and pat[-1] == "'") or (pat[0] == '"' and pat[-1] == '"')):
            pat = pat[1:-1]
    else:
        # Also strip quotes for bare patterns like ``"word_list.txt"``
        if len(pat) >= 2 and ((pat[0] == "'" and pat[-1] == "'") or (pat[0] == '"' and pat[-1] == '"')):
            pat = pat[1:-1]
    # Exact match fast-path
    if pat == path:
        return True
    # Handle ``**/`` prefix which PurePosixPath.match doesn't match at top-level
    # (e.g. ``**/*.txt`` should match ``a.txt`` as well as ``sub/a.txt``).
    # Real jj's fileset/glob does, so we try both with and without the ``**/``.
    candidates = [pat]
    if pat.startswith("**/"):
        candidates.append(pat[3:])
    # Also handle ``**/`` in the middle? For now handle the common prefix case.
    for cand in candidates:
        try:
            if PurePosixPath(path).match(cand):
                return True
        except Exception:
            continue
    return False


def _jj_config_get(key: str, cwd=None) -> str | None:
    """Read one dotted config key the way `jj` itself does, repo config
    included.

    `UserSettings` does not load repo config on purpose (see AGENTS.md's
    Config section). `jj` keeps repo config outside the repo: the id in
    `.jj/repo/config-id` names a directory under the user's config dir.
    That indirection is `jj_lib::secure_config`. Do not copy it here --
    ask `jj` for the value instead, so pyjj follows the same rules.

    `jj config get` prints the raw string with no TOML quotes, so the
    value needs no unquoting."""
    try:
        result = subprocess.run(
            ["jj", "config", "get", key],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    value = result.stdout
    if value.endswith("\n"):
        value = value[:-1]
    return value or None

def _pyjj_template(settings, name: str, cwd=None) -> str | None:
    """Look up `pyjj.templates.<name>`: user config first, then repo config."""
    key = f"pyjj.templates.{name}"
    try:
        value = settings.get_string(key)
    except pyjj.JjError:
        value = None
    if value is not None:
        return value
    return _jj_config_get(key, cwd)


def _resolve_operation(repo, name: str | None):
    """Resolve an operation the way `jj` names them on the command line.

    `@` means the operation the repo is loaded at. Anything else is a
    full hex id, which is what the binding takes. `None` means `@` too,
    so a command can pass an absent argument straight through.
    """
    if not name or name == "@":
        return repo.operation
    return repo.load_operation(name)


# The bar after a file's line count is scaled to fit the terminal in jj.
# pyjj draws it at a fixed width instead: the histogram is decoration,
# and a width that depends on the terminal makes output that scripts
# cannot rely on.
_STAT_BAR_WIDTH = 32


_SUMMARY_STATUS_CHARS = {
    "added": "A",
    "removed": "D",
    "modified": "M",
    "executable": "M",
    "copied": "C",
    "renamed": "R",
}


def _summary_lines(entries, to_ui_path=None) -> list[str]:
    """`jj diff --summary`'s lines: one status letter, a space, the path.

    jj has no separate letter for a mode-only change, so an
    `"executable"` entry reads as modified, which is what jj prints for
    it.
    """
    to_ui_path = to_ui_path or (lambda path: path)
    return [f"{_SUMMARY_STATUS_CHARS[e.status]} {to_ui_path(e.path)}" for e in entries]


def _relative_path(from_dir: Path, to: Path) -> str:
    """jj's `file_util::relative_path`.

    `os.path.relpath` is not the same function. It walks up with `..`
    however far it has to; jj gives up and prints the absolute path when
    the two share no prefix at all, which happens when `-R` names a
    workspace the current directory is nowhere near.
    """
    for i, base in enumerate([from_dir, *from_dir.parents]):
        if not to.is_relative_to(base):
            continue
        suffix = to.relative_to(base)
        if i == 0:
            return "." if str(suffix) == "." else str(suffix)
        return str(Path(*([".."] * i), suffix))
    return str(to)


def _ui_path_formatter(ws):
    """How this invocation spells a repo-relative path back to the user.

    jj prints paths relative to the current directory, not to the
    workspace root, so `jj status` run in a subdirectory names a file
    there by its bare name. The parity harness always runs at the
    workspace root, where the two spellings agree, so it cannot see this
    -- the repo-discovery tests are what catch it.
    """
    cwd = Path.cwd()
    root = Path(ws.workspace_root)
    return lambda path: _relative_path(cwd, root / path)


def _bookmarks_by_commit(repo, remotes: bool = False) -> dict[str, list[str]]:
    """Bookmark names per commit, keyed by hex commit id.

    `remotes` adds the remote-tracking bookmarks as `name@remote`, which
    is what jj lists in a commit's header. A colocated repository has a
    `git` remote, so an exported bookmark appears twice there -- `main`
    and `main@git`.
    """
    by_commit: dict[str, list[str]] = {}
    for bookmark in repo.bookmarks():
        for target in bookmark.target_ids:
            by_commit.setdefault(target.hex(), []).append(bookmark.name)
    if remotes:
        for bookmark in repo.remote_bookmarks():
            for target in bookmark.target_ids:
                by_commit.setdefault(target.hex(), []).append(bookmark.symbol)
    return by_commit


def _short_id(hex_str: str, shortest_len: int) -> str:
    """jj's `shortest(8)`: the unique prefix, but never under 8."""
    return hex_str[: max(8, shortest_len)]


def _is_empty(repo, commit) -> bool:
    """Whether a commit changes nothing, the way jj's `empty()` decides.

    `Commit.is_empty()` answers `False` for a parentless commit, since
    there is nothing to compare against. jj compares against an empty
    tree there instead, so the root commit reads as empty -- and jj
    prints `(empty)` for it.
    """
    if not commit.parent_ids:
        return not commit.list_files()
    return commit.is_empty(repo)


def _local_tz_offset_minutes() -> int:
    """The offset jj's `timestamp.local()` applies.

    jj takes `chrono::Local::now().offset()` -- the offset in force
    *now* -- and stamps it onto every timestamp it prints, rather than
    the offset that was in force when the commit was made. A commit from
    a winter day therefore prints in summer time when read in summer.
    `JJ_TZ_OFFSET_MINS` overrides it.

    This is not a detail worth guessing at: the parity fixture pins its
    commits to 2001 and the suite runs today, so the two rules disagree
    by an hour for half the year.
    """
    override = os.environ.get("JJ_TZ_OFFSET_MINS")
    if override is not None:
        try:
            return int(override)
        except ValueError:
            pass
    offset = datetime.now().astimezone().utcoffset()
    return int(offset.total_seconds() // 60) if offset else 0


def _format_timestamp(timestamp) -> str:
    """jj's `format_timestamp`: the local time, to the second."""
    moment = datetime.fromtimestamp(
        timestamp.millis_since_epoch / 1000, timezone.utc
    )
    zone = timezone(timedelta(minutes=_local_tz_offset_minutes()))
    return moment.astimezone(zone).strftime("%Y-%m-%d %H:%M:%S")


def _detailed_signature(signature) -> str:
    """jj's `format_detailed_signature`: name, angle-bracketed email and
    the timestamp in parentheses, with a placeholder for either half
    that is missing."""
    name = signature.name or "(no name set)"
    email = signature.email or "(no email set)"
    return f"{name} <{email}> ({_format_timestamp(signature.timestamp)})"


def _indent(text: str, prefix: str = "    ") -> str:
    """jj's `indent`: every non-empty line gets the prefix.

    A blank line stays blank rather than becoming four spaces, so a
    description with a paragraph break has no trailing whitespace in it.
    """
    return "\n".join(prefix + line if line else line for line in text.split("\n"))


def _commit_summary(repo, settings, commit, bookmarks=None) -> str:
    """One commit as jj's `commit_summary` template renders it.

    jj builds this from `format_commit_summary_with_refs`, and several
    commands print it -- `status` names the working copy and its parents
    with it, and so do many hints. The shape is

        <change id> <commit id> [<bookmarks> | ][(conflict) ][(empty) ]<description>

    with each absent part dropped along with its separator, and `(no
    description set)` standing in for an empty description.

    Two details are jj's and not obvious. The change id prints in jj's
    reverse-hex spelling, not the raw hex the id carries. Both ids print
    their shortest unique prefix, with a floor of eight characters, so
    the width grows only when a repository needs it to.

    A hidden or divergent commit also gets a marker and a change offset;
    neither is produced here yet.
    """
    if bookmarks is None:
        bookmarks = _bookmarks_by_commit(repo).get(commit.id.hex(), [])
    change = _short_id(
        commit.change_id.reverse_hex(),
        repo.shortest_change_id_prefix_len(commit.change_id, settings),
    )
    commit_id = _short_id(
        commit.id.hex(),
        repo.shortest_commit_id_prefix_len(commit.id, settings),
    )
    rest = []
    if commit.has_conflict:
        rest.append("(conflict)")
    if _is_empty(repo, commit):
        rest.append("(empty)")
    first_line = commit.description.splitlines()[0] if commit.description else ""
    rest.append(first_line if first_line else "(no description set)")
    tail = " ".join(rest)
    if bookmarks:
        tail = " ".join(bookmarks) + " | " + tail
    return f"{change} {commit_id} {tail}"


def _git_diff_bytes(files, context: int = 3) -> bytes:
    """`jj diff --git`'s output for a list of `Commit.git_diff()` files.

    The layout follows jj's `show_git_diff`. Two details differ from what
    `git diff` prints, and both are jj's: the `@@` header always carries
    both counts, even a count of one, and the abbreviated hashes are ten
    characters wide.

    File content is bytes, and may not be text at all, so this returns
    bytes rather than printing.
    """
    out = bytearray()

    def line(text: str) -> None:
        out.extend(text.encode())
        out.extend(b"\n")

    for f in files:
        left = f"a/{f.source_path}"
        right = f"b/{f.path}"
        line(f"diff --git {left} {right}")
        if f.before_mode is None:
            line(f"new file mode {f.after_mode}")
            line(f"index {f.before_hash}..{f.after_hash}")
        elif f.after_mode is None:
            line(f"deleted file mode {f.before_mode}")
            line(f"index {f.before_hash}..{f.after_hash}")
        else:
            if f.copy_operation is not None:
                line(f"{f.copy_operation} from {f.source_path}")
                line(f"{f.copy_operation} to {f.path}")
            if f.before_mode != f.after_mode:
                line(f"old mode {f.before_mode}")
                line(f"new mode {f.after_mode}")
                if f.before_hash != f.after_hash:
                    line(f"index {f.before_hash}..{f.after_hash}")
            elif f.before_hash != f.after_hash:
                line(f"index {f.before_hash}..{f.after_hash} {f.before_mode}")
        if f.before_content == f.after_content:
            continue
        left_name = left if f.before_mode is not None else "/dev/null"
        right_name = right if f.after_mode is not None else "/dev/null"
        if f.is_binary:
            line(f"Binary files {left_name} and {right_name} differ")
            continue
        line(f"--- {left_name}")
        line(f"+++ {right_name}")
        for hunk in pyjj.unified_hunks(f.before_content, f.after_content, context):
            line(f"@@ -{hunk.left_start},{hunk.left_len} "
                 f"+{hunk.right_start},{hunk.right_len} @@")
            for kind, content in hunk.lines:
                out.extend(_DIFF_SIGILS[kind])
                out.extend(content)
                if not content.endswith(b"\n"):
                    out.extend(b"\n\\ No newline at end of file\n")
    return bytes(out)


def _tags_by_commit(repo) -> dict[str, list[str]]:
    """Tag names per commit, keyed by hex commit id."""
    by_commit: dict[str, list[str]] = {}
    for tag in repo.tags():
        for target in tag.target_ids:
            by_commit.setdefault(target.hex(), []).append(tag.name)
    return by_commit


_FILE_TYPES = {
    "100644": "regular file",
    "100755": "executable file",
    "120000": "symlink",
    "040000": "Git submodule",
}

# `unified_hunks` trims context; the color-words format trims its own,
# with different rules at the start and the end of a file. Asking for
# every line keeps the classification and the numbering and leaves the
# trimming here.
_ALL_CONTEXT = 1 << 30


def _color_words_header(f, to_ui_path) -> str:
    """The line jj writes above a file's color-words diff.

    jj names the file by what it is on each side, so a mode change reads
    as a sentence rather than a diff -- `Non-executable file became
    executable at b.txt:`.
    """
    path = to_ui_path(f.path)
    if f.before_mode is None:
        return f"Added {_FILE_TYPES[f.after_mode]} {path}:"
    if f.after_mode is None:
        return f"Removed {_FILE_TYPES[f.before_mode]} {path}:"
    before, after = f.before_mode, f.after_mode
    if before == after == "100755":
        description = "Modified executable file"
    elif before == "100755" and after == "100644":
        description = "Executable file became non-executable at"
    elif before == "100644" and after == "100755":
        description = "Non-executable file became executable at"
    elif before == after == "120000":
        description = "Symlink target changed at"
    elif before == after == "100644":
        description = "Modified regular file"
    else:
        left, right = _FILE_TYPES[before], _FILE_TYPES[after]
        description = f"{left[0].upper()}{left[1:]} became {right} at"
    if f.source_path != f.path:
        source = to_ui_path(f.source_path)
        return f"{description} {path} ({source} => {path}):"
    return f"{description} {path}:"


def _color_words_line(left, right, content: bytes) -> bytes:
    """One numbered line. A missing number leaves its column blank."""
    prefix = f"{left:>4} " if left is not None else "     "
    prefix += f"{right:>4}: " if right is not None else "    : "
    return prefix.encode() + content


def _color_words_hunks(before: bytes, after: bytes, context: int = 3) -> list[bytes]:
    """The numbered body of a color-words diff.

    jj keeps `context` unchanged lines after a change and `context`
    before the next one, and replaces what is left with `    ...`. It
    keeps nothing before the first change and nothing after the last.

    A run that would lose exactly one line prints that line instead: the
    ellipsis costs the same row, so eliding it gains nothing. That is
    the `num_after + num_before + 1` below, and it is jj's rule, not a
    rounding choice.
    """
    hunks = pyjj.unified_hunks(before, after, _ALL_CONTEXT)
    if not hunks:
        return []
    out: list[bytes] = []
    left = right = 1
    run: list[bytes] = []
    emitted = False

    def flush(num_after: int, num_before: int) -> None:
        nonlocal left, right, run
        total = len(run)
        if total > num_after + num_before + 1:
            head, tail = run[:num_after], run[total - num_before:]
            skipped = total - num_after - num_before
        else:
            head, tail, skipped = run, [], 0
        for content in head:
            out.append(_color_words_line(left, right, content))
            left += 1
            right += 1
        if skipped:
            out.append(b"    ...\n")
            left += skipped
            right += skipped
        for content in tail:
            out.append(_color_words_line(left, right, content))
            left += 1
            right += 1
        run = []

    for kind, content in hunks[0].lines:
        if kind == "context":
            run.append(content)
            continue
        flush(context if emitted else 0, context)
        emitted = True
        if kind == "removed":
            out.append(_color_words_line(left, None, content))
            left += 1
        else:
            out.append(_color_words_line(None, right, content))
            right += 1
    flush(context if emitted else 0, 0)
    return out


def _color_words_bytes(files, to_ui_path, context: int = 3) -> bytes:
    """`jj diff`'s default output for a list of `Commit.git_diff()` files.

    A conflicted path reads as a regular file here. jj names it a
    conflict and says whether the change created, resolved or moved it;
    `git_diff()` has already materialized the markers by this point, so
    that distinction is gone. The status scenarios mark the gap.
    """
    out = bytearray()
    for f in files:
        out.extend(_color_words_header(f, to_ui_path).encode())
        out.extend(b"\n")
        added = f.before_mode is None
        removed = f.after_mode is None
        content = f.after_content if added else f.before_content
        if (added or removed) and not content:
            out.extend(b"    (empty)\n")
            continue
        if f.is_binary:
            out.extend(b"    (binary)\n")
            continue
        before = b"" if added else f.before_content
        after = b"" if removed else f.after_content
        if before == after:
            continue
        for line in _color_words_hunks(before, after, context):
            out.extend(line)
            if not line.endswith(b"\n"):
                out.extend(b"\n")
    return bytes(out)


def _print_color_words_diff(from_commit, to_commit, settings, ws, paths=None) -> None:
    """Writes `jj diff`'s default output to stdout."""
    files = from_commit.git_diff(to_commit, settings, paths)
    sys.stdout.flush()
    sys.stdout.buffer.write(_color_words_bytes(files, _ui_path_formatter(ws)))
    sys.stdout.buffer.flush()


_DIFF_SIGILS = {"context": b" ", "removed": b"-", "added": b"+"}


def _print_git_diff(from_commit, to_commit, settings, paths=None) -> None:
    """Writes `jj diff --git`'s output to stdout."""
    files = from_commit.git_diff(to_commit, settings, paths)
    sys.stdout.flush()
    sys.stdout.buffer.write(_git_diff_bytes(files))
    sys.stdout.buffer.flush()


def _print_diff_stats(stats) -> None:
    """`--stat`'s output, in the shape `jj diff --stat` prints it.

    Each file gets its changed-line count and a `+`/`-` bar; a binary
    file gets its byte delta instead, since it has no lines to count.
    The summary line counts every file, binary ones included.
    """
    paths = [stat.path for stat in stats]
    width = max((len(path) for path in paths), default=0)
    total_added = 0
    total_removed = 0
    for stat in stats:
        if stat.added is None:
            delta = f" {stat.bytes_delta:+} bytes" if stat.bytes_delta else ""
            print(f"{stat.path:<{width}} | (binary){delta}")
            continue
        total_added += stat.added
        total_removed += stat.removed
        changed = stat.added + stat.removed
        if changed:
            # Keep at least one mark for each side that moved, so a bar
            # never claims a file gained nothing when it gained a line.
            scale = min(1.0, _STAT_BAR_WIDTH / changed)
            bar_added = max(1, round(stat.added * scale)) if stat.added else 0
            bar_removed = max(1, round(stat.removed * scale)) if stat.removed else 0
            bar = " " + "+" * bar_added + "-" * bar_removed
        else:
            bar = ""
        print(f"{stat.path:<{width}} | {changed}{bar}")
    print(f"{len(stats)} file{'' if len(stats) == 1 else 's'} changed, "
          f"{total_added} insertion{'' if total_added == 1 else 's'}(+), "
          f"{total_removed} deletion{'' if total_removed == 1 else 's'}(-)")


def _diff_base(repo, settings, commit):
    """What a one-revision diff compares against: the first parent, or
    the root commit when there is none.

    jj diffs a parentless commit against the root commit, whose tree is
    empty, so every file in it reads as added. Every format goes through
    here, so none of them needs a branch for the case.
    """
    if commit.parent_ids:
        return repo.get_commit(commit.parent_ids[0])
    return repo.revset(settings, "root()")[0]


def _print_diff(args, ws, settings, base, target, paths) -> None:
    """One place that decides which format `jj diff` prints.

    jj's default is the color-words diff, not a file listing. The flags
    that replace it are `--git`, `--stat`, `--summary` and
    `--name-only`, and every path through `diff` reaches this with the
    same two commits, so they behave the same everywhere.
    """
    if getattr(args, "git", False):
        _print_git_diff(base, target, settings, paths)
        return
    if getattr(args, "stat", False):
        _print_diff_stats(base.diff_stats(target, settings, paths))
        return
    to_ui_path = _ui_path_formatter(ws)
    if getattr(args, "name_only", False):
        for entry in base.diff(target, paths):
            print(to_ui_path(entry.path))
        return
    if getattr(args, "summary", False):
        for line in _summary_lines(base.diff(target, paths), to_ui_path):
            print(line)
        return
    _print_color_words_diff(base, target, settings, ws, paths)
