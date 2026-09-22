"""splice: move a commit between a parent and a merge.

The pyterm shape: a commit grown elsewhere belongs between one parent
of a merge and the merge itself, so the merge takes it in place of
that parent. One rebase does it -- the trick is knowing which one.
"""

TITLE = "splice a commit between a merge parent and the merge"


def setup(ctx):
    ctx.git_init(ctx.work)
    ctx.write(f"{ctx.work}/base.txt", "base\n")
    ctx.cli("commit", "-m", "base")
    ctx.cli("bookmark", "create", "main", "-r", "@-")
    for topic in ("p1", "p2", "c"):
        ctx.cli("new", "main", "-m", topic)
        ctx.write(f"{ctx.work}/{topic}.txt", topic + "\n")
        ctx.cli("bookmark", "create", topic, "-r", "@")
    ctx.cli("new", "p1", "p2", "-m", "merge")
    ctx.cli("bookmark", "create", "m", "-r", "@")


PROMPT = """The repo holds `main` with three commits off it (`p1`, `p2`,
`c`, each with its own file) and a merge `m` joining `p1` and `p2`.

Goal: `c` belongs between `p2` and the merge -- move it there so that:

- `c` sits directly on `p2`.
- the merge's parents are `p1` and the moved `c` (nothing else).
- every file keeps its contents; the merge tree holds base.txt,
  p1.txt, p2.txt and c.txt.
- bookmarks follow their commits; no conflicts.

Do it in as few operations as you can; the skill's rebase section and
`rebase --help` know the spelling.
"""


def check(ctx):
    failures = []
    repo = ctx.open()
    try:
        p1 = repo.resolve("p1")
        p2 = repo.resolve("p2")
        c = repo.resolve("c")
        m = repo.resolve("m")
    except Exception as e:  # noqa: BLE001 -- resolution is the check
        return [f"cannot resolve bookmarks: {e}"]
    if [p.hex() for p in c.parent_ids] != [p2.id.hex()]:
        failures.append("c does not sit directly on p2")
    if sorted(p.hex() for p in m.parent_ids) != sorted(
            [p1.id.hex(), c.id.hex()]):
        failures.append("the merge is not parented on p1 and the moved c")
    try:
        for name in ("base.txt", "p1.txt", "p2.txt", "c.txt"):
            want = "base\n" if name == "base.txt" else f"{name[:-4]}\n"
            if m.read_file(name) != want.encode():
                failures.append(f"merge tree's {name} is wrong")
        if c.read_file("c.txt") != b"c\n":
            failures.append("c lost its file")
    except Exception as e:  # noqa: BLE001
        failures.append(f"cannot read trees: {e}")
    if repo.revset("conflicts()"):
        failures.append("conflicts present")
    return failures
