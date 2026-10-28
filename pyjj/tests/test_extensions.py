"""User extensions: identity hooks and workflows, loaded from the files
the `pyjj.extensions` config key lists."""

import os
import shutil
import subprocess
import sys
import textwrap

import pytest

JJ_ENV = dict(JJ_USER="tester", JJ_EMAIL="tester@example.com", NO_COLOR="1")


@pytest.fixture
def repo(tmp_path):
    home = tmp_path / "home"
    (home / "jj").mkdir(parents=True)
    root = tmp_path / "repo"
    root.mkdir()
    env = os.environ.copy()
    env.update(JJ_ENV)
    env["XDG_CONFIG_HOME"] = str(home)

    class Repo:
        path = root

        def run(self, *args, cwd=None, extra_env=None):
            return subprocess.run(
                [sys.executable, "-m", "pyjj_cli", "-R", str(root), *args],
                capture_output=True, text=True, env={**env, **(extra_env or {})},
                cwd=cwd,
            )

        def extension(self, source: str):
            ext = tmp_path / "ext.py"
            ext.write_text(textwrap.dedent(source))
            (home / "jj" / "config.toml").write_text(
                f'[pyjj]\nextensions = ["{ext}"]\n')

        def author(self, rev="@"):
            # A rewrite keeps a commit's author, as in jj, so the tests
            # read commits the command created.
            result = self.run("log", "-r", rev, "--no-graph", "-T",
                              "{{ author_name }} <{{ author_email }}>")
            assert result.returncode == 0, result.stderr
            return result.stdout.strip()

    result = Repo().run("git", "init", cwd=str(root))
    assert result.returncode == 0, result.stderr
    result = Repo().run("git", "remote", "add", "origin",
                        "git@github.com:work/thing.git")
    assert result.returncode == 0, result.stderr
    return Repo()


WORK_IDENTITY = """
    import pyjj

    @pyjj.identity
    def pick(ctx):
        if "github.com:work/" in ctx.remotes.get("origin", ""):
            return pyjj.Identity(name="Worker", email="me@work.example")
        return None
"""


def test_identity_hook_picks_the_author_by_remote(repo):
    repo.extension(WORK_IDENTITY)
    (repo.path / "a.txt").write_text("a\n")
    result = repo.run("commit", "-m", "one")
    assert result.returncode == 0, result.stderr
    assert repo.author() == "Worker <me@work.example>"


def test_identity_hook_returning_none_keeps_the_config(repo):
    repo.extension("import pyjj\npyjj.identity(lambda ctx: None)\n")
    result = repo.run("commit", "-m", "one")
    assert result.returncode == 0, result.stderr
    assert repo.author() == "tester <tester@example.com>"


def test_command_line_config_outranks_the_hook(repo):
    repo.extension(WORK_IDENTITY)
    result = repo.run("--config", "user.email=cli@example.com",
                      "commit", "-m", "one")
    assert result.returncode == 0, result.stderr
    assert repo.author() == "Worker <cli@example.com>"


def test_a_failing_hook_fails_the_command_and_writes_nothing(repo):
    repo.extension("import pyjj\n\n@pyjj.identity\ndef boom(ctx):\n    raise RuntimeError('nope')\n")
    before = repo.run("--config", "pyjj.extensions=[]", "op", "log",
                      "--no-graph", "-T", "{{ id }}\n").stdout
    result = repo.run("commit", "-m", "one")
    assert result.returncode == 1
    assert "identity hook boom failed" in result.stderr
    after = repo.run("--config", "pyjj.extensions=[]", "op", "log",
                     "--no-graph", "-T", "{{ id }}\n").stdout
    assert before == after


def test_pyjj_python_commits_under_the_hook_identity(repo):
    repo.extension(WORK_IDENTITY)
    result = repo.run("python", "-c", textwrap.dedent("""
        with repo.atomic("new") as tx:
            tx.new("@", message="scripted")
    """))
    assert result.returncode == 0, result.stderr
    assert repo.author() == "Worker <me@work.example>"


WORKFLOW = """
    import pyjj

    class Ship(pyjj.Workflow):
        name = "ship"
        help = "Describe a revision and move a bookmark to it"

        def add_arguments(self, parser):
            parser.add_argument("-r", dest="revision", metavar="REVSET", default="@")
            parser.add_argument("message")

        def run(self, repo, args):
            with repo.atomic("ship") as tx:
                tx.describe(args.revision, message=args.message)
            return self.pyjj(repo, "bookmark", "set", "shipped", "-r", args.revision)
"""


def test_workflow_lists_and_runs(repo):
    repo.extension(WORKFLOW)
    listed = repo.run("workflow")
    assert listed.returncode == 0, listed.stderr
    assert listed.stdout == "ship  Describe a revision and move a bookmark to it\n"
    result = repo.run("wf", "ship", "-r", "@", "shipped it")
    assert result.returncode == 0, result.stderr
    shown = repo.run("log", "-r", "shipped", "--no-graph", "-T", "{{ description }}")
    assert shown.stdout.strip() == "shipped it"


def test_workflow_arguments_complete(repo):
    """The workflow's `REVSET` metavar completes like pyjj's own."""
    repo.extension(WORKFLOW)
    line = "pyjj workflow ship -r "
    answer = repo.path.parent / "completion-answer"
    environment = {
        **os.environ, **JJ_ENV,
        "XDG_CONFIG_HOME": str(repo.path.parent / "home"),
        "_ARGCOMPLETE": "1",
        "_ARGCOMPLETE_IFS": "\013",
        "_ARGCOMPLETE_SHELL": "bash",
        "_ARGCOMPLETE_STDOUT_FILENAME": str(answer),
        "COMP_LINE": line,
        "COMP_POINT": str(len(line)),
        "COMP_TYPE": "9",
        "_ARGCOMPLETE_COMP_WORDBREAKS": " \t\n\"'><=;|&(:",
    }
    done = subprocess.run(
        [sys.executable, "-c", "from pyjj_cli.__main__ import main; main()"],
        env=environment, cwd=str(repo.path), capture_output=True, text=True,
    )
    assert done.returncode == 0, done.stderr
    candidates = [c.rstrip().replace("\\", "")
                  for c in answer.read_text().split("\013")]
    assert "@" in candidates
    assert "root()" in candidates


@pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="ssh-keygen not available")
def test_identity_hook_picks_the_signing_key(repo, tmp_path):
    key = tmp_path / "work_key"
    subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key), "-C", "work"],
                   check=True, capture_output=True)
    repo.extension(f"""
        import pyjj

        pyjj.identity(lambda ctx: pyjj.Identity(
            email="me@work.example", signing_backend="ssh",
            signing_key="{key}", sign_behavior="own"))
    """)
    result = repo.run("new", "-m", "signed")
    assert result.returncode == 0, result.stderr
    signed = repo.run("python", "-c",
                      "print(repo.log('@')[0].commit.is_signed)")
    assert signed.stdout.strip() == "True", signed.stderr


def test_pyjj_python_honours_command_line_config(repo, tmp_path):
    """An extension named only by `--config` still picks the identity."""
    ext = tmp_path / "cli_ext.py"
    ext.write_text("import pyjj\npyjj.identity(lambda ctx: pyjj.Identity(email='cli@ext.example'))\n")
    result = repo.run("--config", f'pyjj.extensions=["{ext}"]', "python", "-c",
                      "print(repo.settings.get_string('user.email'))")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "cli@ext.example"
