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

from ..formatter import Formatter, Line, render_block, separate


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
    repo, _stats = ws.snapshot(settings, _operation_args())
    return ws, repo


# The characters jj leaves unquoted when it records a command line on
# an operation. Anything else makes the whole argument single-quoted.
_ARG_SAFE = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789,-./:@_"
)


# The argv `main()` was given, which is not always `sys.argv`: the
# parity driver calls `main()` directly. Set once per process.
_OPERATION_ARGV: list[str] = []


def set_operation_args(argv) -> None:
    global _OPERATION_ARGV
    _OPERATION_ARGV = list(argv)


# What `--color` asked for, or None when it was not given. Set once per
# process, the same way the recorded argv is.
_COLOR_CHOICE: str | None = None


def set_color_choice(choice: str | None) -> None:
    global _COLOR_CHOICE
    _COLOR_CHOICE = choice


def use_color(settings=None) -> bool:
    """Whether to write escape sequences, by jj's rule.

    `--color` wins, then `ui.color`, then `auto`, which means stdout is
    a terminal. jj reads no environment variable here; `NO_COLOR` is
    pyjj-cli's own courtesy, and it can only turn colour off.

    `debug` asks for jj's `<<labels::text>>` markers rather than escape
    sequences. pyjj-cli does not carry the labels yet, so it prints the
    same plain text `never` does rather than pretending.
    """
    choice = _COLOR_CHOICE
    if choice is None and settings is not None:
        try:
            choice = settings.get_string("ui.color")
        except Exception:
            choice = None
    if choice == "always":
        return True
    if choice in ("never", "debug"):
        return False
    if os.environ.get("NO_COLOR") is not None:
        return False
    return sys.stdout.isatty()


def _operation_args() -> str:
    """The command line to record on this run's operations.

    jj writes an `args` attribute on every transaction, and `jj op log`
    prints it under the description. The program name is a constant
    rather than `argv[0]`, the same way jj's own is: the recorded line
    should read as a command anyone can run, not as whatever path this
    process happened to start from.
    """
    parts = ["pyjj"]
    for arg in _OPERATION_ARGV or sys.argv[1:]:
        if arg and all(char in _ARG_SAFE for char in arg):
            parts.append(arg)
        else:
            escaped = arg.replace("'", "\\'")
            parts.append(f"'{escaped}'")
    return " ".join(parts)


def _start_transaction(repo, settings):
    """Open a transaction with this run's command line recorded on it.

    Every write goes through here rather than through
    `repo.start_transaction` directly, so no command can quietly leave
    its operation without provenance.
    """
    return repo.start_transaction(settings, _operation_args())


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
    tx = _start_transaction(repo, settings)
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


def _tracking_distance_spans(repo, remote_ids, local_ids):
    """How far a tracked remote sits from its local ref, in the pieces
    jj labels it in.

    This is jj's `format_tracked_remote_ref_distances`. Only the count
    carries a label; the words around it are plain.
    """
    parts = _tracking_counts(repo, remote_ids, local_ids)
    if not parts:
        return []
    out = [(" (", "")]
    for index, (word, count, exact) in enumerate(parts):
        if index:
            out.append((", ", ""))
        out.append((f"{word} by " if exact else f"{word} by at least ", ""))
        out.append((str(count),
                    f"tracking_{word}_count "
                    + ("exact" if exact else "lower")))
        out.append((" commits", ""))
    out.append((")", ""))
    return out


def _tracking_counts(repo, remote_ids, local_ids):
    """How far a tracked remote ref sits from the local ref, jj's way.

    Ahead counts the commits the remote ref reaches and the local one
    does not. Behind counts the other way. jj drops a zero count, and
    never singularizes "commits".

    A count is a size hint: exact when its bounds meet, and a lower
    bound otherwise, which jj words as "at least N". Returns
    `(word, count, exact)` for each non-zero direction.
    """
    if not local_ids:
        # The local ref is gone, so there is nothing to measure against.
        return []
    out = []
    for word, wanted, unwanted in (
        ("ahead", remote_ids, local_ids),
        ("behind", local_ids, remote_ids),
    ):
        lower, upper = repo.walk_revs_count(wanted, unwanted)
        if upper == 0:
            continue
        out.append((word, lower, upper == lower))
    return out


def _formatter(settings=None) -> Formatter:
    """This command's stdout, with jj's label stack over it."""
    return Formatter(sys.stdout, use_color(settings))


def _print_ref(repo, settings, ref, template=None, tracked=(), *,
               kind: str = "bookmark", fmt=None) -> None:
    """One listing item: a ref, then the remote refs that follow it.

    jj renders bookmarks and tags from the same `format_commit_ref`, so
    this serves both listings; `kind` is which, and it is a label as
    well as a word. A plain ref is `name: <commit summary>`. A deleted
    one is `name (deleted)`, with no colon. A conflicted one heads a
    block, then lists the commits it moved away from with `-` and the
    ones it moved to with `+`. A remote ref that no local ref follows
    heads its own item, named `name@remote`.

    Each tracked remote ref follows its local ref, indented, named by
    the remote alone, and carrying how far it sits from that local ref.
    A tracked remote that the local ref has not reached yet reads
    `(not created yet)` rather than `(deleted)`.

    The summaries carry no ref names of their own: jj passes an empty
    ref list, since the name is already the line's subject.
    """
    own = fmt is None
    if own:
        fmt = Formatter(sys.stdout, False)
    fmt.push(f"{kind}_list")

    def spans(pieces) -> None:
        for text, labels in pieces:
            fmt.write(text, *labels.split())

    def summary(commit_id, under: str) -> None:
        commit = repo.get_commit(commit_id)
        with fmt.labeled(*under.split()):
            spans(_commit_summary_spans(repo, settings, commit, []))

    def line(commit_id, head=None, prefix: str = "",
             under: str = "normal_target") -> None:
        if template is not None:
            commit = repo.get_commit(commit_id)
            context = _commit_context(repo, settings, commit, [])
            context["name"] = ref.name
            fmt.write(prefix + template.render(context) + "\n")
            return
        if head is not None:
            head()
            fmt.write(": ")
        else:
            fmt.write(prefix, *under.split())
        summary(commit_id, under)
        fmt.write("\n")

    def targets(item, head, absent: str = " (deleted)") -> None:
        if getattr(item, "has_conflict", False):
            head()
            fmt.write(" ")
            fmt.write("(conflicted)", "conflict")
            fmt.write(":\n")
            for commit_id in item.removed_ids:
                line(commit_id, prefix="  - ", under="removed_targets map join")
            for commit_id in item.target_ids:
                line(commit_id, prefix="  + ", under="added_targets map join")
        elif item.target_ids:
            line(item.target_ids[0], head=head)
        else:
            head()
            fmt.write(absent)
            fmt.write("\n")

    remote = getattr(ref, "remote", None)
    if remote is None:
        name = [(ref.name, f"{kind} name")]
    else:
        name = [(ref.name, kind), ("@", kind), (remote, f"{kind} remote")]
    targets(ref, lambda: spans(name))

    for remote_ref, local_ids in tracked:
        head = [("  ", ""), ("@", kind), (remote_ref.remote, f"{kind} remote")]
        head += _tracking_distance_spans(repo, remote_ref.target_ids, local_ids)
        targets(remote_ref, lambda head=head: spans(head),
                absent=" (not created yet)")
    fmt.pop()
    if own:
        fmt.close()


