"""Tests for CommitBuilder's timestamp behavior on rewrite, mirroring
lib/tests/test_commit_builder.rs's test_rewrite_resets_author_timestamp.

Important gotcha this pins down: the `settings` argument to
`Transaction.rewrite_commit()`/`.new_commit()`/`start_transaction()` does
*not* control the author/committer signature of the resulting commit --
that comes from whatever settings the underlying `ReadonlyRepo` was
loaded/created with (`jj_lib::repo::MutableRepo::rewrite_commit` reads
`self.base_repo.settings()`, fixed at load time, not the settings handed to
any of these calls). To change the effective commit-authoring identity or
`debug.commit-timestamp` mid-session, reload the workspace with new
settings (`pyjj.Workspace.load(new_settings, path)` + `.load_at_head()`)
rather than just passing different settings into `start_transaction()`.
"""

import pyjj


def _settings_at(tmp_path, monkeypatch, timestamp, index):
    config_file = tmp_path / f"config-{index}.toml"
    config_file.write_text(f"""
[user]
name = "Test User"
email = "test@example.com"

[debug]
commit-timestamp = "{timestamp}"
""")
    monkeypatch.setenv("JJ_CONFIG", str(config_file))
    monkeypatch.delenv("JJ_USER", raising=False)
    monkeypatch.delenv("JJ_EMAIL", raising=False)
    return pyjj.UserSettings()


def test_rewrite_resets_author_timestamp_only_while_discardable(tmp_path, monkeypatch):
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()

    s1 = _settings_at(tmp_path, monkeypatch, "2001-02-03T04:05:06+07:00", 1)
    ws, repo = pyjj.Workspace.init_internal_git(s1, str(workspace_root))

    # An empty, undescribed ("discardable") commit off the root.
    tx = repo.start_transaction(s1)
    seed = tx.new_commit(s1, [pyjj.CommitId("0" * 40)])
    initial = seed.write(repo)
    tx.rebase_descendants()
    repo = tx.commit("initial")
    assert initial.author.timestamp == initial.committer.timestamp

    # Reload bound to s2 -- changing settings requires a fresh load, not
    # just a different `start_transaction()` argument.
    s2 = _settings_at(tmp_path, monkeypatch, "2002-03-04T05:06:07+08:00", 2)
    ws2 = pyjj.Workspace.load(s2, str(workspace_root))
    repo2 = ws2.load_at_head()
    initial = repo2.get_commit(initial.id)
    tx = repo2.start_transaction(s2)
    builder = tx.rewrite_commit(s2, initial)
    builder.set_description("No longer discardable")
    rewritten1 = builder.write(repo2)
    tx.rebase_descendants()
    repo2 = tx.commit("describe")

    # `initial` was discardable, so rewriting it bumps *both* timestamps to
    # "now" (s2), not just the committer's.
    assert rewritten1.author.timestamp == rewritten1.committer.timestamp
    assert rewritten1.author.timestamp != initial.author.timestamp

    # Reload bound to s3 and rewrite the now-described (non-discardable)
    # commit again.
    s3 = _settings_at(tmp_path, monkeypatch, "2003-04-05T06:07:08+09:00", 3)
    ws3 = pyjj.Workspace.load(s3, str(workspace_root))
    repo3 = ws3.load_at_head()
    rewritten1 = repo3.get_commit(rewritten1.id)
    tx = repo3.start_transaction(s3)
    builder = tx.rewrite_commit(s3, rewritten1)
    builder.set_description("New description")
    rewritten2 = builder.write(repo3)
    tx.rebase_descendants()
    tx.commit("re-describe")

    # `rewritten1` was no longer discardable (had a description), so only
    # the committer timestamp advances -- the author timestamp is frozen.
    assert rewritten2.author.timestamp == rewritten1.author.timestamp
    assert rewritten2.committer.timestamp != rewritten2.author.timestamp
    assert rewritten2.committer.timestamp != rewritten1.committer.timestamp
