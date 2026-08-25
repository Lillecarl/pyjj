#!/usr/bin/env python3
"""One pyjj operation per process, driven by parity_harness.RepoPair.

A fresh interpreter per operation mirrors the `jj` CLI's own
process-per-command model, which is what keeps the seeded RNG streams of
the two sides aligned (see harness module docs). The parent passes the
pinned environment; this script only translates one JSON operation into
pyjj calls.

The settings are built with load_config=True (not the hermetic bare
defaults the rest of the pyjj suite uses) because env-var overrides --
which carry every determinism pin -- only apply when config loading runs.
The scratch HOME the parent points at makes that load empty and stable.
"""

from __future__ import annotations

import json
import sys

import pyjj


def wc_commit_id(repo) -> str:
    view = repo.view()
    names = list(view.keys())
    assert len(names) == 1, f"expected exactly one workspace, got {names}"
    return view[names[0]]


def complete_newline(s: str) -> str:
    """The jj CLI's text_util::complete_newline: append exactly one
    trailing newline to a non-empty description that lacks one. The
    binding layer stores descriptions verbatim (like jj_lib); this is the
    CLI frontend's normalization, applied on every -m/--stdin/editor path."""
    if s and not s.endswith("\n"):
        return s + "\n"
    return s


def main() -> int:
    repo_path, raw_op = sys.argv[1], json.loads(sys.argv[2])
    settings = pyjj.UserSettings(load_config=True)
    op = raw_op["op"]

    if op == "init":
        pyjj.Workspace.init_internal_git(settings, repo_path)
        return 0

    ws = pyjj.Workspace.load(settings, repo_path)
    repo = ws.load_at_head()

    if op == "snapshot":
        ws.snapshot(settings)
        return 0

    tx = repo.start_transaction(settings)

    # The real CLI's `jj abandon` deletes bookmarks on the abandoned
    # commits by default (--retain-bookmarks moves them instead); every
    # other rewrite keeps jj_lib's move-to-successors behavior.
    delete_abandoned_bookmarks = op == "abandon"

    if op == "describe":
        commit = repo.get_commit(pyjj.CommitId(wc_commit_id(repo)))
        new = tx.rewrite_commit(settings, commit).set_description(
            complete_newline(raw_op["message"])
        ).write(repo)
        tx.set_wc_commit(ws.workspace_name, new.id)
    elif op == "new":
        # Explicit parents replace the default (the working copy), never
        # extend it -- matching `jj new <rev>`.
        requested = raw_op.get("parents", [])
        if requested:
            parents = [repo.resolve_single(settings, expr).id.hex() for expr in requested]
        else:
            parents = [wc_commit_id(repo)]
        child = (
            tx.new_commit(settings, [pyjj.CommitId(p) for p in parents])
            .set_description(complete_newline(raw_op["message"]))
            .write(repo)
        )
        tx.set_wc_commit(ws.workspace_name, child.id)
    elif op == "bookmark":
        target = raw_op.get("target")
        cid = (
            repo.resolve_single(settings, target).id
            if target
            else pyjj.CommitId(wc_commit_id(repo))
        )
        tx.set_bookmark(raw_op["name"], cid)
    elif op == "squash":
        source = repo.resolve_single(settings, raw_op["revision"])
        dest = repo.get_commit(source.parent_ids[0])
        builder = tx.squash(source, dest)
        assert builder is not None, "squash matched nothing"
        builder.write(repo)
    elif op == "rebase":
        # Mirror `jj rebase -r <rev> -d <dest>` through move_commits -- the
        # same machinery the real CLI composes. Plain rebase() +
        # rebase_descendants() would drag descendants to the new location;
        # real -r instead grafts them onto the moved commit's original
        # parents.
        commit = repo.resolve_single(settings, raw_op["revision"])
        dest = repo.resolve_single(settings, raw_op["destination"])
        tx.move_commits([commit.id], [], [dest.id], [])
    elif op == "abandon":
        tx.abandon_commit(repo.resolve_single(settings, raw_op["revision"]))
    elif op == "duplicate":
        tx.duplicate([repo.resolve_single(settings, raw_op["revision"])])
    else:
        raise ValueError(f"unknown op: {op}")

    num_rebased = tx.rebase_descendants(delete_abandoned_bookmarks)
    assert num_rebased >= 0
    new_repo = tx.commit(f"parity: {op}")

    # Mirror the CLI's transaction-finish behavior: when a rewrite moved
    # the working-copy commit (e.g. an abandon or rebase rebased it), the
    # on-disk working copy must follow. Without this, the repo reads back
    # as "stale" to a later jj invocation -- exactly what real jj avoids
    # by checking out at transaction finish.
    fresh_ws = pyjj.Workspace.load(settings, repo_path)
    fresh_repo = fresh_ws.load_at_head()
    wc_commit = fresh_repo.get_commit(pyjj.CommitId(wc_commit_id(fresh_repo)))
    fresh_ws.check_out(new_repo, wc_commit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