def _write_lines(fmt, lines, base: str = "") -> None:
    """Each line's spans, then the newline jj writes under no labels.

    jj ends a line in two steps: back to the row's own labels, then the
    newline under none at all. `render_block` does the same for a
    buffered row; this is the streaming form.
    """
    under = base.split()
    for line in lines:
        for text, labels in line:
            fmt.write(text, *under, *labels.split())
        fmt.sync(*under)
        fmt.write("\n")


def _conflict_spans(commit, to_ui_path):
    """The paths jj lists under its unresolved-conflicts warning.

    Each reads `<path> <n>-sided conflict`, and names anything in the
    conflict that is not a plain file, because those are what stop `jj
    resolve` and a diff from working. Those parts are `difficult` and
    print red. Deletions are counted but stay `normal`: they interfere
    with neither.

    The path column is padded to the longest path, capped at 32, plus
    three -- jj's width, so a long path does not push every other line
    across the terminal -- and then a separator space, which jj writes
    after the padding rather than as part of it.
    """
    entries = commit.conflicted_paths()
    if not entries:
        return []
    paths = [to_ui_path(path) for path, _, _, _ in entries]
    width = min(max(len(p) for p in paths), 32) + 3
    lines = []
    for path, (_, sides, adds, objects) in zip(paths, entries):
        # The path stays plain; everything after it is the description.
        described = "conflict_description"
        parts = [(name, f"{described} difficult") for name in objects]
        deletions = sides - adds
        if deletions:
            # Sorted with the objects, and a leading digit sorts first.
            parts.insert(0, (f"{deletions} deletion"
                             f"{'' if deletions == 1 else 's'}",
                             f"{described} normal"))
        spans = [(f"{path:<{width}} ", ""),
                 (f"{sides}-sided",
                  f"{described} difficult" if sides > 2
                  else f"{described} normal"),
                 (" conflict", described)]
        if parts:
            spans.append((" including ", described))
            for index, (text, label) in enumerate(parts):
                if index:
                    spans.append((", " if index < len(parts) - 1
                                  else " and ", described))
                spans.append((text, label))
        lines.append(spans)
    return lines


def _conflict_lines(commit, to_ui_path) -> list[str]:
    """`_conflict_spans` as plain text."""
    return ["".join(text for text, _labels in line)
            for line in _conflict_spans(commit, to_ui_path)]


def _commit_context(repo, settings, commit, bookmarks=None) -> dict:
    """The variables a listing's Jinja template can use for one commit.

    Every listing offers the same names, so a template written for one
    reads the same in another. Short ids carry jj's shortest-unique
    prefix with an eight-character floor, and the change id is jj's
    reverse-hex spelling -- the one a reader can paste back.
    """
    if bookmarks is None:
        bookmarks = _bookmarks_by_commit(repo).get(commit.id.hex(), [])
    description = commit.description.splitlines()[0] if commit.description else ""
    return {
        "commit": commit,
        "change_id": commit.change_id.reverse_hex(),
        "change_id_short": _short_id(
            commit.change_id.reverse_hex(),
            repo.shortest_change_id_prefix_len(commit.change_id, settings),
        ),
        "commit_id": commit.id.hex(),
        "commit_id_short": _short_id(
            commit.id.hex(),
            repo.shortest_commit_id_prefix_len(commit.id, settings),
        ),
        "author": commit.author.name or commit.author.email or "",
        "author_name": commit.author.name or "",
        "author_email": commit.author.email or "",
        "committer_name": commit.committer.name or "",
        "committer_email": commit.committer.email or "",
        "datetime": _format_timestamp(commit.committer.timestamp),
        "description": description or "(no description set)",
        "description_full": commit.description.strip() or "(no description set)",
        "bookmarks": bookmarks,
        "bookmarks_str": " ".join(bookmarks),
        "empty": _is_empty(repo, commit),
        "conflict": commit.has_conflict,
        "summary": _commit_summary(repo, settings, commit, bookmarks),
    }


def _compile_template(template_str: str):
    """Compiles one Jinja template the way pyjj-cli's listings expect.

    Sandboxed on purpose: a context binds live `Commit` objects, so
    plain attribute traversal would reach further than a template needs.
    `StrictUndefined` turns a misspelled variable into an error rather
    than a silently blank column.
    """
    from jinja2 import StrictUndefined
    from jinja2.sandbox import SandboxedEnvironment

    env = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)
    env.filters["short"] = lambda value, n=8: value[:n] if isinstance(value, str) else value
    return env.from_string(template_str)


def _resolve_template(settings, ws, args, name: str, builtins=None):
    """The template a listing should render, or `None` for its default.

    jj drives each listing from a named entry under `[templates]`, and
    pyjj-cli uses Jinja for the same job, under `pyjj.templates.<name>`.
    A `-T` argument may be

    - one of jj's builtin template names, mapped to a Jinja equivalent
      by the caller's `builtins`,
    - a bare word, which names `pyjj.templates.<that word>`,
    - or a raw Jinja template.

    With no `-T`, the configured `pyjj.templates.<name>` applies if it
    is set, so a user can change a listing's shape once rather than on
    every command line.
    """
    template_str = getattr(args, "template", None)
    if not template_str:
        template_str = _pyjj_template(settings, name, cwd=ws.workspace_root)
    elif builtins and template_str in builtins:
        template_str = builtins[template_str]
    elif "{{" not in template_str and " " not in template_str and "\n" not in template_str:
        from_config = _pyjj_template(settings, template_str, cwd=ws.workspace_root)
        if from_config:
            template_str = from_config
    if not template_str:
        return None
    return _compile_template(template_str)


def _resolve_operation(repo, name: str | None):
    """Resolve an operation the way `jj` names them on the command line.

    `@` means the operation the repo is loaded at, and `None` means `@`
    too, so a command can pass an absent argument straight through.
    Anything else is a hex id, which is what the binding takes.

    A trailing run of `-` or `+` walks the operation log: `@-` is the
    operation before this one, `@--` the one before that, and `+` walks
    the other way. A step that has no one operation to land on is an
    error, since the name has to mean exactly one.
    """
    if not name:
        return repo.operation
    symbol = name.rstrip("-+")
    steps = name[len(symbol):]
    operation = repo.operation if symbol == "@" else repo.load_operation(symbol)
    children = None
    for index, step in enumerate(steps):
        if step == "-":
            neighbours = operation.parents()
        else:
            if children is None:
                # A child is only findable by walking the log: an
                # operation records its parents, not the other way
                # round.
                children = {}
                for other in repo.operation_log():
                    for parent in other.parent_ids:
                        children.setdefault(parent, []).append(other)
            neighbours = children.get(operation.id, [])
        if len(neighbours) != 1:
            reached = name[:len(symbol) + index + 1]
            raise CommandError(
                f"The operation {reached!r} resolves to "
                f"{'no' if not neighbours else 'more than one'} operation"
            )
        operation = neighbours[0]
    return operation


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


# jj labels a summary row by its status, and colours it from that.
_SUMMARY_STATUS_LABELS = {
    "added": "added",
    "removed": "removed",
    "modified": "modified",
    "executable": "modified",
    "copied": "copied",
    "renamed": "renamed",
}


def _summary_spans(entries, to_ui_path=None):
    """`jj diff --summary`'s lines: one status letter, a space, the path.

    jj has no separate letter for a mode-only change, so an
    `"executable"` entry reads as modified, which is what jj prints for
    it -- and colours it as.
    """
    to_ui_path = to_ui_path or (lambda path: path)
    return [[(f"{_SUMMARY_STATUS_CHARS[e.status]} {to_ui_path(e.path)}",
              _SUMMARY_STATUS_LABELS[e.status])] for e in entries]


