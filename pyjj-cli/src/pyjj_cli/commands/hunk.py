"""pyjj-cli commands: hunk."""
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

def _resolve_message_arg(msg: str | None, use_stdin: bool) -> str | None:
    """Resolve commit message: '-' or --stdin reads from stdin (supports long messages without quoting)."""
    if use_stdin:
        text = sys.stdin.read()
        if not text.strip():
            return None
        return text
    if msg == "-":
        text = sys.stdin.read()
        if not text:
            return None
        return text
    return msg

def hunk_split(args) -> int:
    """`pyjj hunk split [-r REV] <spec> <message>` — split with hunk/line spec."""
    try:
        settings, ws, repo = _load(args)
        # Handle spec/message normalization like jj-hunk: spec can be '-' for stdin, --spec, or --spec-file
        spec_str = getattr(args, "spec", None)
        spec_flag = getattr(args, "spec_flag", None)
        spec_file = getattr(args, "spec_file", None)
        message = getattr(args, "message", None)
        use_stdin = bool(getattr(args, "stdin", False))
        # --spec flag takes precedence over positional spec
        if spec_flag is not None:
            if spec_str is not None or spec_file is not None:
                print("Error: hunk split: use either --spec, --spec-file orpositional <spec>, not both", file=sys.stderr)
                return 2
            spec_str = spec_flag
        # Normalize like jj-hunk's normalize_spec_message
        if spec_file and message is None:
            # When --spec-file is used, the positional spec is actually the message
            message = spec_str
            spec_str = None
        # Resolve message from stdin if requested
        message = _resolve_message_arg(message, use_stdin)
        if message is None:
            print("Error: hunk split requires a commit message (use '-' or --stdin for stdin)", file=sys.stderr)
            return 2
        if spec_file:
            if spec_str is not None:
                print("Error: hunk split: omit <spec> when using --spec-file", file=sys.stderr)
                return 2
            spec = hunk_mod.load_spec_from_input(None, spec_file)
        else:
            if spec_str is None:
                print("Error: hunk split requires a spec (or use --spec/--spec-file)", file=sys.stderr)
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
        spec_flag = getattr(args, "spec_flag", None)
        spec_file = getattr(args, "spec_file", None)
        message = getattr(args, "message", None)
        use_stdin = bool(getattr(args, "stdin", False))
        if spec_flag is not None:
            if spec_str is not None or spec_file is not None:
                print("Error: hunk commit: use either --spec, --spec-file or positional <spec>, not both", file=sys.stderr)
                return 2
            spec_str = spec_flag
        if spec_file and message is None:
            message = spec_str
            spec_str = None
        message = _resolve_message_arg(message, use_stdin)
        if message is None:
            print("Error: hunk commit requires a commit message (use '-' or --stdin for stdin)", file=sys.stderr)
            return 2
        if spec_file:
            if spec_str is not None:
                print("Error: hunk commit: omit <spec> when using --spec-file", file=sys.stderr)
                return 2
            spec = hunk_mod.load_spec_from_input(None, spec_file)
        else:
            if spec_str is None:
                print("Error: hunk commit requires a spec (or use --spec/--spec-file)", file=sys.stderr)
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
        spec_flag = getattr(args, "spec_flag", None)
        spec_file = getattr(args, "spec_file", None)
        if spec_flag is not None:
            if spec_str is not None or spec_file is not None:
                print("Error: hunk squash: use either --spec, --spec-file or positional <spec>, not both", file=sys.stderr)
                return 2
            spec_str = spec_flag
        if spec_file:
            if spec_str is not None:
                print("Error: hunk squash: omit <spec> when using --spec-file", file=sys.stderr)
                return 2
            spec = hunk_mod.load_spec_from_input(None, spec_file)
        else:
            if spec_str is None:
                print("Error: hunk squash requires a spec (or use --spec/--spec-file)", file=sys.stderr)
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

