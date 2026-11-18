"""Octopus labs: throwaway fork repositories for the octopus workflow.

    pyjj python --no-repo octolab.py build SCENARIO DEST
    pyjj python --no-repo octolab.py check SCENARIO DEST
    pyjj python --no-repo octolab.py task SCENARIO
    pyjj python --no-repo octolab.py list

`build` makes DEST/upstream.git (the project), DEST/origin.git (the
fork's remote), DEST/seed (a workspace that plays upstream's
maintainers) and DEST/fork, the repository an agent works in. `check`
reads DEST/fork and exits 1 with one line per broken expectation.

The fork's shape, before a scenario adds to it:

    @            octopus+1, where work happens
    octopus      merge of every topic tip, empty
    alpha beta gamma   topic bookmarks, each on main
    main@upstream

pytest imports this module; the subagent runs go through the CLI.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

PYJJ = os.environ.get("PYJJ", "pyjj")
TOPICS = ("alpha", "beta", "gamma")

CONFIG = "\n".join(f"k{n} = base" for n in range(1, 11)) + "\n"
ALPHA_PY = "".join(f"def alpha_{n}():\n    return {n}\n\n" for n in range(1, 4))

# Repo-level config every lab repository gets. It outranks the user's
# own config, so a machine's signing key or identity hook stays out.
REPO_CONFIG = {
    "user.name": "Lab User",
    "user.email": "lab@example.com",
    "signing.behavior": "drop",
    "pyjj.extensions": "[]",
}


def run(*argv: str, cwd: Path, stdin: str | None = None) -> str:
    done = subprocess.run(
        argv, cwd=cwd, input=stdin, text=True, capture_output=True, check=False
    )
    if done.returncode != 0:
        raise RuntimeError(
            f"{' '.join(argv)} (in {cwd}) exited {done.returncode}\n"
            f"{done.stdout}{done.stderr}"
        )
    return done.stdout


def pj(cwd: Path, *argv: str) -> str:
    return run(PYJJ, *argv, cwd=cwd)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def set_line(path: Path, key: str, value: str) -> None:
    lines = path.read_text().splitlines()
    lines = [
        f"{key} = {value}" if line.startswith(f"{key} = ") else line for line in lines
    ]
    path.write_text("\n".join(lines) + "\n")


def configure(repo: Path) -> None:
    for key, value in REPO_CONFIG.items():
        argv = ["config", "set", "--repo", key, value]
        pj(repo, *argv)


def init_repo(path: Path, *clone_args: str) -> Path:
    """A colocated pyjj repo, configured before its first commit."""
    pj(path.parent, *clone_args, str(path))
    configure(path)
    # The clone checked out with the user's identity; restart `@` so the
    # first commit carries the lab's.
    pj(path, "new", "trunk()")
    return path


@dataclass
class Lab:
    root: Path

    @property
    def upstream(self) -> Path:
        return self.root / "upstream.git"

    @property
    def origin(self) -> Path:
        return self.root / "origin.git"

    @property
    def seed(self) -> Path:
        return self.root / "seed"

    @property
    def fork(self) -> Path:
        return self.root / "fork"

    def upstream_commit(self, message: str, edit: Callable[[Path], None]) -> None:
        """Land a commit on upstream's main, as a maintainer would."""
        pj(self.seed, "git", "fetch")
        pj(self.seed, "new", "main@origin")
        edit(self.seed)
        pj(self.seed, "commit", "-m", message)
        pj(self.seed, "bookmark", "set", "main", "-r", "@-")
        pj(self.seed, "git", "push", "--bookmark", "main")

    def fork_commit(self, message: str, edit: Callable[[Path], None]) -> None:
        edit(self.fork)
        pj(self.fork, "commit", "-m", message)


