"""Repo/app construction helpers shared between pytest fixtures
(conftest.py) and ad hoc tooling (pyjjui/tools/screenshot.py), so there's a
single source of truth for "what does a seeded demo repo look like" instead
of copy-pasting this transaction-building code into every script that needs
a throwaway repo.
"""

import pyjj

FIXED_SIGNATURE = pyjj.Signature("Test User", "test.user@example.com", pyjj.Timestamp(0, 0))


def write_config(path):
    """A hermetic jj config: fixed user identity and a fixed
    `debug.randomness-seed` (so change-id prefixes are stable across runs --
    load-bearing for snapshot tests, see `seed_repo`'s docs on why commit
    ids need pinning too).
    """
    path.write_text(
        'user.name = "Test User"\n'
        'user.email = "test.user@example.com"\n'
        "debug.randomness-seed = 42\n"
    )


def seed_repo(workspace, settings):
    """Two described commits (`A` then `B`, `B` checked out) on top of the
    fresh workspace's initial empty working-copy commit. Author/committer
    timestamps are pinned everywhere (not just `debug.randomness-seed`'s
    change-ids) so commit ids -- shown in full in the preview pane -- are
    stable too: a commit id is a content hash that includes its timestamp,
    and the *root* commit's timestamp (which `Workspace.init_internal_git`
    sets to real wall-clock time) cascades into every descendant's commit
    id unless it's pinned first.
    """
    repo = workspace.load_at_head()
    root = repo.resolve_single(settings, "@")

    tx = repo.start_transaction(settings)
    builder = tx.rewrite_commit(settings, root)
    builder.set_author(FIXED_SIGNATURE)
    builder.set_committer(FIXED_SIGNATURE)
    root = builder.write(repo)
    tx.set_wc_commit(workspace.workspace_name, root.id)
    tx.rebase_descendants()
    repo = tx.commit("pin root commit timestamp")
    workspace.check_out(repo, root)

    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [root.id])
    builder.set_description("A")
    builder.set_author(FIXED_SIGNATURE)
    builder.set_committer(FIXED_SIGNATURE)
    a = builder.write(repo)
    tx.edit(workspace.workspace_name, a)
    tx.rebase_descendants()
    repo = tx.commit("new A")
    workspace.check_out(repo, a)

    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [a.id])
    builder.set_description("B")
    builder.set_author(FIXED_SIGNATURE)
    builder.set_committer(FIXED_SIGNATURE)
    b = builder.write(repo)
    tx.edit(workspace.workspace_name, b)
    tx.rebase_descendants()
    repo = tx.commit("new B")
    workspace.check_out(repo, b)

    return repo


def new_child(workspace, repo, settings, parent, description):
    """A single fixed-timestamp `jj new` step, for building larger demo
    graphs (e.g. branches/merges) than `seed_repo`'s fixed A/B history.
    """
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [parent.id])
    builder.set_description(description)
    builder.set_author(FIXED_SIGNATURE)
    builder.set_committer(FIXED_SIGNATURE)
    child = builder.write(repo)
    tx.edit(workspace.workspace_name, child)
    tx.rebase_descendants()
    repo = tx.commit(description)
    workspace.check_out(repo, child)
    return repo, child