def _summary_lines(entries, to_ui_path=None) -> list[str]:
    """`_summary_spans` as plain text."""
    return ["".join(text for text, _labels in line)
            for line in _summary_spans(entries, to_ui_path)]


def _print_summary(entries, to_ui_path=None, settings=None) -> None:
    """The summary listing, coloured the way jj colours it."""
    lines = _summary_spans(entries, to_ui_path)
    if lines:
        print(render_block(lines, "diff summary", use_color(settings)))


def _types_spans(entries, to_ui_path=None):
    """`jj diff --types`: what each path is before and after.

    Two characters, one a side, then the path. jj answers "what is it"
    here, not "what happened to it", so a symlink that became a regular
    file reads `LF` where the summary reads `M`. Every row carries the
    same `modified` label whatever the two characters say.
    """
    to_ui_path = to_ui_path or (lambda path: path)
    return [[(f"{e.before_type}{e.after_type} {to_ui_path(e.path)}",
              "modified")] for e in entries]


def _print_types(entries, to_ui_path=None, settings=None) -> None:
    """The types listing, coloured the way jj colours it."""
    lines = _types_spans(entries, to_ui_path)
    if lines:
        print(render_block(lines, "diff types", use_color(settings)))


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


def _short_id_spans(hex_str: str, shortest_len: int, kind: str):
    """The same id, split where jj colours it.

    jj labels the unique prefix and the rest apart, so the prefix a
    reader can type stands out from the padding that only makes the
    column eight wide. `kind` is `change_id` or `commit_id`.
    """
    shown = _short_id(hex_str, shortest_len)
    cut = min(shortest_len if shortest_len > 0 else len(shown), len(shown))
    spans = [(shown[:cut], f"{kind} shortest prefix")]
    if shown[cut:]:
        spans.append((shown[cut:], f"{kind} shortest rest"))
    return spans


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


# The units jj's relative times step through, largest first. The month
# and year sizes are the average ones the `timeago` crate uses, so a
# span of "1 month" means the same number of days it does there.
_TIME_UNITS = (
    ("year", 31_556_952_000),
    ("month", 2_629_746_000),
    ("week", 604_800_000),
    ("day", 86_400_000),
    ("hour", 3_600_000),
    ("minute", 60_000),
    ("second", 1_000),
    ("millisecond", 1),
)


def _relative(millis: int, units, suffix: str, floor: str) -> str:
    """The largest single unit that fits, or `floor` if none does."""
    for name, size in units:
        if millis >= size:
            count = millis // size
            return f"{count} {name}{'' if count == 1 else 's'}{suffix}"
    return floor


def _ago(millis_since_epoch: int) -> str:
    """How long ago a timestamp was, the way `jj`'s `.ago()` says it.

    jj stops at whole seconds here, so anything more recent reads as
    "now" rather than as a count of milliseconds.
    """
    import time

    return _relative(int(time.time() * 1000) - millis_since_epoch,
                     _TIME_UNITS[:-1], " ago", "now")


def _duration(start_millis: int, end_millis: int) -> str:
    """How long an operation lasted, the way jj's `.duration()` says it.

    jj measures down to microseconds here, so a span this short reports
    itself as such rather than as zero. Timestamps carry milliseconds,
    so any operation that starts and ends within one takes this floor.
    """
    return _relative(end_millis - start_millis, _TIME_UNITS, "",
                     "less than a microsecond")


def _format_timestamp(timestamp, century: bool = True) -> str:
    """jj's `format_timestamp`: the local time, to the second.

    `century=False` is the shorter spelling pyjj-cli's listings use --
    two-digit year, no seconds -- which `log` prints by choice rather
    than to match jj.
    """
    moment = datetime.fromtimestamp(
        timestamp.millis_since_epoch / 1000, timezone.utc
    )
    zone = timezone(timedelta(minutes=_local_tz_offset_minutes()))
    local = moment.astimezone(zone)
    if century:
        return local.strftime("%Y-%m-%d %H:%M:%S")
    return local.strftime("%y-%m-%d %H:%M")


def _detailed_signature(signature) -> str:
    """jj's `format_detailed_signature`: name, angle-bracketed email and
    the timestamp in parentheses, with a placeholder for either half
    that is missing."""
    name = signature.name or "(no name set)"
    email = signature.email or "(no email set)"
    return f"{name} <{email}> ({_format_timestamp(signature.timestamp)})"


def _signature_spans(signature, kind: str):
    """jj's `format_detailed_signature`, in labelled pieces.

    The name, the email in angle brackets and the timestamp in
    parentheses. The brackets and parentheses are not part of any field,
    so only the field itself takes a colour. `kind` is `author` or
    `committer`.
    """
    email = signature.email or ""
    local, _, domain = email.partition("@")
    # A signature with no name reads as a placeholder, and jj labels it
    # one -- the same label its missing email carries, and so the same
    # colour. Only the root commit has neither.
    name = ((signature.name, f"{kind} name") if signature.name
            else ("(no name set)", f"{kind} name placeholder"))
    spans = [name, (" <", "")]
    if email:
        spans.append((local, f"{kind} email local"))
        if domain:
            spans.append(("@", f"{kind} email"))
            spans.append((domain, f"{kind} email domain"))
    else:
        spans.append(("(no email set)", f"{kind} email placeholder"))
    spans.append(("> (", ""))
    spans.append((_format_timestamp(signature.timestamp),
                  f"{kind} timestamp local format"))
    spans.append((")", ""))
    return spans


def _indent(text: str, prefix: str = "    ") -> str:
    """jj's `indent`: every non-empty line gets the prefix.

    A blank line stays blank rather than becoming four spaces, so a
    description with a paragraph break has no trailing whitespace in it.
    """
    return "\n".join(prefix + line if line else line for line in text.split("\n"))


def _immutable_ids(repo, settings, commits) -> set[str]:
    """Which of `commits` jj refuses to rewrite.

    jj asks this once per row, to decide whether the row reads
    `immutable` or `mutable` -- which is a colour, and a graph glyph.
    Evaluating `immutable()` on its own would walk the whole of trunk,
    so the question is narrowed to the rows on screen first.

    A hidden commit is never in the set, and naming one in a revset is
    not always allowed, so those are dropped before asking.
    """
    ids = [commit.id.hex() for commit in commits
           if not commit.is_hidden(repo)]
    if not ids:
        return set()
    expression = "immutable() & (" + "|".join(ids) + ")"
    try:
        return {commit.id.hex()
                for commit in repo.revset(settings, expression)}
    except (pyjj.JjError, CommandError):
        return set()


def _commit_kind(repo, commit, wc_ids=(), immutable_ids=()) -> str:
    """jj's outer label on a log row: what kind of commit this is.

    `builtin_log_compact` wraps a whole row in these, and the palette
    reads them -- a working copy is bold, an immutable commit is cyan,
    and the same field under each takes a different colour.
    """
    parts = []
    if commit.id.hex() in wc_ids:
        parts.append("working_copy")
    parts.append("immutable" if commit.id.hex() in immutable_ids
                 else "mutable")
    if commit.has_conflict:
        parts.append("conflicted")
    return " ".join(parts)