def build_base(root: Path) -> Lab:
    lab = Lab(root)
    root.mkdir(parents=True)
    run("git", "init", "--bare", "--initial-branch=main", str(lab.upstream), cwd=root)
    run("git", "init", "--bare", "--initial-branch=main", str(lab.origin), cwd=root)

    pj(root, "git", "init", str(lab.seed))
    configure(lab.seed)
    pj(lab.seed, "git", "remote", "add", "origin", str(lab.upstream))
    write(lab.seed / "README.md", "# project\n")
    write(lab.seed / "config.txt", CONFIG)
    pj(lab.seed, "commit", "-m", "project: initial import")
    pj(lab.seed, "bookmark", "create", "main", "-r", "@-")
    pj(lab.seed, "git", "push", "--bookmark", "main")

    init_repo(lab.fork, "git", "clone", "--remote", "upstream", str(lab.upstream))
    pj(lab.fork, "git", "remote", "add", "origin", str(lab.origin))

    f = lab.fork
    pj(f, "new", "main", "-m", "alpha: add alpha module")
    write(f / "alpha.py", ALPHA_PY)
    pj(f, "new", "-m", "alpha: tune k2")
    set_line(f / "config.txt", "k2", "alpha")
    pj(f, "bookmark", "create", "alpha", "-r", "@")

    pj(f, "new", "main", "-m", "beta: add beta module")
    write(f / "beta.py", "".join(f"BETA_{n} = {n}\n" for n in range(1, 6)))
    pj(f, "bookmark", "create", "beta", "-r", "@")

    pj(f, "new", "main", "-m", "gamma: add gamma module")
    write(f / "gamma.py", "def gamma():\n    return 'gamma'\n")
    pj(f, "new", "-m", "gamma: tune k8")
    set_line(f / "config.txt", "k8", "gamma")
    pj(f, "bookmark", "create", "gamma", "-r", "@")

    pj(f, "new", *TOPICS, "-m", "octopus")
    pj(f, "bookmark", "create", "octopus", "-r", "@")
    pj(f, "new")
    pj(f, "git", "push", "--remote", "origin", *[a for t in TOPICS for a in ("-b", t)])
    return lab


# -- reading state --------------------------------------------------------


@dataclass
class State:
    """The fork, as plain data. Everything a check needs, read once."""

    parents: dict[str, list[str]]  # change id -> parent change ids
    subject: dict[str, str]
    bookmarks: dict[str, str]  # local bookmark -> change id
    remote_main: str
    wc: str
    conflicted: set[str]
    files: dict[str, dict[str, str]] = field(default_factory=dict)

    def lane(self, topic: str) -> list[str]:
        """main..topic, tip first, following first parents."""
        out, at = [], self.bookmarks.get(topic)
        while at is not None and at != self.remote_main and at in self.parents:
            out.append(at)
            ps = self.parents[at]
            at = ps[0] if ps else None
        return out


READ_STATE = r"""
import json, sys
import pyjj
r = pyjj.open(sys.argv[1])
def cid(c): return c.change_id.reverse_hex()
# Visible commits only: a hidden predecessor shares its change id.
commits = r.revset("::visible_heads()")
out = {"parents": {}, "subject": {}, "files": {}}
by_id = {c.id.hex(): c for c in commits}
for c in commits:
    out["parents"][cid(c)] = [cid(by_id[p.hex()]) for p in c.parent_ids if p.hex() in by_id]
    out["subject"][cid(c)] = (c.description.splitlines() or [""])[0]
out["bookmarks"] = {
    b.name: cid(r.resolve(b.target_ids[0].hex()))
    for b in r._repo.bookmarks() if b.target_ids and not b.has_conflict}
out["remote_main"] = cid(r.resolve("main@upstream"))
out["wc"] = cid(r.resolve("@"))
out["conflicted"] = [cid(c) for c in r.revset("conflicts()")]
for c in r.revset("bookmarks() | @ | main@upstream"):
    out["files"][cid(c)] = {p: c.read_file(p).decode(errors="replace")
                            for p in c.list_files() if not c.file_kind(p).endswith("conflict")}
print(json.dumps(out))
"""


