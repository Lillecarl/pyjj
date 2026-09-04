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
EDITOR = Path(__file__).with_name("editor.py")
DIFF_TOOL = Path(__file__).with_name("diff_tool.py")
MERGE_TOOL = Path(__file__).with_name("merge_tool.py")

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
        self.home = root / "home"
        # The scripted editor lives in the pair dir (never chmod files in
        # the source tree); both CLIs find it via $EDITOR.
        self.editor_bin = root / "bin" / "parity-editor"
        self.editor_bin.parent.mkdir(parents=True, exist_ok=True)
        self.editor_bin.write_bytes(EDITOR.read_bytes())
        self.editor_bin.chmod(0o755)
        self.diff_tool_bin = root / "bin" / "parity-diff-tool"
        self.diff_tool_bin.write_bytes(DIFF_TOOL.read_bytes())
        self.diff_tool_bin.chmod(0o755)
        self.merge_tool_bin = root / "bin" / "parity-merge-tool"
        self.merge_tool_bin.write_bytes(MERGE_TOOL.read_bytes())
        self.merge_tool_bin.chmod(0o755)
        # Scratch-home jj config, loaded identically by both sides
        # (load_config=True): registers the scripted diff tool (the
        # dir-based edit protocol split/diffedit use) and two scripted
        # 3-way merge tools sharing one program -- `parity-merge` runs in
        # marker mode ($output pre-populated with the materialized
        # conflict), `parity-write` verbatim ($output starts empty and
        # its final bytes are taken as fully resolved). `program` carries
        # the executable path; jj substitutes $left/$right/$base/$output.
        config_dir = self.home / ".config" / "jj"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.toml").write_text(
            "[merge-tools.parity-diff]\n"
            f'program = "{self.diff_tool_bin}"\n'
            'edit-args = ["--edit", "$left", "$right"]\n'
            "\n"
            "[merge-tools.parity-merge]\n"
            f'program = "{self.merge_tool_bin}"\n'
            'merge-args = ["--marker", "$base", "$left", "$right", "$output", "$path"]\n'
            "merge-tool-edits-conflict-markers = true\n"
            "\n"
            "[merge-tools.parity-write]\n"
            f'program = "{self.merge_tool_bin}"\n'
            'merge-args = ["--verbatim", "$base", "$left", "$right", "$output"]\n'
        )
        # jj creates missing intermediate dirs on init; pyjj requires the
        # destination to exist, so create both up front (empty is fine).
        self.cli_repo.mkdir(parents=True)
        self.py_repo.mkdir(parents=True)
        (self.home / ".config").mkdir(parents=True, exist_ok=True)
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
                "EDITOR": str(self.editor_bin),
                "VISUAL": str(self.editor_bin),
            }
        )
        # Real jj resolves the editor as ui.editor -> JJ_EDITOR -> VISUAL
        # -> EDITOR; pin every layer so a stray host setting can't win.
        env.pop("JJ_EDITOR", None)
        return env

    def _run(self, argv: list[str], env: dict[str, str],
             stdin: str | None = None, cwd: Path | None = None,
             editor_spec: dict | None = None,
             diff_spec: dict | None = None,
             merge_spec: dict | None = None,
             may_fail: bool = False) -> int:
        if editor_spec is not None:
            env["PARITY_EDITOR_SPEC"] = json.dumps(editor_spec)
        if diff_spec is not None:
            env["PARITY_DIFF_SPEC"] = json.dumps(diff_spec)
        if merge_spec is not None:
            env["PARITY_MERGE_SPEC"] = json.dumps(merge_spec)
        proc = subprocess.run(
            argv,
            env=env,
            input=stdin,
            stdin=subprocess.DEVNULL if stdin is None else None,
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd else None,
        )
        env.pop("PARITY_EDITOR_SPEC", None)
        env.pop("PARITY_DIFF_SPEC", None)
        env.pop("PARITY_MERGE_SPEC", None)
        if proc.returncode != 0 and not may_fail:
            raise AssertionError(
                f"command failed ({proc.returncode}): {argv}\n"
                f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
        return proc.returncode

    # -- driving -----------------------------------------------------------

    def init(self) -> None:
        self.op(["git", "init", str(self.cli_repo)], py=["git", "init", str(self.py_repo)])

    def op(
        self,
        jj: list[str],
        py: list[str] | None = None,
        files: dict[str, bytes] | None = None,
        stdin: str | None = None,
        cli_files: dict[str, bytes] | None = None,
        py_files: dict[str, bytes] | None = None,
        editor_spec: dict | tuple[dict, dict] | None = None,
        diff_spec: dict | None = None,
        merge_spec: dict | None = None,
        may_fail: bool = False,
    ) -> int | None:
        """Run one logical operation on both sides.

        `jj` args go to the binary verbatim (`-R <cli-repo>` is prepended
        automatically). `py` goes to the pyjj-cli driver against
        `<py-repo>`; when omitted, the SAME argv runs on both sides --
        which is the point: pyjj-cli must speak jj's argument dialect for
        parity to pass at all. `files` are written into BOTH working
        copies first (both CLIs pick them up via implicit snapshot);
        `cli_files`/`py_files` additionally write per-side bytes, for
        content that legitimately differs across repos (conflict-marker
        text embeds repo-local change ids). `stdin` is piped verbatim to
        both commands (--stdin scenarios). `editor_spec` arms the scripted
        $EDITOR for editor-based flows; a single dict goes to both sides,
        a (cli, py) tuple differentiates when the buffer embeds repo-local
        ids. `diff_spec` arms the scripted dir-based diff tool;
        `merge_spec` arms the scripted 3-way merge tool. `may_fail`
        accepts nonzero exits from BOTH sides (expected-failure flows like
        partial resolution); state comparison still applies.
        """
        env = self._env(bump=True)
        self._write_files({**(files or {}), **(cli_files or {})}, self.cli_repo)
        self._write_files({**(files or {}), **(py_files or {})}, self.py_repo)
        cli_spec = py_spec = editor_spec
        if isinstance(editor_spec, tuple):
            cli_spec, py_spec = editor_spec
        rc = 0
        if jj:
            # `git init` must not carry `-R`: that flag makes every other
            # command search for an existing repo upward. Commands run with
            # their repo as CWD so relative FILESETS resolve identically.
            if jj[:2] == ["git", "init"]:
                rc = self._run([self.jj_bin, *jj], env, stdin=stdin,
                               editor_spec=cli_spec, may_fail=may_fail)
            else:
                rc = self._run([self.jj_bin, "-R", str(self.cli_repo), *jj], env,
                               stdin=stdin, cwd=self.cli_repo, editor_spec=cli_spec,
                               diff_spec=diff_spec, merge_spec=merge_spec,
                               may_fail=may_fail)
        if jj or py:
            return self._run(
                [sys.executable, str(DRIVER), str(self.py_repo), *(py if py is not None else jj)],
                env,
                stdin=stdin,
                cwd=self.py_repo,
                editor_spec=py_spec,
                diff_spec=diff_spec,
                merge_spec=merge_spec,
                may_fail=may_fail,
            )
        return rc

    def _write_files(self, files: dict[str, bytes], ws: Path) -> None:
        for name, content in files.items():
            path = ws / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def read_wc_file(self, side: str, name: str) -> bytes:
        """Read a raw working-copy file from one side ('cli' or 'py') --
        for scenarios that transform each side's own text (conflict
        markers embed repo-local ids)."""
        root = self.cli_repo if side == "cli" else self.py_repo
        return (root / name).read_bytes()

    def write_wc_file(self, side: str, name: str, content: bytes) -> None:
        root = self.cli_repo if side == "cli" else self.py_repo
        (root / name).write_bytes(content)

    # -- extracting & comparing --------------------------------------------

    def _op_id(self, repo: Path, depth: int) -> str:
        """The operation id `depth` steps back from the head op (depth 0 =
        current head). Op ids differ between the two repos (hostnames,
        snapshot-op folding), so scenarios address them PER SIDE.

        Reads with `--ignore-working-copy` for the reason `_extract_repo`
        gives -- and here it also keeps the depth honest, since a
        snapshot taken while looking would itself become the head op."""
        out = self._out(
            [self.jj_bin, "-R", str(repo), "--no-pager", "--ignore-working-copy", "op", "log",
             "--no-graph", "--limit", str(depth + 1), "-T", 'self.id() ++ "\\n"'],
            repo,
        )
        ids = [line for line in out.splitlines() if line]
        return ids[-1]

    def op_id(self, side: str, depth: int) -> str:
        """The operation id `depth` steps back on one side ('cli' or
        'py'). Scenarios that name an operation on the command line need
        this per side, because op ids differ between the two repos."""
        return self._op_id(self.cli_repo if side == "cli" else self.py_repo, depth)

    def op_restore(self, depth: int) -> None:
        """Restore both sides to their own state `depth` operations back."""
        self.op(
            jj=["op", "restore", self._op_id(self.cli_repo, depth)],
            py=["op", "restore", self._op_id(self.py_repo, depth)],
        )

    def _extract_repo(self, repo: Path) -> dict:
        """Canonical state of one repository, read through the pinned jj.

        Every read here passes `--ignore-working-copy`, so extraction
        observes and never mutates. Without it, reading snapshots -- and
        that hides a whole class of bug: if pyjj failed to snapshot
        where jj does, the extractor would fold the file in on the pyjj
        side, and with pinned timestamps it could rebuild the identical
        commit id. It also makes `--ignore-working-copy` itself testable,
        since a harness that snapshots cannot see a command that didn't.
        """
        out = self._out(
            [self.jj_bin, "-R", str(repo), "--no-pager", "--ignore-working-copy", "log", "-r", "all()",
             "--no-graph", "-T", 'commit_id.short(40) ++ "\\n"'],
            repo,
        )
        commits: dict[str, dict] = {}
        for cid in out.splitlines():
            if not cid:
                continue
            meta = self._out(
                [
                    self.jj_bin, "-R", str(repo), "--no-pager", "--ignore-working-copy", "log", "-r", cid,
                    "--no-graph", "-T",
                    'description ++ "\x1f" ++ author.name() ++ "\x1f"'
                    ' ++ author.email() ++ "\x1f" ++ committer.name() ++ "\x1f"'
                    ' ++ committer.email() ++ "\x1f"'
                    ' ++ parents.map(|p| p.commit_id().short(40)).join(" ")'
                    ' ++ "\x1f" ++ bookmarks.join(" ") ++ "\x1f"'
                    ' ++ working_copies.join(" ") ++ "\x1f"'
                    ' ++ tags.join(" ")',
                ]
            )
            desc, aname, amail, cname, cmail, parents, bookmarks, wcs, tags = (
                meta.split("\x1f")
            )
            files = {}
            for path in self._out(
                [self.jj_bin, "-R", str(repo), "--no-pager", "--ignore-working-copy", "file", "list", "-r", cid],
                repo,
            ).splitlines():
                content = subprocess.run(
                    [self.jj_bin, "-R", str(repo), "--no-pager", "--ignore-working-copy", "file", "show",
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
                "tags": sorted(tags.split()),
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