def _commit_glyph(kind: str) -> str:
    """jj's `builtin_log_node`: the glyph says what kind of commit it is.

    It reads the same labels `_commit_kind` builds, so the drawing and
    the colours never disagree.
    """
    for name, glyph in (("working_copy", "@"), ("immutable", "◆"),
                        ("conflicted", "×")):
        if name in kind.split():
            return glyph
    return "○"


def _commit_header_spans(repo, settings, commit, *, kw: str = "",
                         bookmarks=(), tags=(), working_copies=(),
                         author=None, timestamp=None):
    """jj's `format_short_commit_header`: the first line of a log row.

    The change id with its offset, the author's email, the committer's
    timestamp, any names on the commit, the commit id, and the markers
    that say the commit is hidden, divergent or conflicted.

    `kw` is the keyword the template reached the commit through. jj
    labels a keyword access with its own name, so `evolog` -- where the
    commit is the entry's `commit` field -- carries one more label than
    `log`, where the commit is the row itself. `author` replaces the
    email with a plain string, and `timestamp` replaces the full
    stamp, which is what pyjj-cli's own default prints.
    """
    def under(*names) -> str:
        return " ".join(part for part in (kw, *names) if part)

    hidden = commit.is_hidden(repo)
    divergent = not hidden and commit.is_divergent(repo)
    marker = "hidden" if hidden else "divergent" if divergent else ""

    change = [(text, f"{marker} {under(labels)}".strip()) for text, labels
              in _short_id_spans(
                  commit.change_id.reverse_hex(),
                  repo.shortest_change_id_prefix_len(commit.change_id,
                                                     settings),
                  "change_id")]
    if marker:
        # The offset is how a reader addresses this version: jj
        # resolves `<change id>/2` as a revset. Only a hidden or
        # divergent version carries one, since the bare change id names
        # the visible one.
        offset = commit.change_offset(repo)
        if offset is not None:
            change.append(("/", f"{marker} change_offset"))
            change.append((str(offset), f"{marker} {under('change_offset')}"))

    if author is not None:
        who = [(author, under("author"))]
    else:
        local, _, domain = (commit.author.email or "").partition("@")
        who = [(local, under("author", "email", "local"))]
        if domain:
            who.append(("@", under("author", "email")))
            who.append((domain, under("author", "email", "domain")))

    names = [[(name, under(kind, "name"))]
             for kind, group in (("bookmarks", bookmarks), ("tags", tags),
                                 ("working_copies", working_copies))
             for name in group]

    labels = []
    # jj's order: whichever of hidden/divergent applies, then conflict.
    if marker:
        labels.append([(f"({marker})", marker)])
    if commit.has_conflict:
        labels.append([("(conflict)", "conflict")])

    return separate([
        change,
        who,
        [(timestamp if timestamp is not None
          else _format_timestamp(commit.committer.timestamp),
          under("committer", "timestamp", "local", "format"))],
        *names,
        [(text, under(labels)) for text, labels in _short_id_spans(
            commit.id.hex(),
            repo.shortest_commit_id_prefix_len(commit.id, settings),
            "commit_id")],
        *labels,
    ])


def _commit_root_spans(repo, settings, commit, *, kw: str = ""):
    """jj's `format_root_commit`: the row the root commit gets.

    It has no author and no timestamp worth printing -- the epoch reads
    as a 1970 commit that nobody made -- so `root()` stands where they
    would go. The whole row is `immutable`, whatever the immutable
    revset says.
    """
    def under(*names) -> str:
        return " ".join(part for part in (kw, *names) if part)

    return separate([
        [(text, under(labels)) for text, labels in _short_id_spans(
            commit.change_id.reverse_hex(),
            repo.shortest_change_id_prefix_len(commit.change_id, settings),
            "change_id")],
        [("root()", "root")],
        [(text, under(labels)) for text, labels in _short_id_spans(
            commit.id.hex(),
            repo.shortest_commit_id_prefix_len(commit.id, settings),
            "commit_id")],
    ])


def _commit_body_spans(repo, settings, commit, *, kw: str = ""):
    """jj's second line of `builtin_log_compact`: empty, then the text."""
    empty = _is_empty(repo, commit)
    parts = [[("(empty)", "empty")]] if empty else []
    first_line = commit.description.splitlines()[0] if commit.description else ""
    if first_line:
        parts.append([(first_line,
                       " ".join(part for part in
                                (kw, "description", "first_line") if part))])
    else:
        parts.append([("(no description set)",
                       "empty description placeholder" if empty
                       else "description placeholder")])
    return separate(parts)


def _commit_summary_spans(repo, settings, commit, bookmarks=None):
    """One commit as jj's `commit_summary` template renders it, in the
    labelled pieces jj colours it in.

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

    A hidden or divergent commit carries a marker, and its change id
    carries the offset that addresses it -- `yqymtrmq/1` resolves as a
    revset where the bare change id would be ambiguous or resolve to
    something else. jj prints the offset only for those two, because
    only then does the change id alone fail to name the commit.

    Returns `(text, labels)` pairs. The caller supplies the labels
    around these -- `commit`, and `working_copy` where it applies -- so
    the same pieces colour differently in different places, which is
    what jj's stacks do.
    """
    if bookmarks is None:
        bookmarks = _bookmarks_by_commit(repo).get(commit.id.hex(), [])
    hidden = commit.is_hidden(repo)
    divergent = not hidden and commit.is_divergent(repo)
    marker = "hidden" if hidden else "divergent" if divergent else ""

    spans = []
    for text, labels in _short_id_spans(
        commit.change_id.reverse_hex(),
        repo.shortest_change_id_prefix_len(commit.change_id, settings),
        "change_id",
    ):
        spans.append((text, f"{marker} {labels}".strip()))
    if marker:
        offset = commit.change_offset(repo)
        if offset is not None:
            spans.append((f"/{offset}", f"{marker} change_offset"))
    spans.append((" ", ""))
    spans.extend(_short_id_spans(
        commit.id.hex(),
        repo.shortest_commit_id_prefix_len(commit.id, settings),
        "commit_id",
    ))
    spans.append((" ", ""))

    if bookmarks:
        for index, name in enumerate(bookmarks):
            if index:
                spans.append((" ", ""))
            spans.append((name, "bookmarks name"))
        spans.append((" | ", "separator"))

    rest = []
    # jj's order: whichever of hidden/divergent applies, then conflict.
    if marker:
        rest.append((f"({marker})", marker))
    if commit.has_conflict:
        rest.append(("(conflict)", "conflict"))
    empty = _is_empty(repo, commit)
    if empty:
        rest.append(("(empty)", "empty"))
    first_line = commit.description.splitlines()[0] if commit.description else ""
    if first_line:
        rest.append((first_line, "description first_line"))
    else:
        rest.append(("(no description set)",
                     "empty description placeholder" if empty
                     else "description placeholder"))
    for index, (text, labels) in enumerate(rest):
        if index:
            spans.append((" ", ""))
        spans.append((text, labels))
    return spans


def _commit_summary(repo, settings, commit, bookmarks=None) -> str:
    """`_commit_summary_spans` as plain text."""
    return "".join(
        text for text, _ in
        _commit_summary_spans(repo, settings, commit, bookmarks)
    )