def read_state(lab: Lab) -> State:
    raw = json.loads(
        run(
            PYJJ,
            "python",
            "--no-repo",
            "-",
            str(lab.fork),
            cwd=lab.root,
            stdin=READ_STATE,
        )
    )
    raw["conflicted"] = set(raw["conflicted"])
    return State(**raw)


def base_expectations(
    s: State, topics: tuple[str, ...], stacked: dict[str, str] | None = None
) -> list[str]:
    """What holds after every scenario: the octopus is intact.

    `stacked` maps a topic to the topic it must start on instead of main.
    An octopus parent that is an ancestor of another (a stacked base) may
    stay or go.
    """
    stacked = stacked or {}
    bad = []
    octo = s.bookmarks.get("octopus")
    if octo is None:
        return ["the octopus bookmark is gone"]
    tips = {s.bookmarks.get(t) for t in topics}
    if None in tips:
        bad.append(f"a topic bookmark is missing: have {sorted(s.bookmarks)}")
    bases = {s.bookmarks.get(b) for b in stacked.values()}
    if set(s.parents[octo]) - bases != tips - bases:
        names = {v: k for k, v in s.bookmarks.items()}
        got = sorted(names.get(p, s.subject.get(p, p)) for p in s.parents[octo])
        bad.append(f"octopus parents are {got}, expected the tips of {sorted(topics)}")
    for t in topics:
        lane = s.lane(t)
        if not lane:
            bad.append(f"topic {t} has no commits of its own")
            continue
        base = stacked.get(t)
        if base is not None:
            if s.bookmarks.get(base) not in lane:
                bad.append(f"topic {t} is not stacked on {base}")
            continue
        root = lane[-1]
        if s.parents.get(root) != [s.remote_main]:
            bad.append(f"topic {t} does not start on main@upstream")
    if s.parents.get(s.wc) != [octo]:
        bad.append("@ is not a child of the octopus")
    if s.conflicted:
        bad.append(
            f"{len(s.conflicted)} commits are in conflict: "
            + ", ".join(s.subject.get(c, c) for c in s.conflicted)
        )
    return bad


# -- scenarios --------------------------------------------------------------


@dataclass
class Scenario:
    name: str
    task: str
    setup: Callable[[Lab], None]
    check: Callable[[Lab, State], list[str]]
    topics: tuple[str, ...] = TOPICS
    stacked: dict[str, str] = field(default_factory=dict)


SCENARIOS: dict[str, Scenario] = {}


def scenario(
    name: str,
    task: str,
    topics: tuple[str, ...] = TOPICS,
    stacked: dict[str, str] | None = None,
):
    def register(pair: tuple[Callable[[Lab], None], Callable[[Lab, State], list[str]]]):
        SCENARIOS[name] = Scenario(
            name, task.strip(), pair[0], pair[1], topics, stacked or {}
        )
        return pair

    return register


def wc_is_empty(s: State) -> list[str]:
    octo = s.bookmarks["octopus"]
    if s.files.get(s.wc) != s.files.get(octo):
        return ["@ still holds changes; it should be empty on top of the octopus"]
    return []


def file_in(s: State, topic: str, path: str, needle: str) -> list[str]:
    tip = s.bookmarks.get(topic)
    content = s.files.get(tip, {}).get(path)
    if content is None or needle not in content:
        return [f"{path} on {topic} does not contain {needle!r}"]
    return []


def _absorb_setup(lab: Lab) -> None:
    f = lab.fork
    text = (f / "beta.py").read_text().replace("BETA_3 = 3", "BETA_3 = 33")
    write(f / "beta.py", text)
    text = (f / "alpha.py").read_text().replace("return 2", "return 22")
    write(f / "alpha.py", text)


def _absorb_check(lab: Lab, s: State) -> list[str]:
    return (
        file_in(s, "beta", "beta.py", "BETA_3 = 33")
        + file_in(s, "alpha", "alpha.py", "return 22")
        + wc_is_empty(s)
    )


