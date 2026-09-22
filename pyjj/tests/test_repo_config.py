"""Repo and workspace config reach the revset loader, as they do in jj.

jj keeps these behind an id: the repository holds a hex id in
`.jj/repo/config-id`, and the config itself lives under the *user's*
config directory. Loading them needs a workspace to read the id from,
which is why `UserSettings.for_repo` exists beside the constructor.

The test that matters is `immutable_heads()`. Set with `config set
--repo` it had no effect here, so pyjj-cli rewrote commits real jj
refuses -- an agent could rewrite published history believing it was
protected.
"""

import os
import shutil
import subprocess
import sys

import pytest


def _run(root, *args, home, check=False):
    env = os.environ.copy()
    env.update(JJ_USER="tester", JJ_EMAIL="tester@example.com",
               NO_COLOR="1", XDG_CONFIG_HOME=str(home))
    # A config directory of its own, so the machine's real jj config
    # cannot decide the answer either way.
    result = subprocess.run(
        [sys.executable, "-m", "pyjj_cli", "-R", str(root), *args],
        capture_output=True, text=True, env=env,
    )
    if check:
        assert result.returncode == 0, result.stderr
    return result


@pytest.fixture
def repo_with_topics(tmp_path):
    """`main`, two topics off it, and a commit keeping `b` alive."""
    root = tmp_path / "repo"
    root.mkdir()
    home = tmp_path / "config"
    home.mkdir()
    env = os.environ.copy()
    env.update(JJ_USER="tester", JJ_EMAIL="tester@example.com",
               XDG_CONFIG_HOME=str(home))
    subprocess.run([sys.executable, "-m", "pyjj_cli", "git", "init"],
                   cwd=str(root), env=env, capture_output=True, check=True)
    (root / "base.txt").write_text("base\n")
    _run(root, "commit", "-m", "base", home=home, check=True)
    _run(root, "bookmark", "create", "main", "-r", "@-", home=home, check=True)
    for topic in ("a", "b"):
        _run(root, "new", "main", "-m", f"topic {topic}", home=home,
             check=True)
        (root / f"{topic}.txt").write_text(topic + "\n")
        _run(root, "bookmark", "create", topic, "-r", "@", home=home,
             check=True)
    _run(root, "new", "b", "-m", "keepalive", home=home, check=True)
    return root, home


def test_for_repo_loads_the_layer_the_constructor_skips(repo_with_topics,
                                                        monkeypatch):
    """The binding half, isolated from the CLI: the plain constructor
    sees only the root commit as immutable, `for_repo` sees the set the
    repo config names."""
    import pyjj

    root, home = repo_with_topics
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    _run(root, "config", "set", "--repo",
         'revset-aliases."immutable_heads()"', "a", home=home, check=True)

    plain = pyjj.UserSettings()
    workspace = pyjj.Workspace.load(plain, str(root))
    repo = workspace.load_at_head()
    full = pyjj.UserSettings.for_repo(workspace.repo_path,
                                      workspace.workspace_root)

    assert len(repo.revset(plain, "immutable()")) == 1, "only root()"
    assert len(repo.revset(full, "immutable()")) > 1, (
        "the repo layer did not reach the revset loader")


def test_a_written_config_directory_carries_its_metadata(repo_with_topics):
    """The half that made jj ignore pyjj's config.

    A directory holding only `config.toml` is one jj treats as absent,
    so every value `config set --repo` wrote was invisible to `jj`. The
    metadata beside it records which repository the directory belongs
    to, and writing it is what makes the two tools agree.
    """
    from pathlib import Path

    root, home = repo_with_topics
    _run(root, "config", "set", "--repo", "user.name", "written-by-pyjj",
         home=home, check=True)

    dirs = list((Path(home) / "jj" / "repos").iterdir())
    assert len(dirs) == 1, dirs
    assert (dirs[0] / "config.toml").exists()
    assert (dirs[0] / "metadata.binpb").exists(), (
        "without this jj treats the directory as absent")

    import pyjj
    recorded = pyjj.repo_config_repo_path(str(dirs[0]))
    assert recorded == str(root / ".jj" / "repo")


def test_without_the_setting_a_rewrite_goes_through(repo_with_topics):
    """The control: nothing is immutable, so `a` moves."""
    root, home = repo_with_topics
    result = _run(root, "rebase", "-r", "a", "-d", "b", home=home)
    assert result.returncode == 0, result.stderr