def _git_diff_lines(files, context: int = 3, compare: str = "exact"):
    """`jj diff --git`'s output for a list of `Commit.git_diff()` files.

    The layout follows jj's `show_git_diff`. Two details differ from what
    `git diff` prints, and both are jj's: the `@@` header always carries
    both counts, even a count of one, and the abbreviated hashes are ten
    characters wide.

    File content is bytes, and may not be text at all, so the spans
    carry it decoded with `surrogateescape`.
    """
    lines = []

    def line(text: str) -> None:
        lines.append([(text, "file_header")])

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
            lines.append([(f"Binary files {left_name} and {right_name} differ",
                           "")])
            continue
        line(f"--- {left_name}")
        line(f"+++ {right_name}")
        lines.extend(_unified_hunk_lines(f.before_content, f.after_content,
                                         context, compare))
    return lines


def _git_diff_bytes(files, context: int = 3, coloured: bool = False,
                    compare: str = "exact") -> bytes:
    """`_git_diff_lines` as bytes, ready to write to stdout."""
    return _render_diff(_git_diff_lines(files, context, compare), coloured)


def _unified_hunk_lines(before: bytes, after: bytes, context: int = 3,
                        compare: str = "exact"):
    """The `@@` headers and their lines, as labelled spans.

    jj prints these for a file and, in `--git` format, for a commit
    description as well, under a dummy path.

    A changed line carries its word diff: jj marks only the words that
    moved, and underlines those. The line's trailing newline is not part
    of any token -- jj writes it outside every label -- so the last
    token can land empty, and the escape sequence that closes the
    underline is written all the same.
    """
    lines = []
    for hunk in pyjj.unified_hunks(before, after, context, compare):
        lines.append([(f"@@ -{hunk.left_start},{hunk.left_len} "
                       f"+{hunk.right_start},{hunk.right_len} @@",
                       "hunk_header")])
        for kind, tokens in hunk.lines:
            content = b"".join(token for _token_kind, token in tokens)
            tokens = list(tokens)
            if content.endswith(b"\n"):
                last_kind, last = tokens[-1]
                tokens[-1] = (last_kind, last[:-1])
            spans = [(_DIFF_SIGILS[kind], kind)]
            spans += [(token.decode("utf-8", "surrogateescape"),
                       f"{kind} token" if token_kind == "different" else kind)
                      for token_kind, token in tokens]
            lines.append(spans)
            if not content.endswith(b"\n"):
                lines.append([("\\ No newline at end of file", "")])
    return lines


def _unified_hunk_bytes(before: bytes, after: bytes, context: int = 3,
                        compare: str = "exact") -> bytes:
    """`_unified_hunk_lines` as plain bytes."""
    return _render_diff(_unified_hunk_lines(before, after, context, compare),
                        False)


def _render_diff(lines, coloured: bool, base: str = "diff git") -> bytes:
    """A diff's lines as bytes, coloured or not.

    File content is bytes and may not be text at all, so the spans carry
    it decoded with `surrogateescape` and this puts it back.

    The description diff is `diff` alone rather than `diff git`: jj
    renders it outside the format's own label, so its file header is
    bold but nothing else about it says `git`.
    """
    if not lines:
        return b""
    rendered = render_block(lines, base, coloured)
    return rendered.encode("utf-8", "surrogateescape") + b"\n"


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

def _color_words_header(f, to_ui_path) -> str:
    """The line jj writes above a file's color-words diff.

    jj names the file by what it is on each side, so a mode change reads
    as a sentence rather than a diff -- `Non-executable file became
    executable at b.txt:`.

    A conflict is one of those names. The content arrives materialized,
    so the mode says `regular file` on both sides and only the recorded
    conflict flags can tell that the change created, resolved or moved a
    conflict.
    """
    def kind(mode, conflict) -> str:
        return "conflict" if conflict else _FILE_TYPES[mode]

    path = to_ui_path(f.path)
    if f.before_mode is None:
        return f"Added {kind(f.after_mode, f.after_conflict)} {path}:"
    if f.after_mode is None:
        return f"Removed {kind(f.before_mode, f.before_conflict)} {path}:"
    before, after = f.before_mode, f.after_mode
    if f.before_conflict and f.after_conflict:
        description = "Modified conflict in"
    elif f.before_conflict:
        description = "Resolved conflict in"
    elif f.after_conflict:
        description = "Created conflict in"
    elif before == after == "100755":
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


def _split_inclusive(data: bytes) -> list[bytes]:
    """Rust's `split_inclusive(b'\\n')`: each line keeps its newline."""
    if not data:
        return []
    lines = data.split(b"\n")
    tail = lines.pop()
    out = [line + b"\n" for line in lines]
    if tail:
        out.append(tail)
    return out


# jj's `diff.color-words.max-inline-alternation`, at its default. A row
# that changes side more often than this is harder to read than two
# rows, so jj splits it instead of inlining it.
_MAX_INLINE_ALTERNATION = 3

# The label a row's left and right side carry.
_COLOR_WORDS_SIDES = {"left": "removed", "right": "added"}


def _split_by_matching_newline(hunks):
    """Groups of hunks that belong to one run of changed lines.

    jj's `split_diff_hunks_by_matching_newline`: a matching hunk that
    holds a newline ends the group it is in.
    """
    group = []
    for kind, lhs, rhs in hunks:
        group.append((kind, lhs, rhs))
        if kind == "matching" and b"\n" in lhs and b"\n" in rhs:
            yield group
            group = []
    if group:
        yield group


def _count_alternation(group) -> int:
    """How often a group of hunks changes side, matching hunks aside.

    jj's measure of how busy a row would look: `[left]` counts 1,
    `[left, matching, left]` still counts 1, and `[left, right,
    matching, right, left]` counts 3.
    """
    count = 0
    previous = None
    for kind, lhs, rhs in group:
        if kind != "different":
            continue
        for index, content in enumerate((lhs, rhs)):
            if not content or index == previous:
                continue
            count += 1
            previous = index
    return count


def _can_inline(hunks) -> bool:
    """Whether a changed region fits one row per line."""
    return max((_count_alternation(group)
                for group in _split_by_matching_newline(hunks)),
               default=0) <= _MAX_INLINE_ALTERNATION


def _diff_line_rows(hunks, left: int, right: int):
    """jj_lib's `DiffLineIterator`: word-diff hunks grouped into rows.

    A row is `(left, right, parts)`, and each part is `(side, text)`
    with side `both`, `left` or `right`. A row can hold text from both
    sides, which is what puts a replaced word beside the word it
    replaced.

    Returns the rows and the numbers the next region starts from.
    """
    rows = []
    current: list[tuple[str, bytes]] = []
    for kind, lhs, rhs in hunks:
        # jj's iterator refills only when its queue is empty, so the
        # blank-line check below sees this hunk's own rows and no others.
        queue: list[tuple[int, int, list]] = []
        if kind == "matching":
            for token in _split_inclusive(lhs):
                current.append(("both", token))
                if token.endswith(b"\n"):
                    queue.append((left, right, current))
                    current = []
                    left += 1
                    right += 1
        else:
            for token in _split_inclusive(lhs):
                current.append(("left", token))
                if token.endswith(b"\n"):
                    queue.append((left, right, current))
                    current = []
                    left += 1
            rights = _split_inclusive(rhs)
            # A right side that opens with a newline would add a blank
            # row under a row that already carries right-hand text. jj
            # drops the blank row and only counts the line.
            if (rhs.startswith(b"\n") and not current and queue
                    and any(side != "left" for side, _ in queue[0][2])):
                rights = rights[1:]
                right += 1
            for token in rights:
                current.append(("right", token))
                if token.endswith(b"\n"):
                    queue.append((left, right, current))
                    current = []
                    right += 1
        rows.extend(queue)
    if current:
        rows.append((left, right, current))
    return rows, left, right