scenario(
    "absorb",
    """
The working copy holds two small fixes: one to beta.py, one to alpha.py.
Fold each fix into the topic branch that owns those lines. Leave the
working copy empty on top of the octopus.
""",
)((_absorb_setup, _absorb_check))


def _move_setup(lab: Lab) -> None:
    write(lab.fork / "gamma.md", "# gamma\n\nThe gamma module.\n")
    pj(lab.fork, "describe", "-m", "gamma: document the module")


def _move_check(lab: Lab, s: State) -> list[str]:
    bad = file_in(s, "gamma", "gamma.md", "The gamma module") + wc_is_empty(s)
    lane = [s.subject[c] for c in s.lane("gamma")]
    if "gamma: document the module" not in lane:
        bad.append(f"no commit 'gamma: document the module' on gamma; lane is {lane}")
    if len(lane) != 3:
        bad.append(f"gamma should have 3 commits, has {len(lane)}: {lane}")
    return bad


scenario(
    "move",
    """
The working copy holds a finished commit, "gamma: document the module".
Move it onto the gamma topic as its own commit, on top of gamma's
existing commits. Leave the working copy empty on top of the octopus.
""",
)((_move_setup, _move_check))


def _squash_setup(lab: Lab) -> None:
    f = lab.fork
    with (f / "alpha.py").open("a") as fh:
        fh.write("def alpha_4():\n    return 4\n")
    write(f / "notes.txt", "scratch notes, not for any branch\n")


def _squash_check(lab: Lab, s: State) -> list[str]:
    bad = file_in(s, "alpha", "alpha.py", "def alpha_4")
    lane = s.lane("alpha")
    if len(lane) != 2:
        bad.append(f"alpha should still have 2 commits, has {len(lane)}")
    wc = s.files.get(s.wc, {})
    if "notes.txt" not in wc:
        bad.append("notes.txt is no longer in the working copy")
    for t in TOPICS:
        if "notes.txt" in s.files.get(s.bookmarks.get(t), {}):
            bad.append(f"notes.txt leaked into {t}")
    return bad


scenario(
    "squash",
    """
The working copy holds a new function in alpha.py and a scratch file
notes.txt. Squash the alpha.py change into the last commit of the alpha
topic (do not add a new commit to alpha). notes.txt must stay in the
working copy, which stays on top of the octopus.
""",
)((_squash_setup, _squash_check))


def _new_topic_setup(lab: Lab) -> None:
    write(lab.fork / "delta.py", "DELTA = 'delta'\n")
    pj(lab.fork, "describe", "-m", "delta: add delta module")


def _new_topic_check(lab: Lab, s: State) -> list[str]:
    bad = file_in(s, "delta", "delta.py", "DELTA") + wc_is_empty(s)
    if [s.subject[c] for c in s.lane("delta")] != ["delta: add delta module"]:
        bad.append("delta should hold exactly the commit 'delta: add delta module'")
    return bad


scenario(
    "new-topic",
    """
The working copy holds a finished commit, "delta: add delta module". It
belongs to none of the existing topics. Make it a new topic branch with
the bookmark `delta`, based on main, and include it in the octopus.
Leave the working copy empty on top of the octopus.
""",
    topics=(*TOPICS, "delta"),
)((_new_topic_setup, _new_topic_check))


def _sync_setup(lab: Lab) -> None:
    def edit(at: Path) -> None:
        set_line(at / "config.txt", "k2", "upstream")
        set_line(at / "config.txt", "k5", "upstream")
        write(at / "UPSTREAM.md", "news\n")

    lab.upstream_commit("project: retune k2 and k5", edit)


def _sync_check(lab: Lab, s: State) -> list[str]:
    bad = []
    for t in TOPICS:
        content = s.files.get(s.bookmarks.get(t), {})
        if "UPSTREAM.md" not in content:
            bad.append(f"{t} is not rebased onto the new upstream main")
    bad += file_in(s, "alpha", "config.txt", "k2 = alpha")
    bad += file_in(s, "alpha", "config.txt", "k5 = upstream")
    return bad


