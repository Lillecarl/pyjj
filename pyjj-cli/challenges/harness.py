"""Agent CTF harness: challenges a solver meets through the pyjj skill alone.

A challenge is one module `c_<name>.py` with three members:

    TITLE = "one line"
    def setup(ctx): ...   # build the arena (repos, upstreams, the mess)
    PROMPT = "..."        # what the solver sees; `{work}`, `{upstream}`,
                          # `{home}`, `{arena}` and `{pyjj}` are filled
                          # in at bundle time
    def check(ctx): ...   # return [failures]; [] means the solver passed

`setup` drives the `pyjj` CLI as a subprocess (the same path a solver
uses, so setup cannot lean on anything the solver lacks). `check` may
use the `pyjj` session API directly -- it runs here, not in the solver,
so expressiveness beats honesty there.

Usage (inside an env with `pyjj` importable, e.g. `nix run --file . tests`
or the pyjjui dev shell):

    python harness.py list
    python harness.py run restack --arena /tmp/ctf/restack --pyjj-bin <bin>
    python harness.py bundle restack --arena /tmp/ctf/restack   # solver prompt
    python harness.py check restack --arena /tmp/ctf/restack

`run` refuses a non-empty arena without `--force`, then verifies the
challenge starts unsolved: a `check` that passes immediately means the
challenge is trivial and gets reported as such.
"""

from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(HERE, "..", "skills", "pyjj", "SKILL.md")

JJ_ENV = {
    "JJ_USER": "ctf",
    "JJ_EMAIL": "ctf@example.com",
    "NO_COLOR": "1",
}


@dataclass
class Ctx:
    """Everything a challenge's setup/check may touch."""

    arena: str
    work: str = ""
    upstream: str = ""
    home: str = ""
    pyjj_bin: str | None = None
    meta: dict = field(default_factory=dict)

    def env(self) -> dict:
        env = os.environ.copy()
        env.update(JJ_ENV)
        env["HOME"] = self.home
        env["XDG_CONFIG_HOME"] = self.home
        return env

    def cli(self, *args, cwd=None, check=True, repo=None):
        """Run the pyjj CLI against the arena, hermetically."""
        target = repo or self.work
        if self.pyjj_bin:
            cmd = [self.pyjj_bin, "-R", target, *args]
        else:
            cmd = [sys.executable, "-m", "pyjj_cli", "-R", target, *args]
        result = subprocess.run(cmd, capture_output=True, text=True,
                                env=self.env(), cwd=cwd or target)
        if check and result.returncode != 0:
            raise RuntimeError(
                f"pyjj {args} failed: {result.stderr.strip()}")
        return result

    def open(self):
        """The work repo through the session API (checks only)."""
        import pyjj
        return pyjj.open(self.work)

    def raw(self, *args, cwd=None, check=True):
        """Run the pyjj CLI without `-R` (for commands that create the
        repo they name, like `git clone` / `git init`)."""
        if self.pyjj_bin:
            cmd = [self.pyjj_bin, *args]
        else:
            cmd = [sys.executable, "-m", "pyjj_cli", *args]
        result = subprocess.run(cmd, capture_output=True, text=True,
                                env=self.env(), cwd=cwd or self.arena)
        if check and result.returncode != 0:
            raise RuntimeError(
                f"pyjj {args} failed: {result.stderr.strip()}")
        return result

    def git_init(self, path: str) -> None:
        """`pyjj git init` in a fresh directory (takes no -R: the repo it
        names does not exist yet)."""
        os.makedirs(path, exist_ok=True)
        if self.pyjj_bin:
            cmd = [self.pyjj_bin, "git", "init"]
        else:
            cmd = [sys.executable, "-m", "pyjj_cli", "git", "init"]
        result = subprocess.run(cmd, capture_output=True, text=True,
                                env=self.env(), cwd=path)
        if result.returncode != 0:
            raise RuntimeError(f"git init failed: {result.stderr.strip()}")

    def write(self, path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)


def _challenge(name: str):
    try:
        return importlib.import_module(f"c_{name}")
    except ImportError:
        raise SystemExit(f"unknown challenge {name!r}")


def _ctx(args, _mod) -> Ctx:
    arena = os.path.abspath(args.arena)
    return Ctx(arena=arena,
               work=os.path.join(arena, "work"),
               upstream=os.path.join(arena, "upstream"),
               home=os.path.join(arena, "home"),
               pyjj_bin=args.pyjj_bin)


def _solver_preamble(ctx: Ctx) -> str:
    pyjj = ctx.pyjj_bin or f"{sys.executable} -m pyjj_cli"
    return (
        "You are solving a pyjj challenge. Rules:\n"
        f"- Work only inside {ctx.arena}. Do not touch anything outside it.\n"
        f"- Do not read anything under pyjj-cli/challenges/ (that is the "
        "answer key).\n"
        "- Drive the repo with the pyjj CLI. The binary is:\n"
        f"      {pyjj} -R {ctx.work} <command>\n"
        "- Run with this environment so the repo stays hermetic:\n"
        f"      export HOME={ctx.home} XDG_CONFIG_HOME={ctx.home} "
        "JJ_USER=ctf JJ_EMAIL=ctf@example.com NO_COLOR=1\n"
        "- When you believe the goal is met, stop and report what you did.\n"
    )


def cmd_list(_args) -> int:
    for name in sorted(_names()):
        mod = _challenge(name)
        print(f"{name}: {mod.TITLE}")
    return 0


def _names() -> list[str]:
    return sorted(
        name[2:-3] for name in os.listdir(HERE)
        if name.startswith("c_") and name.endswith(".py"))


def cmd_run(args) -> int:
    mod = _challenge(args.name)
    ctx = _ctx(args, mod)
    if os.path.exists(ctx.arena) and os.listdir(ctx.arena) and not args.force:
        raise SystemExit(f"arena {ctx.arena} is not empty (use --force)")
    os.makedirs(ctx.home, exist_ok=True)
    mod.setup(ctx)
    failures = mod.check(ctx)
    if failures:
        print(f"arena ready at {ctx.arena}: challenge starts unsolved, "
              f"{len(failures)} check(s) failing as expected")
    else:
        print(f"WARNING: check passes on a fresh arena -- {args.name} "
              f"may be trivial")
    return 0


def cmd_bundle(args) -> int:
    mod = _challenge(args.name)
    ctx = _ctx(args, mod)
    with open(SKILL, encoding="utf-8") as handle:
        print(handle.read())
    print("---\n")
    print(_solver_preamble(ctx))
    print(mod.PROMPT.format(work=ctx.work, upstream=ctx.upstream,
                            home=ctx.home, arena=ctx.arena,
                            pyjj=ctx.pyjj_bin or "pyjj"))
    return 0


def cmd_check(args) -> int:
    mod = _challenge(args.name)
    ctx = _ctx(args, mod)
    failures = mod.check(ctx)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("PASS")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="challenge names and titles")

    for name in ("run", "bundle", "check"):
        p = sub.add_parser(name)
        p.add_argument("name", help="challenge to run")
        p.add_argument("--arena", required=True,
                       help="arena directory (built by run, solved in place)")
        if name in ("run", "bundle", "check"):
            p.add_argument("--pyjj-bin", default=None,
                           help="pyjj binary the solver uses")
        if name == "run":
            p.add_argument("--force", action="store_true",
                           help="reuse a non-empty arena directory")
    args = parser.parse_args(argv)
    return {"list": cmd_list, "run": cmd_run,
            "bundle": cmd_bundle, "check": cmd_check}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
