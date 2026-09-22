"""parallel: turn a three-commit stack into siblings.

The AI-agent shape: three lines of work built as a stack, then fanned
out so each stands on its own. `parallelize` moves every target onto
the parents the chain hung from and reparents whatever followed onto
all of them at once (a merge). Disjoint files throughout, so any
conflict is the solver's own doing.
"""

TITLE = "parallelize a stack into siblings"


def setup(ctx):
    ctx.git_init(ctx.work)
    ctx.write(f"{ctx.work}/base.txt", "base\n")
    ctx.cli("commit", "-m", "base")
    ctx.cli("bookmark", "create", "main", "-r", "@-")
    ctx.cli("new", "main")
    for name in ("f1.txt", "f2.txt", "f3.txt"):
        ctx.write(f"{ctx.work}/{name}", name + "\n")
        ctx.cli("commit", "-m", name)
        ctx.cli("bookmark", "create", name, "-r", "@-")
    ctx.cli("new", "@-", "-m", "follower")
    ctx.write(f"{ctx.work}/f4.txt", "f4.txt\n")
    ctx.cli("bookmark", "create", "follower", "-r", "@")


PROMPT = """The repo holds `main` with a linear stack of three commits on
it (`f1.txt`, `f2.txt`, `f3.txt`, bookmarked the same names) and a
`follower` commit (f4.txt) on top of the stack.

Goal: fan the three stack commits out so each sits directly on
`main`, with `follower` reparented onto all three at once:

- `f1.txt`, `f2.txt`, `f3.txt` each name a commit whose only parent is
  `main`, holding its own file (and base.txt).
- `follower` has exactly those three commits as parents and carries
  f4.txt.
- bookmarks follow their commits; no conflicts.
"""


def check(ctx):
    failures = []
    repo = ctx.open()
    try:
        main = repo.resolve("main")
        subs = [repo.resolve(name) for name in ("f1.txt", "f2.txt", "f3.txt")]
        follower = repo.resolve("follower")
    except Exception as e:  # noqa: BLE001 -- resolution is the check
        return [f"cannot resolve bookmarks: {e}"]
    for commit, name in zip(subs, ("f1.txt", "f2.txt", "f3.txt")):
        if [p.hex() for p in commit.parent_ids] != [main.id.hex()]:
            failures.append(f"{name} does not sit directly on main")
        try:
            if commit.read_file(name) != f"{name}\n".encode():
                failures.append(f"{name} lost its own file")
        except Exception as e:  # noqa: BLE001
            failures.append(f"cannot read {name}: {e}")
    want_parents = sorted(c.id.hex() for c in subs)
    if sorted(p.hex() for p in follower.parent_ids) != want_parents:
        failures.append("follower is not parented on all three siblings")
    try:
        if follower.read_file("f4.txt") != b"f4.txt\n":
            failures.append("follower lost f4.txt")
    except Exception as e:  # noqa: BLE001
        failures.append(f"cannot read f4.txt: {e}")
    if repo.revset("conflicts()"):
        failures.append("conflicts present")
    return failures