def _unzip_word_hunks(hunks):
    """jj_lib's `unzip_diff_hunks_to_lines`: one token list per line.

    This is what a row looks like when the two sides cannot share it.
    """
    lines: list[list] = [[], []]
    pending: list[list] = [[], []]

    def push(index: int, kind: str, data: bytes) -> None:
        for token in _split_inclusive(data):
            pending[index].append((kind, token))
            if token.endswith(b"\n"):
                lines[index].append(pending[index])
                pending[index] = []

    for kind, lhs, rhs in hunks:
        token_kind = "matching" if kind == "matching" else "different"
        push(0, token_kind, lhs)
        push(1, token_kind, rhs)
    for index in (0, 1):
        if pending[index]:
            lines[index].append(pending[index])
    return lines[0], lines[1]


def _color_words_number_spans(left, right):
    """The `   1    1: ` gutter. A missing number leaves its column blank."""
    spans = []
    if left is None:
        spans.append(("     ", ""))
    else:
        spans.append((f"{left:>4}", "removed line_number"))
        spans.append((" ", ""))
    if right is None:
        spans.append(("    : ", ""))
    else:
        spans.append((f"{right:>4}", "added line_number"))
        spans.append((": ", ""))
    return spans


def _strip_newline(parts):
    """Drops the row's trailing newline; `render_block` writes it back.

    jj writes a newline outside every label, so the escape that closes
    the last span comes before it. The last part can land empty, and its
    escape sequence is written all the same.
    """
    parts = list(parts)
    head, data = parts[-1]
    if data.endswith(b"\n"):
        parts[-1] = (head, data[:-1])
    return parts


def _color_words_content_spans(parts):
    """One row's text, which may come from both sides at once."""
    spans = []
    for side, data in _strip_newline(parts):
        labels = _COLOR_WORDS_SIDES.get(side)
        spans.append((data.decode("utf-8", "surrogateescape"),
                      f"{labels} token" if labels else ""))
    return spans


def _color_words_token_spans(tokens, side: str):
    """One single-sided row. Only the words that moved carry `token`."""
    return [(data.decode("utf-8", "surrogateescape"),
             f"{side} token" if kind == "different" else side)
            for kind, data in _strip_newline(tokens)]


def _changed_rows(rows, before: bytes, after: bytes, numbers, coloured) -> None:
    """Rows for one changed region, word-diffed.

    An inline row tells the two sides apart by colour alone, so a plain
    rendering always splits it into a removed row and an added row. That
    is why the coloured and the plain output are not the same shape.
    """
    hunks = pyjj.content_hunks(before, after, "word")
    if coloured and _can_inline(hunks):
        grouped, left, right = _diff_line_rows(hunks, numbers[0], numbers[1])
        for row_left, row_right, parts in grouped:
            has_left = any(side != "right" for side, _ in parts)
            has_right = any(side != "left" for side, _ in parts)
            rows.append(
                _color_words_number_spans(row_left if has_left else None,
                                          row_right if has_right else None)
                + _color_words_content_spans(parts))
        numbers[0], numbers[1] = left, right
        return
    left_lines, right_lines = _unzip_word_hunks(hunks)
    for tokens in left_lines:
        rows.append(_color_words_number_spans(numbers[0], None)
                    + _color_words_token_spans(tokens, "removed"))
        numbers[0] += 1
    for tokens in right_lines:
        rows.append(_color_words_number_spans(None, numbers[1])
                    + _color_words_token_spans(tokens, "added"))
        numbers[1] += 1


def _unchanged_rows(rows, left_lines, right_lines, numbers, coloured) -> None:
    """Rows for lines both sides share, under the `context` label."""
    if left_lines != right_lines:
        # Only `-w` or `-b` reaches this: the line diff called the
        # lines the same and they still differ to the eye. jj
        # word-diffs them and keeps the `context` label on the rows,
        # so they stay dim however they are told apart.
        changed: list = []
        _changed_rows(changed, b"".join(left_lines), b"".join(right_lines),
                      numbers, coloured)
        rows.extend(Line(spans, "context") for spans in changed)
        return
    for line in left_lines:
        rows.append(Line(_color_words_number_spans(numbers[0], numbers[1])
                         + _color_words_content_spans([("both", line)]),
                         "context"))
        numbers[0] += 1
        numbers[1] += 1


def _context_rows(rows, pending, numbers, num_after, num_before,
                  coloured) -> None:
    """`num_after` unchanged rows, `    ...`, then `num_before` more."""
    if pending is None:
        return

    def split(side: bytes):
        lines = _split_inclusive(side)
        head = lines[:num_after]
        rest = lines[num_after:]
        # jj takes one line more than it will show. If nothing is
        # skipped that line belongs to the block; if something is, the
        # ellipsis takes its place, because it costs the same row.
        tail = rest[max(0, len(rest) - num_before - 1):]
        return head, tail, len(rest) - len(tail)

    left_head, left_tail, left_skipped = split(pending[0])
    right_head, right_tail, right_skipped = split(pending[1])
    _unchanged_rows(rows, left_head, right_head, numbers, coloured)
    if left_skipped or right_skipped:
        rows.append([("    ...", "")])
        numbers[0] += left_skipped
        numbers[1] += right_skipped
        if len(left_tail) > num_before:
            left_tail = left_tail[1:]
            numbers[0] += 1
        if len(right_tail) > num_before:
            right_tail = right_tail[1:]
            numbers[1] += 1
    _unchanged_rows(rows, left_tail, right_tail, numbers, coloured)


def _color_words_rows(before: bytes, after: bytes, context: int = 3,
                      coloured: bool = False, compare: str = "exact"):
    """The numbered body of a color-words diff, as labelled rows.

    jj keeps `context` unchanged lines after a change and `context`
    before the next one, and replaces what is left with `    ...`. It
    keeps nothing before the first change and nothing after the last.
    """
    rows: list = []
    numbers = [1, 1]
    pending = None
    emitted = False
    for kind, lhs, rhs in pyjj.content_hunks(before, after, "line", compare):
        if kind == "matching":
            pending = (lhs, rhs)
            continue
        _context_rows(rows, pending, numbers,
                      context if emitted else 0, context, coloured)
        pending = None
        emitted = True
        _changed_rows(rows, lhs, rhs, numbers, coloured)
    _context_rows(rows, pending, numbers,
                  context if emitted else 0, 0, coloured)
    return rows


def _color_words_lines(files, to_ui_path, context: int = 3,
                       coloured: bool = False, compare: str = "exact"):
    """`jj diff`'s default output for a list of `Commit.git_diff()` files.

    A conflicted path reads as a regular file here. jj names it a
    conflict and says whether the change created, resolved or moved it;
    `git_diff()` has already materialized the markers by this point, so
    that distinction is gone. The status scenarios mark the gap.
    """
    rows: list = []
    for f in files:
        rows.append([(_color_words_header(f, to_ui_path), "header")])
        added = f.before_mode is None
        removed = f.after_mode is None
        content = f.after_content if added else f.before_content
        if (added or removed) and not content:
            rows.append([("    (empty)", "empty")])
            continue
        if f.is_binary:
            rows.append([("    (binary)", "binary")])
            continue
        before = b"" if added else f.before_content
        after = b"" if removed else f.after_content
        if before == after:
            continue
        rows.extend(_color_words_rows(before, after, context, coloured,
                                      compare))
    return rows


