"""Shared helpers for CLI commands."""
"""CLI command implementations exercising pyjj bindings."""
import json
import os
import shlex
import subprocess
import sys
import tempfile
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

def _finish(tx, description, settings, ws, base_repo, *, delete_abandoned_bookmarks=False):
    """Commit the transaction, then mirror the real CLI's
    transaction-finish behavior: when a rewrite moved the working-copy
    commit (e.g. an abandon or rebase rebased it), update the on-disk
    working copy to match."""
    old_wc_hex = base_repo.view()[ws.workspace_name]
    tx.rebase_descendants(delete_abandoned_bookmarks)
    tx.commit(description)
    _checkout_if_moved(settings, ws, old_wc_hex)

def _restore_view_command(tx, description, settings, ws, repo):
    """Shared tail for view-restoring operations (undo/redo/op restore):
    they produce no rewrites to rebase and take their operation description
    verbatim from the binding -- for undo/redo it encodes the target op so
    future stack jumps keep working."""
    old_wc_hex = repo.view()[ws.workspace_name]
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