def test_config_set_repo_makes_immutable_heads_bite(repo_with_topics):
    root, home = repo_with_topics
    _run(root, "config", "set", "--repo",
         'revset-aliases."immutable_heads()"', "a", home=home, check=True)

    listed = _run(root, "config", "list", "--repo", home=home, check=True)
    assert 'immutable_heads()' in listed.stdout

    result = _run(root, "rebase", "-r", "a", "-d", "b", home=home)
    assert result.returncode == 1
    assert "immutable" in result.stderr


def test_jj_reads_what_pyjj_wrote_and_the_other_way(repo_with_topics):
    """The divergence ran both ways, and this is the direction that
    was easy to miss: jj ignored config pyjj had written."""
    jj = os.environ.get("PYJJ_PARITY_JJ") or shutil.which("jj")
    if not jj:
        pytest.skip("no jj binary on PATH")
    root, home = repo_with_topics

    def run_jj(*args):
        env = os.environ.copy()
        env.update(JJ_USER="tester", JJ_EMAIL="tester@example.com",
                   XDG_CONFIG_HOME=str(home))
        return subprocess.run([jj, "--no-pager", "-R", str(root), *args],
                              capture_output=True, text=True, env=env)

    _run(root, "config", "set", "--repo", "aliases.from-pyjj", '["log"]',
         home=home, check=True)
    assert "from-pyjj" in run_jj("config", "list", "--repo").stdout

    assert run_jj("config", "set", "--repo", "aliases.from-jj",
                  '["status"]').returncode == 0
    listed = _run(root, "config", "list", "--repo", home=home, check=True)
    assert "from-jj" in listed.stdout
    assert "from-pyjj" in listed.stdout


def test_config_get_reads_the_repo_layer(repo_with_topics):
    """`config get` built its own settings and so missed the repo
    layer: it reported a key unset that `jj config get` printed."""
    root, home = repo_with_topics
    _run(root, "config", "set", "--repo", "ui.default-command", "status",
         home=home, check=True)

    result = _run(root, "config", "get", "ui.default-command", home=home)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "status"


def test_util_snapshot_honours_a_repo_level_limit(repo_with_topics):
    """`snapshot.max-new-file-size` set per repo has to reach the
    snapshot, which built its settings without the repo layer and so
    took a file the limit forbids.

    Asserted on the tree rather than the message: pyjj does not report
    refused files the way jj does ("Refused to snapshot some files"),
    which is a separate divergence in the reporting, not in whether the
    limit applies.
    """
    root, home = repo_with_topics
    _run(root, "config", "set", "--repo", "snapshot.max-new-file-size", "10",
         home=home, check=True)
    (root / "big.txt").write_text("x" * 200)

    result = _run(root, "util", "snapshot", home=home)
    assert result.returncode == 0, result.stderr
    listed = _run(root, "file", "list", home=home, check=True)
    assert "big.txt" not in listed.stdout, (
        "the repo-level size limit did not reach the snapshot")


def test_a_file_under_the_limit_is_still_snapshotted(repo_with_topics):
    """The control: the limit refuses one file, not the snapshot."""
    root, home = repo_with_topics
    _run(root, "config", "set", "--repo", "snapshot.max-new-file-size", "1000",
         home=home, check=True)
    (root / "small.txt").write_text("x" * 20)

    _run(root, "util", "snapshot", home=home, check=True)
    listed = _run(root, "file", "list", home=home, check=True)
    assert "small.txt" in listed.stdout


def test_the_repo_layer_does_not_leak_between_repositories(tmp_path):
    """The id names a directory under the user's config home, and the
    metadata there records which repository it belongs to. A second
    repository must not pick up the first one's config."""
    home = tmp_path / "config"
    home.mkdir()
    roots = []
    for name in ("one", "two"):
        root = tmp_path / name
        root.mkdir()
        env = os.environ.copy()
        env.update(JJ_USER="tester", JJ_EMAIL="tester@example.com",
                   XDG_CONFIG_HOME=str(home))
        subprocess.run([sys.executable, "-m", "pyjj_cli", "git", "init"],
                       cwd=str(root), env=env, capture_output=True, check=True)
        (root / "f.txt").write_text(name + "\n")
        _run(root, "commit", "-m", name, home=home, check=True)
        roots.append(root)

    # Not `user.name`: JJ_USER is an env override, and an env override
    # outranks the repo layer in jj too, so it would hide the answer.
    _run(roots[0], "config", "set", "--repo", "aliases.only-in-one",
         '["log"]', home=home, check=True)

    first = _run(roots[0], "config", "list", "--repo", home=home, check=True)
    assert "only-in-one" in first.stdout

    second = _run(roots[1], "config", "list", "--repo", home=home)
    assert "only-in-one" not in second.stdout
