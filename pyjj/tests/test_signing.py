"""Tests for commit signing: CommitBuilder.set_sign_behavior()/Commit.is_signed.

Uses jj's real `ssh` signing backend (no GPG required) with a throwaway
ed25519 keypair generated via `ssh-keygen`, wired up through `JJ_CONFIG` --
the same mechanism `pyjj.UserSettings(load_config=True)` uses to see real
jj config in production. Skipped if `ssh-keygen` isn't on PATH.
"""

import shutil
import subprocess

import pytest

import pyjj

pytestmark = pytest.mark.skipif(
    shutil.which("ssh-keygen") is None, reason="ssh-keygen not available"
)


@pytest.fixture
def ssh_signing_settings(tmp_path, monkeypatch):
    """`UserSettings(load_config=True)` configured to sign with a fresh,
    throwaway SSH key -- default behavior "own" (sign own commits).
    """
    key_path = tmp_path / "key"
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_path), "-C", "pyjj-test"],
        check=True,
        capture_output=True,
    )
    pub_key = (tmp_path / "key.pub").read_text()

    allowed_signers = tmp_path / "allowed_signers"
    allowed_signers.write_text(f"pyjj-test {pub_key}")

    config_file = tmp_path / "config.toml"
    config_file.write_text(f"""
[user]
name = "Test User"
email = "test@example.com"

[signing]
backend = "ssh"
key = "{key_path}"
behavior = "own"

[signing.backends.ssh]
allowed-signers = "{allowed_signers}"
""")
    monkeypatch.setenv("JJ_CONFIG", str(config_file))
    monkeypatch.delenv("JJ_USER", raising=False)
    monkeypatch.delenv("JJ_EMAIL", raising=False)
    return pyjj.UserSettings()


@pytest.fixture
def ssh_signing_workspace_and_repo(tmp_path, ssh_signing_settings):
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    return pyjj.Workspace.init_internal_git(ssh_signing_settings, str(workspace_root))


def test_own_commits_signed_by_default(ssh_signing_settings, ssh_signing_workspace_and_repo):
    _ws, repo = ssh_signing_workspace_and_repo
    view = repo.view()
    wc = repo.get_commit(pyjj.CommitId(next(iter(view.values()))))

    # Created by this same settings.user, so behavior "own" signs it.
    assert wc.is_signed is True


def test_set_sign_behavior_force_signs_commit(ssh_signing_settings, ssh_signing_workspace_and_repo):
    _ws, repo = ssh_signing_workspace_and_repo
    view = repo.view()
    wc = repo.get_commit(pyjj.CommitId(next(iter(view.values()))))

    tx = repo.start_transaction(ssh_signing_settings)
    builder = tx.new_commit(ssh_signing_settings, [wc.id])
    builder.set_description("signed commit")
    builder.set_sign_behavior("force")
    commit = builder.write(repo)
    tx.commit("add signed commit")

    assert commit.is_signed is True


def test_set_sign_behavior_drop_leaves_commit_unsigned(ssh_signing_settings, ssh_signing_workspace_and_repo):
    _ws, repo = ssh_signing_workspace_and_repo
    view = repo.view()
    wc = repo.get_commit(pyjj.CommitId(next(iter(view.values()))))

    tx = repo.start_transaction(ssh_signing_settings)
    builder = tx.new_commit(ssh_signing_settings, [wc.id])
    builder.set_description("unsigned commit")
    builder.set_sign_behavior("drop")
    commit = builder.write(repo)
    tx.commit("add unsigned commit")

    assert commit.is_signed is False


def test_verification_reports_good_status_key_and_display(
    ssh_signing_settings, ssh_signing_workspace_and_repo
):
    _ws, repo = ssh_signing_workspace_and_repo
    view = repo.view()
    wc = repo.get_commit(pyjj.CommitId(next(iter(view.values()))))

    v = wc.verification
    assert v is not None
    assert v.status == "good"
    assert v.key is not None
    assert v.display == "pyjj-test"


def test_verification_is_none_when_unsigned(workspace, repo, settings, wc_commit):
    # `settings`/`repo` (the shared fixtures) have no signing backend
    # configured -- verification() must return None, not raise or return a
    # dummy "unknown" result, for a commit that was never signed at all.
    assert wc_commit.is_signed is False
    assert wc_commit.verification is None


def test_sign_behavior_keep_preserves_signature_on_rewrite(
    ssh_signing_settings, ssh_signing_workspace_and_repo
):
    _ws, repo = ssh_signing_workspace_and_repo
    view = repo.view()
    wc = repo.get_commit(pyjj.CommitId(next(iter(view.values()))))
    assert wc.is_signed is True

    tx = repo.start_transaction(ssh_signing_settings)
    builder = tx.rewrite_commit(ssh_signing_settings, wc)
    builder.set_description("rewritten, default (keep) behavior")
    rewritten = builder.write(repo)
    tx.rebase_descendants()
    repo2 = tx.commit("rewrite keeping signature")

    rewritten = repo2.get_commit(rewritten.id)
    assert rewritten.is_signed is True
    assert rewritten.verification.status == "good"


def test_sign_behavior_drop_clears_signature_on_rewrite(
    ssh_signing_settings, ssh_signing_workspace_and_repo
):
    _ws, repo = ssh_signing_workspace_and_repo
    view = repo.view()
    wc = repo.get_commit(pyjj.CommitId(next(iter(view.values()))))
    assert wc.is_signed is True

    tx = repo.start_transaction(ssh_signing_settings)
    builder = tx.rewrite_commit(ssh_signing_settings, wc)
    builder.set_description("rewritten, explicit drop")
    builder.set_sign_behavior("drop")
    rewritten = builder.write(repo)
    tx.rebase_descendants()
    repo2 = tx.commit("rewrite dropping signature")

    rewritten = repo2.get_commit(rewritten.id)
    assert rewritten.is_signed is False
    assert rewritten.verification is None


def test_set_sign_behavior_rejects_unknown_value(workspace, repo, settings, wc_commit):
    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [wc_commit.id])
    with pytest.raises(pyjj.JjError):
        builder.set_sign_behavior("not-a-real-behavior")


def test_no_signing_backend_configured_leaves_commit_unsigned(workspace, repo, settings, wc_commit):
    # `settings` (the shared fixture) uses load_config=False -- no signing
    # backend configured, so even the default "own"-ish behavior can't sign.
    assert wc_commit.is_signed is False