scenario(
    "sync",
    """
Upstream has moved on: main on the `upstream` remote has a new commit.
Fetch it and rebase every topic onto the new main. Upstream changed k2
in config.txt, which the alpha topic also changes; where they disagree,
alpha's value wins. Keep upstream's other changes.
""",
)((_sync_setup, _sync_check))


def _landed_setup(lab: Lab) -> None:
    def edit(at: Path) -> None:
        write(at / "alpha.py", ALPHA_PY)
        set_line(at / "config.txt", "k2", "alpha")

    lab.upstream_commit("alpha: add alpha module (#12)", edit)


def _landed_check(lab: Lab, s: State) -> list[str]:
    bad = []
    if "alpha" in s.bookmarks and s.bookmarks["alpha"] in set(
        s.parents.get(s.bookmarks.get("octopus"), [])
    ):
        bad.append("alpha is still merged into the octopus")
    for t in ("beta", "gamma"):
        if "alpha.py" not in s.files.get(s.bookmarks.get(t), {}):
            bad.append(f"{t} is not rebased onto the new upstream main")
    return bad


scenario(
    "landed",
    """
Upstream merged the alpha topic: main on the `upstream` remote now holds
alpha's changes as one squashed commit. Fetch, rebase the remaining
topics onto the new main, and take alpha out of the octopus. Delete the
local alpha bookmark.
""",
    topics=("beta", "gamma"),
)((_landed_setup, _landed_check))


def _cross_setup(lab: Lab) -> None:
    set_line(lab.fork / "config.txt", "k2", "alpha-for-beta")
    write(
        lab.fork / "beta.py",
        (lab.fork / "beta.py").read_text() + "K2 = 'alpha-for-beta'\n",
    )
    pj(lab.fork, "describe", "-m", "beta: read k2 as alpha sets it")


def _cross_check(lab: Lab, s: State) -> list[str]:
    bad = (
        file_in(s, "beta", "config.txt", "k2 = alpha-for-beta")
        + file_in(s, "beta", "beta.py", "alpha-for-beta")
        + wc_is_empty(s)
    )
    if s.subject.get(s.bookmarks.get("beta")) != "beta: read k2 as alpha sets it":
        bad.append("beta's tip is not 'beta: read k2 as alpha sets it'")
    if "alpha-for-beta" in s.files.get(s.bookmarks.get("alpha"), {}).get(
        "config.txt", ""
    ):
        bad.append("the change leaked into alpha")
    return bad


scenario(
    "cross-lane",
    """
The working copy holds a finished commit, "beta: read k2 as alpha sets
it". It belongs on the beta topic as its own commit, but it changes the
line `k2` in config.txt that the alpha topic sets. Put it on beta.
Leave alpha's own commits as they are, leave no conflicts, and leave the
working copy empty on top of the octopus.
""",
    stacked={"beta": "alpha"},
)((_cross_setup, _cross_check))


# -- entry points -----------------------------------------------------------


def build(name: str, dest: Path) -> Lab:
    sc = SCENARIOS[name]
    lab = build_base(dest)
    sc.setup(lab)
    pj(lab.fork, "status")
    return lab


def check(name: str, dest: Path) -> list[str]:
    sc = SCENARIOS[name]
    lab = Lab(dest)
    state = read_state(lab)
    return base_expectations(state, sc.topics, sc.stacked) + sc.check(lab, state)


def main(argv: list[str]) -> int:
    match argv:
        case ["list"]:
            for sc in SCENARIOS.values():
                print(f"{sc.name}: {sc.task.splitlines()[0]}")
            return 0
        case ["task", name]:
            print(SCENARIOS[name].task)
            return 0
        case ["build", name, dest]:
            path = Path(dest).resolve()
            if path.exists():
                shutil.rmtree(path)
            build(name, path)
            print(path / "fork")
            return 0
        case ["check", name, dest]:
            bad = check(name, Path(dest).resolve())
            for line in bad:
                print(line)
            return 1 if bad else 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
