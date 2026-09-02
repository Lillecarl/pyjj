"""pyjj-cli commands: rewrite."""
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

import pyjj
import pyjj.hunk as hunk_mod
from .common import (
    CommandError,
    _checkout_if_moved,
    _finish,
    _load,
    _resolve_all,
    _resolve_in_arg_order,
    _resolve_one,
    _restore_view_command,
    _wc_commit,
    complete_newline,
    join_message_paragraphs,
    _run_editor,
    _changed_files,
    _run_diff_tool,
    _selection_is_empty,
    _merge_marker_len,
    _run_merge_tool,
    _fix_pattern_matches,
)

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
        paths = getattr(args, "filesets", None) or None
        # Normalize empty list to None (means all paths)
        if paths == []:
            paths = None
        builder = tx.squash(source, dest, paths=paths)
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
        # Determine source mode: -r (commit_ids), -s (root_ids), -b (branch roots)
        revisions = getattr(args, "revisions", None)
        sources = getattr(args, "sources", None)
        branches = getattr(args, "branches", None)
        # Count how many source modes were given
        mode_count = sum(1 for m in (revisions, sources, branches) if m)
        if mode_count == 0:
            # Default is -b @ when nothing given, like real jj
            sources = ["@"]
            mode_count = 1
        if mode_count > 1:
            print("Error: specify only one of -r, -s, -b", file=sys.stderr)
            return 2
        if revisions:
            targets = _resolve_all(repo, settings, revisions)
            target_commit_ids = [c.id for c in targets]
            target_root_ids = []
        elif sources:
            roots = _resolve_all(repo, settings, sources)
            target_root_ids = [c.id for c in roots]
            target_commit_ids = []
        else:  # branches
            roots = _resolve_all(repo, settings, branches)
            target_root_ids = [c.id for c in roots]
            target_commit_ids = []

        # Destinations: -d/--destination, -o/--onto, -A/--insert-after, -B/--insert-before
        dests = getattr(args, "destinations", None) or []
        ontos = getattr(args, "ontos", None) or []
        afters = getattr(args, "insert_afters", None) or []
        befores = getattr(args, "insert_befores", None) or []

        # Expand -o as alias for -d
        new_parent_ids: list[pyjj.CommitId] = []
        new_child_ids: list[pyjj.CommitId] = []

        # Collect plain destinations (-d / -o)
        plain_dests = list(dests) + list(ontos)
        if plain_dests:
            if afters or befores:
                print("Error: cannot combine -d/-o with -A/-B", file=sys.stderr)
                return 2
            dest_commits = _resolve_in_arg_order(repo, settings, plain_dests)
            new_parent_ids = [c.id for c in dest_commits]
            new_child_ids = []
        elif afters:
            # -A: insert after -> new parents = after, new children = children(after)
            after_commits = _resolve_in_arg_order(repo, settings, afters)
            new_parent_ids = [c.id for c in after_commits]
            # Find children of after commits via revset
            try:
                children_expr = " | ".join(f"children({a})" for a in afters)
                children = repo.revset(settings, children_expr)
                new_child_ids = [c.id for c in children]
            except pyjj.JjError:
                new_child_ids = []
        elif befores:
            # -B: insert before -> new children = before, new parents = parents(before)
            before_commits = _resolve_in_arg_order(repo, settings, befores)
            new_child_ids = [c.id for c in before_commits]
            parents_set: dict[str, pyjj.Commit] = {}
            for c in before_commits:
                for pid in c.parent_ids:
                    try:
                        p = repo.get_commit(pid)
                        parents_set[pid.hex()] = p
                    except pyjj.JjError:
                        pass
            new_parent_ids = [c.id for c in parents_set.values()]
        else:
            print("Error: no destination specified (use -d, -o, -A or -B)", file=sys.stderr)
            return 2

        tx = repo.start_transaction(settings)
        tx.move_commits(target_commit_ids, target_root_ids, new_parent_ids, new_child_ids)
        _finish(tx, "rebase commit", settings, ws, repo)
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0

def absorb(args) -> int:
    """`jj absorb --from X --into Y [FILESETS]` — move hunks into ancestors."""
    try:
        settings, ws, repo = _load(args)
        if getattr(args, "interactive", False) or getattr(args, "tool", None):
            print("Error: interactive absorb (--interactive/--tool) is not yet supported", file=sys.stderr)
            return 2
        source = _resolve_one(repo, settings, args.from_)
        dest_expr = getattr(args, "into", None)
        paths = getattr(args, "filesets", None) or None
        if paths == []:
            paths = None
        tx = repo.start_transaction(settings)
        stats = tx.absorb(settings, source, destinations=dest_expr, paths=paths)
        _finish(tx, f"absorb from {source.id.hex()[:12]} into {dest_expr or 'mutable()'}", settings, ws, repo)
        # Minimal feedback like jj (number of destinations)
        if stats.source is None:
            # Fully absorbed and abandoned (empty description)
            pass
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0