def _color_words_bytes(files, to_ui_path, context: int = 3,
                       coloured: bool = False, compare: str = "exact") -> bytes:
    """`_color_words_lines` as bytes, ready to write to stdout."""
    return _render_diff(
        _color_words_lines(files, to_ui_path, context, coloured, compare),
        coloured, "diff color_words")


def _print_color_words_diff(from_commit, to_commit, settings, ws, paths=None,
                            context=3, compare="exact") -> None:
    """Writes `jj diff`'s default output to stdout."""
    files = from_commit.git_diff(to_commit, settings, paths)
    sys.stdout.flush()
    sys.stdout.buffer.write(
        _color_words_bytes(files, _ui_path_formatter(ws), context,
                           use_color(settings), compare)
    )
    sys.stdout.buffer.flush()


_DIFF_SIGILS = {"context": " ", "removed": "-", "added": "+"}


def _print_git_diff(from_commit, to_commit, settings, paths=None, context=3,
                    compare="exact") -> None:
    """Writes `jj diff --git`'s output to stdout."""
    files = from_commit.git_diff(to_commit, settings, paths)
    sys.stdout.flush()
    sys.stdout.buffer.write(_git_diff_bytes(files, context,
                                            use_color(settings), compare))
    sys.stdout.buffer.flush()


def _diff_stats_lines(stats):
    """`--stat`'s output, in the shape `jj diff --stat` prints it.

    Each file gets its changed-line count and a `+`/`-` bar; a binary
    file gets its byte delta instead, since it has no lines to count.
    The summary line counts every file, binary ones included.

    The `-` run is written even when it is empty, because jj writes it
    with the line's newline: a file that only gained lines still pays
    for the escape sequence that would have coloured its `-` marks.
    """
    paths = [stat.path for stat in stats]
    width = max((len(path) for path in paths), default=0)
    total_added = 0
    total_removed = 0
    lines = []
    for stat in stats:
        if stat.added is None:
            lines.append([(f"{stat.path:<{width}} | ", ""),
                          ("(binary)", "binary")])
            if stat.bytes_delta:
                side = "removed" if stat.bytes_delta < 0 else "added"
                lines[-1].append((f" {stat.bytes_delta:+}", side))
                lines[-1].append((" bytes", ""))
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
        else:
            bar_added = bar_removed = 0
        gap = " " if bar_added or bar_removed else ""
        line = [(f"{stat.path:<{width}} | {changed}{gap}", "")]
        if bar_added:
            line.append(("+" * bar_added, "added"))
        line.append(("-" * bar_removed, "removed"))
        lines.append(line)
    lines.append([(
        f"{len(stats)} file{'' if len(stats) == 1 else 's'} changed, "
        f"{total_added} insertion{'' if total_added == 1 else 's'}(+), "
        f"{total_removed} deletion{'' if total_removed == 1 else 's'}(-)",
        "stat-summary")])
    return lines


def _print_diff_stats(stats, settings=None) -> None:
    """The histogram, coloured the way jj colours it."""
    print(render_block(_diff_stats_lines(stats), "diff stat",
                       use_color(settings)))


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


# jj gives a commit description a dummy path so a `--git` diff of one
# stays a parsable patch.
_DESCRIPTION_PATH = "JJ-COMMIT-DESCRIPTION"


def _description_diff_bytes(args, before: str, after: str,
                            coloured: bool = False, formats=None) -> bytes:
    """What jj prints when two commits' descriptions differ.

    `jj interdiff` compares descriptions as well as trees. The short
    formats omit the block: jj's reasoning is that a dummy file path
    tells the reader nothing, and a summary line is only a path.
    """
    if before == after:
        return b""
    _short, long = _diff_formats(args) if formats is None else formats
    if long is None or long.startswith(_TOOL_FORMAT):
        # jj hands a tool two directories of files, and a description
        # is not one, so it prints no description block for a tool.
        return b""
    left, right = before.encode(), after.encode()
    compare = _compare_mode(args)
    if long == "git":
        lines = [
            [(f"diff --git a/{_DESCRIPTION_PATH} b/{_DESCRIPTION_PATH}",
              "file_header")],
            [(f"--- {_DESCRIPTION_PATH}", "file_header")],
            [(f"+++ {_DESCRIPTION_PATH}", "file_header")],
        ]
        lines += _unified_hunk_lines(left, right, compare=compare)
        return _render_diff(lines, coloured, "diff")
    lines = [[("Modified commit description:", "header")]]
    lines += _color_words_rows(left, right, coloured=coloured, compare=compare)
    return _render_diff(lines, coloured, "diff")


class _FileStat:
    """The shape `_print_diff_stats` reads, computed from file content.

    `Commit.diff_stats()` needs two commits. An interdiff has only one,
    since its left side is a tree that was never committed.
    """

    @staticmethod
    def _type(mode, conflict) -> str:
        """jj's type character, from what `git_diff()` reports."""
        if mode is None:
            return "-"
        if conflict:
            return "C"
        return {"120000": "L", "040000": "G"}.get(mode, "F")

    def __init__(self, f, compare: str = "exact"):
        self.path = f.path
        self.status = (
            "added" if f.before_mode is None
            else "removed" if f.after_mode is None
            else "modified"
        )
        self.before_type = self._type(f.before_mode, f.before_conflict)
        self.after_type = self._type(f.after_mode, f.after_conflict)
        self.binary = f.is_binary
        self.bytes_delta = len(f.after_content) - len(f.before_content)
        if f.is_binary:
            self.added = self.removed = None
            return
        self.added = self.removed = 0
        for hunk in pyjj.unified_hunks(f.before_content, f.after_content, 0,
                                       compare):
            for kind, _ in hunk.lines:
                if kind == "added":
                    self.added += 1
                elif kind == "removed":
                    self.removed += 1


# jj's short formats, in the order it picks between them. Each is a
# listing: one line a file, and no content.
_SHORT_FORMATS = ("summary", "stat", "types", "name_only")

# What a long format's name reads as when an external program provides
# it. The tool's own name follows.
_TOOL_FORMAT = "tool:"


# The long formats, by the name jj spells them with on the command
# line. A `--tool=:<name>` names one of these or one of the short ones.
_LONG_FORMATS = ("git", "color-words")


def _format_flag(name: str) -> str:
    """A format's name as the flag that asks for it."""
    return "--" + name.replace("_", "-")


def _diff_formats_from_args(args) -> tuple[str | None, str | None]:
    """The formats these flags name, before any default applies.

    jj sorts the flags into a *short* format, which lists the files,
    and a *long* one, which carries their content. It asks for at most
    one of each, so `--stat --git` names both.

    `--tool` names a long format too. A `:` before the name asks for a
    builtin -- `--tool=:git` is `--git` -- and anything else is an
    external program, which jj runs to print the diff. Either way it
    refuses to be combined with a flag naming the same half.
    """
    short = next((name for name in _SHORT_FORMATS
                  if getattr(args, name, False)), None)
    long = ("git" if getattr(args, "git", False)
            else "color_words" if getattr(args, "color_words", False)
            else None)
    tool = getattr(args, "tool", None)
    if not tool:
        return short, long

    def refuse(named: str) -> None:
        raise CommandError(
            f"--tool={tool} cannot be used with {_format_flag(named)}")

    if not tool.startswith(":"):
        if long is not None:
            refuse(long)
        return short, f"{_TOOL_FORMAT}{tool}"
    name = tool[1:].replace("-", "_")
    if name in _SHORT_FORMATS:
        if short is not None:
            refuse(short)
        return name, long
    if name.replace("_", "-") in _LONG_FORMATS:
        if long is not None:
            refuse(long)
        return short, name
    raise CommandError(f"invalid builtin diff format: {tool}")


