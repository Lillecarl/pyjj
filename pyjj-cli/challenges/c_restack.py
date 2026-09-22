"""restack: stack topic `a` onto topic `b` with the graph workflow."""

TITLE = "stack topic a onto topic b via graph plan/apply"


def setup(ctx):
    ctx.git_init(ctx.work)
    ctx.write(f"{ctx.work}/base.txt", "base\n")
    ctx.cli("commit", "-m", "base")
    ctx.cli("bookmark", "create", "main", "-r", "@-")
    for topic in ("a", "b"):
        ctx.cli("new", "main", "-m", f"topic {topic}")
        ctx.write(f"{ctx.work}/{topic}.txt", topic + "\n")
        ctx.cli("bookmark", "create", topic, "-r", "@")
    ctx.cli("new", "b", "-m", "keepalive")


PROMPT = """The repo holds `main` with two independent topics off it: `a`
(file a.txt) and `b` (file b.txt), plus a keepalive commit on `b`.

Goal: reorganize history so topic `a` sits directly on top of topic `b`
(`b` stays on `main`). Use the skill's reshape workflow: export the
graph, edit it, preview the plan, then apply. Requirements:

- bookmark `a` follows its commit; bookmark `b` is untouched.
- no conflicts anywhere afterwards.
- a.txt and b.txt keep their contents.
"""


def check(ctx):
    failures = []
    repo = ctx.open()
    try:
        a = repo.resolve("a")
        b = repo.resolve("b")
        main = repo.resolve("main")
    except Exception as e:  # noqa: BLE001 -- resolution is the check
        return [f"cannot resolve a/b/main: {e}"]
    if [p.hex() for p in a.parent_ids] != [b.id.hex()]:
        failures.append("a is not parented on b")
    if [p.hex() for p in b.parent_ids] != [main.id.hex()]:
        failures.append("b is not parented on main")
    try:
        if a.read_file("a.txt") != b"a\n":
            failures.append("a.txt content changed")
        if b.read_file("b.txt") != b"b\n":
            failures.append("b.txt content changed")
    except Exception as e:  # noqa: BLE001
        failures.append(f"cannot read topic files: {e}")
    if repo.revset("conflicts()"):
        failures.append("conflicts present")
    return failures