def fix(args) -> int:
    """`jj fix [-s REVSET] [--include-unchanged-files] [FILESETS]` — run formatters."""
    try:
        settings, ws, repo = _load(args)
        revset = getattr(args, "source", None)
        include_unchanged = bool(getattr(args, "include_unchanged", False))
        paths = getattr(args, "filesets", None) or None
        if paths == []:
            paths = None

        tx = repo.start_transaction(settings)
        files = tx.fix_enumerate(settings, revset=revset, paths=paths, include_unchanged_files=include_unchanged)
        if not files:
            # No files to fix — matches real jj's quiet no-op.
            return 0

        # Discover fix tools from config, sorted lexicographically like jj does.
        try:
            tool_names = sorted(settings.list_fix_tools())
        except AttributeError:
            # Fallback for old bindings without list_fix_tools.
            tool_names = []
        if not tool_names:
            # No tools configured — nothing to do.
            return 0

        # Build mapping of tool -> (command, patterns, enabled)
        tools = []
        for name in tool_names:
            enabled = settings.get_bool(f"fix.tools.{name}.enabled")
            if enabled is False:
                continue
            command = settings.get_string_list(f"fix.tools.{name}.command")
            if not command:
                continue
            patterns = settings.get_string_list(f"fix.tools.{name}.patterns") or []
            tools.append((name, command, patterns))

        if not tools:
            return 0

        workspace_root = ws.workspace_root
        fixes: dict[str, bytes] = {}
        for f in files:
            content = f.content
            cur = content
            for _name, command, patterns in tools:
                # Check if any pattern matches this file's path
                if patterns and not any(_fix_pattern_matches(p, f.path) for p in patterns):
                    continue
                # Substitute $path and $root in command args
                cmd = [arg.replace("$path", f.path).replace("$root", workspace_root) for arg in command]
                try:
                    proc = subprocess.run(cmd, input=cur, capture_output=True, check=False)
                except OSError as e:
                    raise CommandError(f"fix tool {_name} failed to start: {e}")
                if proc.returncode != 0:
                    raise CommandError(
                        f"fix tool {_name} exited with {proc.returncode}: "
                        f"{proc.stderr.decode(errors='replace')[:200]}"
                    )
                cur = proc.stdout
            if cur != content:
                fixes[f.key] = cur

        if not fixes:
            return 0

        summary = tx.fix_apply(settings, fixes, revset=revset, paths=paths, include_unchanged_files=include_unchanged)
        _finish(tx, f"fix {revset or 'reachable(@, mutable())'}", settings, ws, repo)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0