def _diff_formats(args) -> tuple[str | None, str | None]:
    """The formats `jj diff` prints, in the order it prints them.

    A diff command always prints something, so the long color-words
    format is the default. It applies only when no flag asks for
    anything: the short format alone prints the listing alone.
    """
    short, long = _diff_formats_from_args(args)
    if short is None and long is None:
        return None, "color_words"
    return short, long


def _diff_formats_for_log(args, patch: bool) -> tuple[str | None, str | None]:
    """The formats a log-like command prints, which may be none at all.

    `jj log` prints a row and nothing else unless a flag asks for a
    diff, so both formats can be `None`. `--patch` asks for the default
    long format, and a long flag of its own already covers that.

    jj also skips the default when the short format *is* the configured
    default. pyjj-cli's default is the color-words format, which is
    long, so that case cannot arise here.
    """
    short, long = _diff_formats_from_args(args)
    if patch and long is None:
        long = "color_words"
    return short, long


def _compare_mode(args) -> str:
    """How `-w` and `-b` ask for two lines to be compared.

    This decides which lines a diff calls the same, so it reaches
    every format, the histogram included.
    """
    if getattr(args, "ignore_all_space", False):
        return "ignore-all-space"
    if getattr(args, "ignore_space_change", False):
        return "ignore-space-change"
    return "exact"


def _diff_tool_bytes(settings, tool: str, files) -> bytes:
    """What an external program prints for a diff.

    jj writes the two sides of every changed path into a `left` and a
    `right` directory, runs the tool with its working directory set to
    the pair, and copies its output through unchanged. The two names
    are relative for that reason, so a tool that echoes them prints
    nothing about where the pair happened to live.

    A non-zero exit is not an error: `diff` itself exits 1 whenever the
    two sides differ, which is the whole point of running it.
    """
    args_template = settings.get_string_list(f"merge-tools.{tool}.diff-args")
    if args_template is None:
        # An unconfigured name is the program itself, with jj's own
        # default arguments.
        args_template = ["$left", "$right"]
    elif not args_template:
        raise CommandError(
            f"The tool `{tool}` cannot be used for diff formatting")
    program = settings.get_string(f"merge-tools.{tool}.program") or tool
    with tempfile.TemporaryDirectory(prefix="pyjj-difftool-") as room:
        for side, content in (("left", "before_content"),
                              ("right", "after_content")):
            for entry in files:
                present = (entry.before_mode if side == "left"
                           else entry.after_mode)
                if present is None:
                    continue
                path = Path(room) / side / entry.path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(getattr(entry, content))
            (Path(room) / side).mkdir(parents=True, exist_ok=True)
        argv = [program] + [
            arg.replace("$left", "left").replace("$right", "right")
            for arg in args_template
        ]
        try:
            done = subprocess.run(argv, cwd=room, stdin=subprocess.DEVNULL,
                                  capture_output=True)
        except OSError as e:
            raise CommandError(f"Failed to execute tool `{program}`: {e}")
        sys.stderr.write(done.stderr.decode("utf-8", "replace"))
        return done.stdout


def _diff_files_bytes(args, ws, files, settings=None, formats=None) -> bytes:
    """The same format choice as `_diff_bytes`, from file content alone.

    `jj interdiff` diffs a rebased tree that has no commit id, so the
    commit-based helper cannot serve it. `jj evolog --patch` compares
    the same way, against a commit's predecessors.
    """
    context = getattr(args, "context", None)
    context = 3 if context is None else context
    compare = _compare_mode(args)
    to_ui_path = _ui_path_formatter(ws)
    short, long = _diff_formats(args) if formats is None else formats
    coloured = use_color(settings)

    def block(lines, label: str) -> bytes:
        if not lines:
            return b""
        return (render_block(lines, label, coloured)
                .encode("utf-8", "surrogateescape") + b"\n")

    out = b""
    if short == "summary":
        out = block(_summary_spans([_FileStat(f, compare) for f in files],
                                   to_ui_path), "diff summary")
    elif short == "stat":
        out = block(_diff_stats_lines([_FileStat(f, compare) for f in files]),
                    "diff stat")
    elif short == "types":
        out = block(_types_spans([_FileStat(f, compare) for f in files],
                                 to_ui_path), "diff types")
    elif short == "name_only":
        out = "".join(f"{to_ui_path(f.path)}\n" for f in files).encode(
            "utf-8", "surrogateescape")
    if long is None:
        return out
    if long.startswith(_TOOL_FORMAT):
        return out + _diff_tool_bytes(settings, long[len(_TOOL_FORMAT):],
                                      files)
    if long == "git":
        return out + _git_diff_bytes(files, context, coloured, compare)
    return out + _color_words_bytes(files, to_ui_path, context, coloured,
                                    compare)


def _print_diff_files(args, ws, files, settings=None) -> None:
    """`_diff_files_bytes`, written to stdout."""
    sys.stdout.flush()
    sys.stdout.buffer.write(_diff_files_bytes(args, ws, files, settings))
    sys.stdout.buffer.flush()


def _diff_bytes(args, ws, settings, base, target, paths,
                formats=None) -> bytes:
    """One place that decides which format a diff prints.

    jj's default is the color-words diff, not a file listing. Every
    path through `diff` reaches this with the same two commits, so the
    flags behave the same everywhere.

    A log-like command passes its own `formats`, since `jj log` prints
    no diff at all unless a flag asks for one. It also needs the bytes
    rather than the printing: the graph lays them beside its column.
    """
    context = getattr(args, "context", None)
    context = 3 if context is None else context
    compare = _compare_mode(args)
    to_ui_path = _ui_path_formatter(ws)
    short, long = _diff_formats(args) if formats is None else formats
    coloured = use_color(settings)

    def block(lines, label: str) -> bytes:
        """One rendered listing, with the newline that ends its last row.

        A listing of nothing is nothing: jj writes a line per file, so
        a diff that touches no file writes no blank line either.
        """
        if not lines:
            return b""
        return (render_block(lines, label, coloured)
                .encode("utf-8", "surrogateescape") + b"\n")

    out = b""
    if short == "summary":
        out = block(_summary_spans(base.diff(target, paths), to_ui_path),
                    "diff summary")
    elif short == "stat":
        out = block(_diff_stats_lines(
            base.diff_stats(target, settings, paths, compare)), "diff stat")
    elif short == "types":
        out = block(_types_spans(base.diff(target, paths), to_ui_path),
                    "diff types")
    elif short == "name_only":
        out = "".join(f"{to_ui_path(entry.path)}\n"
                      for entry in base.diff(target, paths)).encode(
                          "utf-8", "surrogateescape")
    if long is None:
        return out
    files = base.git_diff(target, settings, paths)
    if long.startswith(_TOOL_FORMAT):
        return out + _diff_tool_bytes(settings, long[len(_TOOL_FORMAT):],
                                      files)
    if long == "git":
        return out + _git_diff_bytes(files, context, coloured, compare)
    return out + _color_words_bytes(files, to_ui_path, context, coloured,
                                    compare)


def _print_diff(args, ws, settings, base, target, paths) -> None:
    """`_diff_bytes`, written to stdout."""
    sys.stdout.flush()
    sys.stdout.buffer.write(_diff_bytes(args, ws, settings, base, target,
                                        paths))
    sys.stdout.buffer.flush()
