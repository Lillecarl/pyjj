"""Differential-testing harness: run identical scenarios through the real
`jj` CLI and through pyjj, each in its own fresh repository, then compare
the resulting repo states.

The whole suite rests on an empirically validated determinism contract.
Two independent repositories end up bit-identical -- down to change ids,
commit ids and bookmarks -- when:

- identity is pinned (`JJ_USER`/`JJ_EMAIL`),
- commit and operation timestamps are pinned (`JJ_TIMESTAMP`/
  `JJ_OP_TIMESTAMP`, both tools map these onto `debug.*-timestamp`
  config),
- machine config is suppressed by pointing `HOME`/`XDG_CONFIG_HOME` at a
  shared empty scratch dir (a real user config with e.g. GPG signing
  would otherwise leak non-deterministic signatures into commit ids),
- change-id minting randomness is seeded per *logical step* via
  `JJ_RANDOMNESS_SEED`. The seed restarts per process, so a fixed global
  seed would mint colliding change ids; instead every logical operation
  gets its own derived seed. `jj` is process-per-command by nature, so
  the pyjj side runs one fresh interpreter per operation too -- that
  keeps the two RNG streams aligned.

State extraction is uniform: the same `jj` binary reads BOTH repositories
afterwards. A mismatch therefore means the repos really diverged, never
that two extractors disagreed.

Only steps that invoke a tool consume a step index; plain working-copy
file writes do not (they draw no randomness).
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

DRIVER = Path(__file__).with_name("driver.py")

PIN_USER = "Alice"
PIN_EMAIL = "alice@example.com"
PIN_TIME = "2001-02-03T04:05:06+00:00"
SEED_BASE = 1000


class RepoPair:
    """One scenario's worth of parallel repos: `cli/repo` driven by the jj
    binary, `py/repo` driven by pyjj through driver.py subprocesses."""

    def __init__(self, root: Path, jj_bin: str | None = None):
        self.root = root
        self.jj_bin = jj_bin or os.environ.get("PYJJ_PARITY_JJ") or "jj"
        self.cli_repo = root / "cli" / "repo"
        self.py_repo = root / "py" / "repo"
        # jj creates missing intermediate dirs on init; pyjj requires the
        # destination to exist, so create both up front (empty is fine).
        self.cli_repo.mkdir(parents=True)
        self.py_repo.mkdir(parents=True)
        self.home = root / "home"
        (self.home / ".config").mkdir(parents=True)
        self._step = 0

    def _env(self, *, bump: bool) -> dict[str, str]:
        if bump:
            self._step += 1
        # Inherit the parent environment (the dev-shell vars the editable
        # installs need), then layer the determinism pins on top and point
        # HOME at the scratch dir so no real user config leaks in.
        for name in list(os.environ):
            if name.startswith("JJ_"):
                del os.environ[name]
        env = dict(os.environ)
        env.update(
            {
                "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.home / ".config"),
                "JJ_USER": PIN_USER,
                "JJ_EMAIL": PIN_EMAIL,
                "JJ_TIMESTAMP": PIN_TIME,
                "JJ_OP_TIMESTAMP": PIN_TIME,
                "JJ_RANDOMNESS_SEED": str(SEED_BASE + self._step),
            }
        )
        return env

    def _run(self, argv: list[str], env: dict[str, str]) -> None:
        proc = subprocess.run(
            argv, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True
        )
        if proc.returncode != 0:
            raise AssertionError(
                f"command failed ({proc.returncode}): {argv}\n"
                f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )

    # -- driving -----------------------------------------------------------

    def init(self) -> None:
        self.op(["git", "init", str(self.cli_repo)], py=["git", "init", str(self.py_repo)])

    def op(
        self,
        jj: list[str],
        py: list[str] | None = None,
        files: dict[str, bytes] | None = None,
    ) -> None:
        """Run one logical operation on both sides.

        `jj` args go to the binary verbatim (`-R <cli-repo>` is prepended
        automatically). `py` goes to the pyjj-cli driver against
        `<py-repo>`; when omitted, the SAME argv runs on both sides --
        which is the point: pyjj-cli must speak jj's argument dialect for
        parity to pass at all. `files` are written into both working
        copies first (both CLIs pick them up via implicit snapshot).
        """
        env = self._env(bump=True)
        for name, content in (files or {}).items():
            for ws in (self.cli_repo, self.py_repo):
                path = ws / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        if jj:
            # `git init` must not carry `-R`: that flag makes every other
            # command search for an existing repo upward.
            if jj[:2] == ["git", "init"]:
                self._run([self.jj_bin, *jj], env)
            else:
                self._run([self.jj_bin, "-R", str(self.cli_repo), *jj], env)
        if jj or py:
            self._run(
                [sys.executable, str(DRIVER), str(self.py_repo), *(py if py is not None else jj)],
                env,
            )

    # -- extracting & comparing --------------------------------------------

    def _extract_repo(self, repo: Path) -> dict:
        """Canonical state of one repository, read through the pinned jj."""
        out = self._out(
            [self.jj_bin, "-R", str(repo), "--no-pager", "log", "-r", "all()",
             "--no-graph", "-T", 'commit_id.short(40) ++ "\\n"'],
            repo,
        )
        commits: dict[str, dict] = {}
        for cid in out.splitlines():
            if not cid:
                continue
            meta = self._out(
                [
                    self.jj_bin, "-R", str(repo), "--no-pager", "log", "-r", cid,
                    "--no-graph", "-T",
                    'description ++ "\x1f" ++ author.name() ++ "\x1f"'
                    ' ++ author.email() ++ "\x1f" ++ committer.name() ++ "\x1f"'
                    ' ++ committer.email() ++ "\x1f"'
                    ' ++ parents.map(|p| p.commit_id().short(40)).join(" ")'
                    ' ++ "\x1f" ++ bookmarks.join(" ") ++ "\x1f"'
                    ' ++ working_copies.join(" ")',
                ]
            )
            desc, aname, amail, cname, cmail, parents, bookmarks, wcs = (
                meta.split("\x1f")
            )
            files = {}
            for path in self._out(
                [self.jj_bin, "-R", str(repo), "--no-pager", "file", "list", "-r", cid],
                repo,
            ).splitlines():
                content = subprocess.run(
                    [self.jj_bin, "-R", str(repo), "--no-pager", "file", "show",
                     "-r", cid, path],
                    env=self._env(bump=False),
                    capture_output=True,
                    check=True,
                    cwd=str(repo),
                ).stdout
                files[path] = hashlib.sha256(content).hexdigest()
            commits[cid] = {
                "description": desc,
                "author": [aname, amail],
                "committer": [cname, cmail],
                "parents": sorted(parents.split()),
                "bookmarks": sorted(bookmarks.split()),
                "working_copies": sorted(wcs.split()),
                "files": files,
            }
        return {"commits": commits}

    def _out(self, argv: list[str], repo: Path | None = None) -> str:
        # With cwd at the repo root, `jj file list` prints workspace-relative
        # paths, so extracted trees from the two repos are comparable.
        proc = subprocess.run(
            argv,
            env=self._env(bump=False),
            capture_output=True,
            text=True,
            cwd=str(repo) if repo else None,
        )
        if proc.returncode != 0:
            raise AssertionError(
                f"extraction failed: {argv}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
        return proc.stdout

    def assert_parity(self) -> None:
        got = {
            side: self._extract_repo(repo)
            for side, repo in (("cli", self.cli_repo), ("py", self.py_repo))
        }
        if got["cli"] == got["py"]:
            return
        a = json.dumps(got["cli"], indent=1, sort_keys=True).splitlines()
        b = json.dumps(got["py"], indent=1, sort_keys=True).splitlines()
        diff = "\n".join(difflib.unified_diff(a, b, "cli", "py", lineterm=""))
        raise AssertionError(f"repos diverged:\n{diff}")