def revert(args) -> int:
    """`jj revert -r REV --onto REV` — apply reverse of revisions."""
    try:
        settings, ws, repo = _load(args)
        # Resolve revisions to revert (union of all -r)
        rev_args = getattr(args, "revisions", None) or []
        if not rev_args:
            print("Error: --revision is required", file=sys.stderr)
            return 2
        # _resolve_all expects list of revsets; each -r is a revset string
        targets = _resolve_all(repo, settings, rev_args)
        if not targets:
            print("No revisions to revert.")
            return 0
        # Sort in reverse topological order (children before parents) like real jj.
        # The revset engine already returns topological order (children before parents
        # for log_graph, but revset order is not guaranteed). For the simple case
        # of a linear chain, the order returned by _resolve_all (union) will be
        # the order of the input revsets, not topological. We can sort by
        # using the repo's log_graph or by checking parent relationships.
        # Simplest: sort by commit date or just reverse the list if it's linear.
        # For now, sort by trying to order so that descendants come before ancestors
        # by checking if one is ancestor of another via revset.
        # If we can't determine, just reverse the input order which matches
        # jj's "reverse topological" for the common case of passing parents first.
        # We can attempt to use the repo's revset to get topological order:
        try:
            # Build a revset that includes all targets and get their order
            union = " | ".join(f"({r})" for r in rev_args)
            ordered = repo.revset(settings, union)
            # ordered is already topological (children before parents) per log_graph?
            # Reverse to get reverse topological (parents before children) then reverse again?
            # Actually we want reverse topological for revert: children first, so that
            # each revert is applied on top of the previous. That is the same as
            # topological order where children are first.
            # So we can just use ordered as is, but ensure it matches targets set.
            id_to_commit = {c.id.hex(): c for c in targets}
            # Filter ordered to only those in targets, preserving ordered's sequence
            ordered_targets = [id_to_commit[c.id.hex()] for c in ordered if c.id.hex() in id_to_commit]
            # If ordered_targets has same length, use it; else fallback to original
            if len(ordered_targets) == len(targets):
                targets = ordered_targets
        except Exception:
            pass

        # Determine destination: --onto / --destination / --insert-after / --insert-before
        ontos = getattr(args, "ontos", None) or []
        dests = getattr(args, "destinations", None) or []
        afters = getattr(args, "insert_afters", None) or []
        befores = getattr(args, "insert_befores", None) or []
        dest_mode_count = sum(1 for x in (ontos, dests, afters, befores) if x)
        if dest_mode_count == 0:
            print("Error: --onto, --insert-after or --insert-before is required", file=sys.stderr)
            return 2
        if dest_mode_count > 1:
            print("Error: specify only one of --onto, --insert-after, --insert-before", file=sys.stderr)
            return 2

        new_parent_ids: list[pyjj.CommitId] = []
        new_child_ids: list[pyjj.CommitId] = []
        if ontos or dests:
            plain = list(ontos) + list(dests)
            dest_commits = _resolve_in_arg_order(repo, settings, plain)
            if not dest_commits:
                print("Error: no destination revisions", file=sys.stderr)
                return 1
            new_parent_ids = [c.id for c in dest_commits]
            new_child_ids = []
        elif afters:
            after_commits = _resolve_in_arg_order(repo, settings, afters)
            new_parent_ids = [c.id for c in after_commits]
            # Children of after: those whose parent is after
            try:
                children_expr = " | ".join(f"children({a})" for a in afters)
                children = repo.revset(settings, children_expr)
                new_child_ids = [c.id for c in children]
            except pyjj.JjError:
                new_child_ids = []
        else:  # befores
            before_commits = _resolve_in_arg_order(repo, settings, befores)
            new_child_ids = [c.id for c in before_commits]
            parents_set: dict[str, pyjj.Commit] = {}
            for c in before_commits:
                for pid in c.parent_ids:
                    try:
                        p = repo.get_commit(pid)
                        parents_set[pid.hex()] = p
                    except pyjj.JjError:
                        pass
            new_parent_ids = [c.id for c in parents_set.values()]
            if not new_parent_ids:
                # If before has no parents (root), use empty? But revert requires at least one parent.
                print("Error: insert-before destination has no parents", file=sys.stderr)
                return 1

        tx = repo.start_transaction(settings)
        # Chain reverts in the determined order (which should be reverse topological,
        # i.e. children first). The first revert is onto new_parent_ids, subsequent
        # ones are onto the previous revert's commit.
        current_parents = new_parent_ids
        last_revert = None
        for commit in targets:
            builder = tx.revert_commit(commit, current_parents)
            # Generate description like jj's default templates.revert_description:
            #   'Revert "' ++ description.first_line() ++ '"\n\nThis reverts commit ' ++ commit_id ++ '.\n'
            first_line = commit.description.splitlines()[0] if commit.description else ""
            desc = f'Revert "{first_line}"\n\nThis reverts commit {commit.id.hex()}.\n'
            builder.set_description(desc)
            last_revert = builder.write(repo)
            current_parents = [last_revert.id]
            # For insert-after/before, the new_child_ids should be rebased onto the final revert chain.
            # We will handle that after the loop by rebasing original children.

        if last_revert is None:
            print("No revisions to revert.")
            return 0

        # Handle insert-after / insert-before by rebasing the original children onto the final revert
        if new_child_ids:
            for child_id in new_child_ids:
                try:
                    child = repo.get_commit(child_id)
                    # Rewrite child to have last_revert as parent (keeping other parents if merge)
                    # For simplicity, replace the old parent (the after/before target) with last_revert
                    # If child had multiple parents, keep them but replace the relevant one.
                    # For now, just set parents to [last_revert.id] if single parent, else keep other parents
                    if len(child.parent_ids) == 1:
                        new_parents = [last_revert.id]
                    else:
                        # For merges, replace any parent that was in new_parent_ids or new_child_ids?
                        # Simplify: keep all parents but ensure last_revert is included
                        existing = [pid for pid in child.parent_ids if pid.hex() not in {c.hex() for c in new_parent_ids + new_child_ids}]
                        new_parents = [last_revert.id] + existing
                    b = tx.rewrite_commit(settings, child)
                    b.set_parents(new_parents)
                    b.write(repo)
                except pyjj.JjError:
                    continue

        # If the source was @ and we created a new commit, the working copy should follow?
        # _finish will handle rebase_descendants and checkout.
        _finish(tx, f"revert {rev_args[0] if rev_args else ''}", settings, ws, repo)
        return 0
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

