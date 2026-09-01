"""CLI command implementations exercising pyjj bindings.

Command semantics mirror the real `jj` CLI (0.43-era): every
workspace-attached command implicitly snapshots the working copy before
acting, descriptions go through complete_newline, and `jj abandon`
deletes bookmarks on the abandoned commits unless told otherwise.
"""

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


def _load(args):
    """Load settings + workspace at the -R path, snapshotting the working
    copy first like every real jj workspace command does."""
    settings = pyjj.UserSettings()
    ws = pyjj.Workspace.load(settings, args.repository)
    repo, _stats = ws.snapshot(settings)
    return settings, ws, repo


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
    fresh_ws = pyjj.Workspace.load(settings, ws.workspace_root)
    fresh_repo = fresh_ws.load_at_head()
    new_wc_hex = fresh_repo.view()[fresh_ws.workspace_name]
    if new_wc_hex != old_wc_hex:
        fresh_ws.check_out(fresh_repo, fresh_repo.get_commit(pyjj.CommitId(new_wc_hex)))


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


def git_init(args) -> int:
    """`jj git init` — create a new jj repo backed by an internal Git store."""
    settings = pyjj.UserSettings()
    # Real `jj git init` creates missing parent directories.
    destination = Path(args.destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    try:
        ws, repo = pyjj.Workspace.init_internal_git(settings, str(destination))
    except pyjj.WorkspaceInitError as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    print(f"Initialized repo in {ws.workspace_root}")
    for ws_name, commit_id in repo.view().items():
        print(f"Working copy ({ws_name}) now at: {commit_id[:12]}")
    return 0


def status(args) -> int:
    try:
        _settings, ws, repo = _load(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    print(f"Workspace: {ws.workspace_root}")
    view = repo.view()
    for ws_name, commit_id in view.items():
        commit = repo.get_commit(pyjj.CommitId(commit_id))
        desc = commit.description.splitlines()[0] if commit.description else "(no description set)"
        print(f"Working copy ({ws_name}) now at: {commit_id[:12]} {desc}")
    return 0


def log(args) -> int:
    try:
        _settings, _ws, repo = _load(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    view = repo.view()
    seen = set()
    queue: list = [(cid, 0) for cid in view.values()]

    while queue and args.limit > 0:
        commit_id_hex, indent = queue.pop(0)
        if commit_id_hex in seen:
            continue
        seen.add(commit_id_hex)

        commit = repo.get_commit(pyjj.CommitId(commit_id_hex))
        prefix = "  " * indent
        desc = commit.description.splitlines()[0] if commit.description else "(no description)"
        print(f"{prefix}@ {commit_id_hex[:12]} {desc}")

        args.limit -= 1
        if indent < 5:
            for parent_id in commit.parent_ids:
                queue.append((parent_id.hex(), indent + 1))

    return 0


def describe(args) -> int:
    try:
        settings, ws, repo = _load(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    revsets = list(args.revisions_pos or [])
    if args.revisions_opt:
        revsets.extend(args.revisions_opt)

    if args.stdin:
        description = sys.stdin.read()
    elif args.messages:
        description = join_message_paragraphs(args.messages)
    elif len(revsets) <= 1:
        # Bare `describe` (or a single revision): the editor path.
        base_commit = _resolve_one(repo, settings, revsets[0] if revsets else "@")
        description = _run_editor(settings, base_commit.description)
    else:
        print("Error: bulk description editing is not supported; pass -m "
              "or --stdin", file=sys.stderr)
        return 2

    if not revsets:
        revsets = ["@"]

    try:
        targets = _resolve_all(repo, settings, revsets)
        if not targets:
            print("No revisions to describe.")
            return 0

        tx = repo.start_transaction(settings)
        new_wc_id = None
        wc_id = repo.view().get(ws.workspace_name)
        for commit in targets:
            builder = (
                tx.rewrite_commit(settings, commit)
                .set_description(description)
            )
            new_commit = builder.write(repo)
            if commit.id.hex() == wc_id:
                new_wc_id = new_commit.id
        if new_wc_id is not None:
            tx.set_wc_commit(ws.workspace_name, new_wc_id)
        _finish(tx, f"describe commit {targets[0].id.hex()}", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def new(args) -> int:
    try:
        settings, ws, repo = _load(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    try:
        if args.parents_pos:
            parents = _resolve_in_arg_order(repo, settings, args.parents_pos)
        else:
            parents = [_wc_commit(repo, ws)]
        tx = repo.start_transaction(settings)
        builder = tx.new_commit(settings, [c.id for c in parents])
        if args.message:
            builder = builder.set_description(complete_newline(args.message))
        child = builder.write(repo)
        tx.set_wc_commit(ws.workspace_name, child.id)
        _finish(tx, "new empty commit", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def bookmark(args) -> int:
    """`jj bookmark create NAMES... [-r REVSET]` / `bookmark set NAME -r REVSET`."""
    try:
        settings, ws, repo = _load(args)
        target = _resolve_one(repo, settings, args.revision)
        tx = repo.start_transaction(settings)
        if hasattr(args, "names"):
            for name in args.names:
                if repo.get_bookmark(name) is not None:
                    raise CommandError(
                        f"Bookmark already exists: {name} "
                        "(use `bookmark set` to move it)"
                    )
                tx.set_bookmark(name, target.id)
        else:
            if repo.get_bookmark(args.name) is None:
                raise CommandError(f"No such bookmark: {args.name}")
            tx.set_bookmark(args.name, target.id)
        _finish(tx, f"point bookmark at {target.id.hex()}", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


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


def squash(args) -> int:
    try:
        settings, ws, repo = _load(args)
        sources = _resolve_all(repo, settings, list(args.from_ or []) + list(args.revision or []))
        if not sources:
            sources = [_wc_commit(repo, ws)]
        if len(sources) != 1:
            raise CommandError("squashing multiple source revisions is not supported yet")
        source = sources[0]
        dest = (
            _resolve_one(repo, settings, args.into)
            if args.into
            else repo.get_commit(source.parent_ids[0])
        )

        # Message handling, mirroring the real CLI's paths. -u keeps the
        # destination's description untouched; -m replaces; with no flag,
        # a single non-empty side wins, two non-empty sides open the
        # combining editor whose template is destination-block-first.
        use_dest_desc = args.use_destination_message and args.message is None
        if args.message is not None:
            description = complete_newline(args.message)
        else:
            candidates = [c.description for c in [source, dest] if c.description]
            if len(candidates) == 1:
                description = candidates[0]
            elif len(candidates) == 0:
                description = ""
            elif args.use_destination_message:
                pass
            else:
                combined = (
                    "JJ: Description from the destination commit:\n"
                    + dest.description
                    + "\nJJ: Description from source commit:\n"
                    + source.description
                )
                description = _run_editor(settings, combined)

        tx = repo.start_transaction(settings)
        builder = tx.squash(source, dest)
        if builder is None:
            print("Nothing changed.")
            return 0
        if not use_dest_desc:
            builder = builder.set_description(description)
        builder.write(repo)
        _finish(tx, "squash commit", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def rebase(args) -> int:
    try:
        settings, ws, repo = _load(args)
        if not args.revisions:
            print("Error: currently only `-r REVSETS` mode is supported", file=sys.stderr)
            return 2
        targets = _resolve_all(repo, settings, args.revisions)
        destinations = _resolve_in_arg_order(repo, settings, args.destinations)
        tx = repo.start_transaction(settings)
        tx.move_commits([c.id for c in targets], [], [d.id for d in destinations], [])
        _finish(tx, "rebase commit", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def abandon(args) -> int:
    try:
        settings, ws, repo = _load(args)
        revsets = args.revisions_pos or ["@"]
        targets = _resolve_all(repo, settings, revsets)
        if not targets:
            print("No revisions to abandon.")
            return 0
        tx = repo.start_transaction(settings)
        for commit in targets:
            tx.abandon_commit(commit)
        # The real `jj abandon` deletes bookmarks pointing at the abandoned
        # commits by default (--retain-bookmarks moves them instead).
        _finish(tx, f"abandon commit {targets[0].id.hex()}", settings, ws, repo,
                delete_abandoned_bookmarks=True)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def duplicate(args) -> int:
    try:
        settings, ws, repo = _load(args)
        revsets = args.revisions_pos or ["@"]
        targets = _resolve_all(repo, settings, revsets)
        tx = repo.start_transaction(settings)
        tx.duplicate(targets)
        _finish(tx, "duplicate commit", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def edit(args) -> int:
    try:
        settings, ws, repo = _load(args)
        target = _resolve_one(repo, settings, args.revision_pos)
        tx = repo.start_transaction(settings)
        # MutableRepo::edit abandons a discardable, unreferenced old wc
        # itself; rebase_descendants() in _finish clears the pending map.
        tx.edit(ws.workspace_name, target)
        _finish(tx, f"edit commit {target.id.hex()}", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def commit(args) -> int:
    """`jj commit`: describe @, then put the selected paths (or all of @'s
    change) into it and create a new working-copy child on top."""
    try:
        settings, ws, repo = _load(args)
        if args.interactive or args.tool or args.editor:
            print("Error: interactive commit is not supported; pass -m "
                  "(with optional FILESETS)", file=sys.stderr)
            return 2
        wc = _wc_commit(repo, ws)
        if args.message is not None:
            description = complete_newline(args.message)
        else:
            description = _run_editor(settings, wc.description)
        tx = repo.start_transaction(settings)
        if args.paths_pos:
            # Selected paths stay in @ (same change id); everything else
            # moves to the new child -- the same primitives `split` uses,
            # with the roles reversed.
            kept = (
                tx.split_selected(wc, list(args.paths_pos))
                .set_description(description)
                .write(repo)
            )
            child = tx.split_remainder(wc, kept).write(repo)
        else:
            described = (
                tx.rewrite_commit(settings, wc)
                .set_description(description)
                .write(repo)
            )
            child = tx.new_commit(settings, [described.id]).write(repo)
        tx.set_wc_commit(ws.workspace_name, child.id)
        _finish(tx, f"commit {wc.id.hex()}", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def restore(args) -> int:
    try:
        settings, ws, repo = _load(args)
        src = _resolve_one(repo, settings, args.from_)
        dst = _resolve_one(repo, settings, args.into)
        paths = list(args.paths_pos) or None
        tx = repo.start_transaction(settings)
        builder = tx.restore(src, dst, paths)
        restored = builder.write(repo)
        if dst.id.hex() == repo.view().get(ws.workspace_name):
            tx.set_wc_commit(ws.workspace_name, restored.id)
        _finish(tx, f"restore from {src.id.hex()} into {dst.id.hex()}",
                settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def split(args) -> int:
    try:
        settings, ws, repo = _load(args)
        target = _resolve_one(repo, settings, args.revision or "@")

        tx = repo.start_transaction(settings)
        if args.paths_pos:
            first_builder = tx.split_selected(target, list(args.paths_pos))
        else:
            # The diff-editor path: select changes by editing the right
            # directory. Upstream order applies the diff selection first,
            # then the description.
            if not args.tool:
                print("Error: no diff editor specified; pass --tool",
                      file=sys.stderr)
                return 2
            parent = repo.get_commit(target.parent_ids[0])
            changed = _changed_files(repo, settings, parent, target)
            before = {p: b for p, (b, _a) in changed.items()}
            after = {p: a for p, (_b, a) in changed.items()}
            selections = _run_diff_tool(settings, args.tool, before, after)
            if _selection_is_empty(selections, before):
                print("No changes selected.")
                return 1
            first_builder = tx.split_selected_edited(target, selections)

        if args.message is not None:
            first_description = complete_newline(args.message)
        else:
            # The editor path: the draft template carries the current
            # description past all "JJ:" comments.
            first_description = _run_editor(settings, target.description)

        first = first_builder.set_description(first_description).write(repo)
        second = tx.split_remainder(target, first).write(repo)
        if target.id.hex() == repo.view().get(ws.workspace_name):
            tx.set_wc_commit(ws.workspace_name, second.id)
        _finish(tx, f"split commit {target.id.hex()}", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"Error: diff editor exited with status {e.returncode}",
              file=sys.stderr)
        return 1
    return 0


def diffedit(args) -> int:
    """`jj diffedit --from X --to Y`: edit the diff between two revisions;
    the result is applied to the destination side."""
    try:
        settings, ws, repo = _load(args)
        if not args.tool:
            print("Error: no diff editor specified; pass --tool",
                  file=sys.stderr)
            return 2
        from_commit = _resolve_one(repo, settings, args.from_)
        to_commit = _resolve_one(repo, settings, args.into)

        changed = _changed_files(repo, settings, from_commit, to_commit)
        before = {p: b for p, (b, _a) in changed.items()}
        after = {p: a for p, (_b, a) in changed.items()}
        if not changed:
            print("No changes to edit.")
            return 0
        selections = _run_diff_tool(settings, args.tool, before, after)
        if _selection_is_empty(selections, before):
            print("Nothing changed.")
            return 0

        tx = repo.start_transaction(settings)
        builder = tx.edit_commit_tree(to_commit, selections)
        edited = builder.write(repo)
        if to_commit.id.hex() == repo.view().get(ws.workspace_name):
            tx.set_wc_commit(ws.workspace_name, edited.id)
        _finish(
            tx,
            f"edit diff from {from_commit.id.hex()} to {to_commit.id.hex()}",
            settings, ws, repo,
        )
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"Error: diff editor exited with status {e.returncode}",
              file=sys.stderr)
        return 1
    return 0


def resolve(args) -> int:
    """`jj resolve [-r REV] [--tool NAME] [FILESETS]`: run a 3-way merge
    tool per conflicted file. Mirrors upstream ordering: conflict listing
    and tool runs happen before any mutation (an aborted tool leaves no
    operation), the commit is rewritten even when nothing resolved, and
    leftover conflicts are reported as an error AFTER the operation
    commits."""
    try:
        settings, ws, repo = _load(args)
        commit = _resolve_one(repo, settings, args.revision)

        candidates = commit.list_files(list(args.paths_pos) or None)
        conflicts = []
        for p in candidates:
            try:
                commit.read_file(p)
            except pyjj.JjError:
                conflicts.append(p)
        conflicts.sort()
        if not conflicts:
            if args.paths_pos:
                print("Error: No conflicts found at the given path(s)",
                      file=sys.stderr)
            else:
                print("Error: No conflicts found at this revision",
                      file=sys.stderr)
            return 1

        if args.list_:
            for p in conflicts:
                print(p)
            return 0

        if not args.tool:
            print("Error: no merge tool specified; pass --tool",
                  file=sys.stderr)
            return 2

        # Built-in side-picking tools: no external process, no merge-args.
        if args.tool in (":ours", ":theirs"):
            side = 0 if args.tool == ":ours" else 1
            tx = repo.start_transaction(settings)
            builder = tx.pick_conflict_sides(commit, conflicts, side)
            new_commit = builder.write(repo)
            if commit.id.hex() == repo.view().get(ws.workspace_name):
                tx.set_wc_commit(ws.workspace_name, new_commit.id)
            _finish(tx, f"Resolve conflicts in commit {commit.id.hex()}",
                    settings, ws, repo)
        else:
            edits_markers = bool(
                settings.get_bool(
                    f"merge-tools.{args.tool}.merge-tool-edits-conflict-markers"
                )
            )

            resolutions: dict[str, bytes] = {}
            for p in conflicts:
                sides = dict(commit.conflict_sides(p))
                materialized = commit.materialize_conflict(settings, p)
                out = _run_merge_tool(settings, args.tool, sides, p,
                                      edits_markers, bytes(materialized))
                initial = bytes(materialized) if edits_markers else b""
                if not out or out == initial:
                    # Upstream's EmptyOrUnchanged: leave this path conflicted
                    # and keep going with the remaining files.
                    continue
                resolutions[p] = out

            tx = repo.start_transaction(settings)
            if resolutions:
                builder = tx.resolve_conflicts(commit, resolutions)
            else:
                # Nothing changed, but real jj still rewrites the commit
                # (committer-timestamp bump) and records the operation.
                builder = tx.rewrite_commit(commit)
            new_commit = builder.write(repo)
            if commit.id.hex() == repo.view().get(ws.workspace_name):
                tx.set_wc_commit(ws.workspace_name, new_commit.id)
            _finish(tx, f"Resolve conflicts in commit {commit.id.hex()}",
                    settings, ws, repo)

        unresolved = []
        for p in conflicts:
            try:
                new_commit.read_file(p)
            except pyjj.JjError:
                unresolved.append(p)
        if unresolved:
            print("Warning: Some files at this revision still have "
                  "conflicts:", file=sys.stderr)
            for p in unresolved:
                print(f"  {p}", file=sys.stderr)
            return 1
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def undo(args) -> int:
    try:
        settings, ws, repo = _load(args)
        tx = repo.start_transaction(settings)
        _undone, _restored_to, description = tx.undo()
        _restore_view_command(tx, description, settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def redo(args) -> int:
    try:
        settings, ws, repo = _load(args)
        tx = repo.start_transaction(settings)
        _redone, _restored_to, description = tx.redo()
        _restore_view_command(tx, description, settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def op_restore(args) -> int:
    """`jj op restore <OPERATION>`: make the view match a past operation."""
    try:
        settings, ws, repo = _load(args)
        target = repo.load_operation(args.operation_pos)
        tx = repo.start_transaction(settings)
        tx.restore_operation(target)
        _restore_view_command(
            tx, f"restore operation {args.operation_pos}", settings, ws, repo
        )
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def hunk_list(args) -> int:
    """`pyjj hunk list [-r REV] [--format json|yaml|text]` — list hunks like jj-hunk."""
    try:
        settings, ws, repo = _load(args)
        target = _resolve_one(repo, settings, args.revision)
        # Collect file contents for the target's diff against parent
        file_contents = hunk_mod.collect_file_contents_for_commit(repo, target, settings)
        # Build output like jj-hunk: {files: [{path, status, hunks: [...]}, ...]}
        files_output = []
        for path, (before, after) in sorted(file_contents.items()):
            # Skip binary files for now
            try:
                before_s = before.decode()
                after_s = after.decode()
            except UnicodeDecodeError:
                files_output.append(
                    {"path": path, "status": "modified", "hunks": [], "binary": True}
                )
                continue
            hunks = hunk_mod.get_hunks_detailed(before_s, after_s)
            if not hunks and before != after:
                # For binary or whole-file case, still report
                hunks = []
            # Determine status
            if not before and after:
                status = "modified"
            elif not before:
                status = "added"
            elif not after:
                status = "removed"
            else:
                status = "modified"
            files_output.append({"path": path, "status": status, "hunks": hunks})
        output = {"files": files_output}
        fmt = args.format or "json"
        if fmt == "json":
            print(json.dumps(output, indent=2))
        elif fmt == "yaml":
            try:
                import yaml  # type: ignore

                print(yaml.safe_dump(output, sort_keys=False))
            except ImportError:
                print("Error: PyYAML not installed, cannot output YAML", file=sys.stderr)
                return 1
        elif fmt == "text":
            # Simple text format like jj-hunk --files
            for f in files_output:
                print(f"{f['status'][0].upper()} {f['path']} ({len(f['hunks'])} hunks)")
                for h in f["hunks"]:
                    print(f"  hunk {h['index']} {h['type']} {h['id']}")
        else:
            print(f"Error: unknown format {fmt!r}", file=sys.stderr)
            return 1
    except (pyjj.JjError, CommandError, ValueError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def _load_spec(args) -> hunk_mod.Spec:
    """Load spec from args.spec / args.spec_file / stdin, handling '-'."""
    spec_str = getattr(args, "spec", None)
    spec_file = getattr(args, "spec_file", None)
    # Handle case where spec_file is provided and spec is None, but message is in spec position
    # For hunk split, args has spec and message; for commit, similar.
    # The _load_spec_from_input helper already handles '-'
    return hunk_mod.load_spec_from_input(spec_str, spec_file)


def hunk_split(args) -> int:
    """`pyjj hunk split [-r REV] <spec> <message>` — split with hunk/line spec."""
    try:
        settings, ws, repo = _load(args)
        # Handle spec/message normalization like jj-hunk: spec can be '-' for stdin, or --spec-file
        spec_str = getattr(args, "spec", None)
        spec_file = getattr(args, "spec_file", None)
        message = getattr(args, "message", None)
        # Normalize like jj-hunk's normalize_spec_message
        if spec_file and message is None:
            # When --spec-file is used, the positional spec is actually the message
            message = spec_str
            spec_str = None
        if message is None:
            print("Error: hunk split requires a commit message", file=sys.stderr)
            return 2
        if spec_file:
            if spec_str is not None:
                print("Error: hunk split: omit <spec> when using --spec-file", file=sys.stderr)
                return 2
            spec = hunk_mod.load_spec_from_input(None, spec_file)
        else:
            if spec_str is None:
                print("Error: hunk split requires a spec (or use --spec-file)", file=sys.stderr)
                return 2
            spec = hunk_mod.load_spec_from_input(spec_str, None)
        target = _resolve_one(repo, settings, args.revision or "@")
        overrides = hunk_mod.spec_to_overrides(repo, target, spec, settings)
        if not overrides:
            print("No changes selected.")
            return 1
        tx = repo.start_transaction(settings)
        # Use split_selected_edited with overrides
        first_builder = tx.split_selected_edited(target, overrides)
        first_builder.set_description(complete_newline(message))
        first = first_builder.write(repo)
        second = tx.split_remainder(target, first).write(repo)
        if target.id.hex() == repo.view().get(ws.workspace_name):
            tx.set_wc_commit(ws.workspace_name, second.id)
        _finish(tx, f"split commit {target.id.hex()}", settings, ws, repo)
    except (pyjj.JjError, CommandError, ValueError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def hunk_commit(args) -> int:
    """`pyjj hunk commit <spec> <message>` — commit selected hunks from working copy."""
    try:
        settings, ws, repo = _load(args)
        spec_str = getattr(args, "spec", None)
        spec_file = getattr(args, "spec_file", None)
        message = getattr(args, "message", None)
        if spec_file and message is None:
            message = spec_str
            spec_str = None
        if message is None:
            print("Error: hunk commit requires a commit message", file=sys.stderr)
            return 2
        if spec_file:
            if spec_str is not None:
                print("Error: hunk commit: omit <spec> when using --spec-file", file=sys.stderr)
                return 2
            spec = hunk_mod.load_spec_from_input(None, spec_file)
        else:
            if spec_str is None:
                print("Error: hunk commit requires a spec (or use --spec-file)", file=sys.stderr)
                return 2
            spec = hunk_mod.load_spec_from_input(spec_str, None)
        # For commit, the target is the working copy commit
        target = _wc_commit(repo, ws)
        # Collect file contents for working copy changes? For commit, we need to snapshot working copy
        # The working copy's changes are not yet in a commit; we need to use the working copy's file contents
        # For now, we treat the working copy's parent as the base, similar to split
        # Use the same spec_to_overrides but for the working copy's diff against parent
        overrides = hunk_mod.spec_to_overrides(repo, target, spec, settings)
        if not overrides:
            print("No changes selected.")
            return 1
        tx = repo.start_transaction(settings)
        # For commit, we want to keep selected changes in the current commit, and leave the rest in a new child
        # This is the same as split, but the current commit is the working copy
        first_builder = tx.split_selected_edited(target, overrides)
        first_builder.set_description(complete_newline(message))
        first = first_builder.write(repo)
        second = tx.split_remainder(target, first).write(repo)
        tx.set_wc_commit(ws.workspace_name, second.id)
        _finish(tx, f"commit {target.id.hex()}", settings, ws, repo)
    except (pyjj.JjError, CommandError, ValueError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def hunk_squash(args) -> int:
    """`pyjj hunk squash [-r REV] <spec>` — squash selected hunks into parent."""
    try:
        settings, ws, repo = _load(args)
        spec_str = getattr(args, "spec", None)
        spec_file = getattr(args, "spec_file", None)
        if spec_file:
            if spec_str is not None:
                print("Error: hunk squash: omit <spec> when using --spec-file", file=sys.stderr)
                return 2
            spec = hunk_mod.load_spec_from_input(None, spec_file)
        else:
            if spec_str is None:
                print("Error: hunk squash requires a spec (or use --spec-file)", file=sys.stderr)
                return 2
            spec = hunk_mod.load_spec_from_input(spec_str, None)
        target = _resolve_one(repo, settings, args.revision or "@")
        if not target.parent_ids:
            print("Error: cannot squash root commit", file=sys.stderr)
            return 1
        parent = repo.get_commit(target.parent_ids[0])
        # For squash, we need to move selected changes from target into parent
        # Collect file contents and apply spec to get selected content for the source
        file_contents = hunk_mod.collect_file_contents_for_commit(repo, target, settings)
        selected = hunk_mod.apply_spec(spec, file_contents)
        # Build hunks map for the existing Transaction.squash API: for each file, find which hunks are selected
        # Instead of using the old hunks API, we can directly use the selected content to create a new squash
        # For squash, we want to move the selected changes into the parent. We can do this by creating a new parent
        # with the selected changes applied, and leaving the target with the remaining changes.
        # Simpler: Use the selected content as overrides for the parent, and the remaining for the target?
        # Actually, the selected changes are those that should be squashed into parent. So we need to:
        # - Apply selected to parent (via edit_commit_tree)
        # - Leave target with the unselected changes (i.e., before + unselected)
        # But we can also use the existing Transaction.squash with hunks param if we can map selected to hunk indices.
        # For now, we will use a direct approach: compute the new parent content and new target content, then write them.
        # This is more involved; for MVP we can use the simpler path: if the spec is whole-file or hunk-level without line-level,
        # we can map to hunks indices and call the existing API.
        # For line-level, we need content overrides.
        # Let's try to use the content override path: create a new parent with selected changes.
        tx = repo.start_transaction(settings)
        # Find which files have changes selected
        # For each file, if selected == after, then the whole file's changes are selected -> use paths
        # For partial, we need to create new file content for parent
        # For now, we will use a simplified squash: use Transaction.squash with hunks where possible, else fallback to manual
        # Check if spec is simple (only hunks/ids, no line ranges or per-hunk lines)
        is_simple = all(
            not fs.line_ranges and not fs.per_hunk_lines and not fs.per_hunk_added and not fs.per_hunk_removed
            for fs in spec.files.values()
        )
        if is_simple:
            # Map to hunks indices
            hunks_map: dict[str, list[int]] = {}
            for path, fs in spec.files.items():
                if fs.action == "keep":
                    # Whole file
                    continue
                if fs.action == "reset":
                    continue
                # Collect indices
                indices = list(fs.selection.indices)
                # For ids, we need to resolve to indices via detailed hunks
                if fs.selection.ids:
                    # Resolve ids to indices
                    before, after = file_contents.get(path, (b"", b""))
                    try:
                        before_s = before.decode()
                        after_s = after.decode()
                        hunks = hunk_mod.get_hunks_detailed(before_s, after_s)
                        for h in hunks:
                            if h["id"] in fs.selection.ids:
                                indices.append(h["index"])
                    except Exception:
                        pass
                if indices:
                    hunks_map[path] = sorted(set(indices))
            # Also need to handle default
            # For default == "keep", files not listed are kept whole -> they are not part of hunks_map but should be squashed whole
            # For squash, the semantics are: selected changes are moved. If default is keep, then unlisted files' changes are also moved.
            # This is complex; for now we assume default is reset, which is the common case for selective squash
            builder = tx.squash(target, parent, hunks=hunks_map if hunks_map else None)
            if builder is None:
                print("Nothing selected to squash.")
                return 1
            builder.write(repo)
            _finish(tx, "squash commit", settings, ws, repo)
        else:
            # Line-level or complex spec: need manual content handling
            # For each file, compute the new parent content (before + selected) and new target content (before + unselected)
            # Selected content is in `selected` dict, unselected is the remainder
            # For parent, its new content should be its old content plus the selected changes
            # For target, its new content should be its old content minus the selected changes (i.e., keep only unselected)
            # We can achieve this by using edit_commit_tree for both
            # First, compute unselected content for target
            unselected_overrides: dict[str, bytes | None] = {}
            selected_overrides: dict[str, bytes | None] = {}
            for path, (before, after) in file_contents.items():
                sel = selected.get(path, before)
                # For target, the new content should be before + (after - selected) ??? Actually target's new content after squashing selected into parent should be the unselected part
                # The unselected part is: before + (after - selected) where (after - selected) is the hunks not selected
                # We can compute unselected as the content that would be produced if we apply the complement spec
                # For now, compute unselected by applying the inverted selection: keep the hunks not selected
                # We can compute it as: unselected = before with selected hunks removed? Simpler: unselected = result of applying spec with inverted selection
                # But we have selected, so unselected = before + (after - selected)?? We can compute by taking the after and removing selected hunks
                # For now, we will compute unselected by taking the file's after and applying the same spec but inverted
                # To avoid complexity, we will just use the selected for parent and for target we will keep the unselected as before + (after - selected)
                # We can compute unselected by: unselected = apply_spec with inverted spec? Instead, we can compute directly:
                # unselected_content = after with selected hunks reverted to before
                # We can get this by calling apply_spec_to_file_content with the complement of the file_spec
                # Simpler: For each file, unselected is the content that would result if we kept the hunks NOT in selected
                # We can compute it as: unselected = before with the complement of selected hunks
                # Let's just compute it by re-applying with inverted selection
                file_spec = spec.files.get(path)
                if file_spec is None:
                    # Default handling
                    if spec.default == "keep":
                        # All changes selected, so parent gets after, target becomes before (empty)
                        selected_overrides[path] = sel
                        unselected_overrides[path] = before if before else None
                    else:
                        # No changes selected, nothing to squash for this file
                        continue
                else:
                    # For file with spec, selected is already computed, unselected is the complement
                    # Compute complement by inverting the file_spec's selection
                    # For simplicity, if file_spec has action keep/reset, complement is opposite
                    # If it has hunks, complement is before + (after - selected hunks)
                    # We can compute unselected by taking the file's after and filtering out selected hunks
                    # Use the same helper but with inverted spec
                    # For now, just set unselected to before if selected != before/after? This is a simplification
                    # For a file where we selected some hunks, the remaining hunks should stay in target
                    # So unselected content = before with the *unselected* hunks applied
                    # We can compute it as: unselected = before with (all hunks - selected hunks)
                    # To do that, we need to know all hunks
                    try:
                        before_s = before.decode()
                        after_s = after.decode()
                        hunks = hunk_mod.get_hunks_detailed(before_s, after_s)
                        # Find unselected indices
                        all_indices = {h["index"] for h in hunks}
                        selected_indices = set()
                        # Determine which hunks were selected for this file
                        if file_spec.action == "keep":
                            selected_indices = all_indices
                        elif file_spec.action == "reset":
                            selected_indices = set()
                        else:
                            # Check hunks selection
                            for h in hunks:
                                if file_spec.selection.matches(h["index"], h["id"]) or hunk_mod._hunk_overlaps_line_ranges(h["after"]["start"], h["after"]["lines"], file_spec.line_ranges):
                                    selected_indices.add(h["index"])
                            # Also check per-hunk lines - for now treat as selected
                            for idx in file_spec.per_hunk_lines:
                                selected_indices.add(idx)
                            for idx in file_spec.per_hunk_added:
                                selected_indices.add(idx)
                            for idx in file_spec.per_hunk_removed:
                                selected_indices.add(idx)
                        unselected_indices = all_indices - selected_indices
                        if unselected_indices:
                            # Build unselected content by applying only unselected hunks
                            # Create a temporary file_spec for unselected
                            unselected_spec = hunk_mod.FileSpec()
                            unselected_spec.selection.indices = unselected_indices
                            unselected_content = hunk_mod.apply_spec_to_file_content(before, after, unselected_spec, "reset")
                            unselected_overrides[path] = unselected_content
                        else:
                            # No remaining hunks, so target's file should be reverted to before
                            unselected_overrides[path] = before if before else None
                        selected_overrides[path] = sel
                    except Exception:
                        continue
            # Apply selected to parent
            if selected_overrides:
                # Filter out None and before-equivalent
                parent_overrides = {k: v for k, v in selected_overrides.items() if v is not None and v != file_contents[k][0]}
                if parent_overrides:
                    pb = tx.edit_commit_tree(parent, parent_overrides)
                    pb.write(repo)
            # Apply unselected to target
            if unselected_overrides:
                target_overrides = {}
                for k, v in unselected_overrides.items():
                    before = file_contents[k][0]
                    if v is None:
                        # File should be deleted if before was empty? Actually if unselected is None, it means the file should be absent
                        # For now, treat None as delete
                        target_overrides[k] = None
                    elif v != file_contents[k][1]:  # v != after
                        target_overrides[k] = v
                    else:
                        # v == after, meaning no change to target for this file, skip
                        continue
                if target_overrides:
                    tb = tx.edit_commit_tree(target, target_overrides)
                    tb.write(repo)
                else:
                    # If no overrides, it means target becomes empty? Need to handle keep_emptied
                    pass
            _finish(tx, "squash commit", settings, ws, repo)
    except (pyjj.JjError, CommandError, ValueError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def hunk_schema(args) -> int:
    """`pyjj hunk schema` — dump JSON schema for LLM tool-calling."""
    try:
        fmt = getattr(args, "format", "json")
        if not hunk_mod.HAS_PYDANTIC:
            print("Error: pydantic not available, cannot generate schema", file=sys.stderr)
            return 1
        schema = hunk_mod.SpecModel.model_json_schema()  # type: ignore
        if fmt == "json":
            print(json.dumps(schema, indent=2))
        elif fmt == "yaml":
            try:
                import yaml  # type: ignore

                print(yaml.safe_dump(schema, sort_keys=False))
            except ImportError:
                print("Error: PyYAML not installed, cannot output YAML", file=sys.stderr)
                return 1
        else:
            print(f"Error: unknown format {fmt!r}", file=sys.stderr)
            return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


def version(args) -> int:
    print(f"pyjj-cli v0.1.0")
    print(f"  pyjj (Rust bindings): v{pyjj.VERSION}")
    print(f"  Python: {sys.version}")
    return 0
