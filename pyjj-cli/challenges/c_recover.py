"""recover: a bad abandon deleted real work; find it in the op log."""

TITLE = "recover an abandoned topic via op restore"


def setup(ctx):
    ctx.git_init(ctx.work)
    ctx.write(f"{ctx.work}/base.txt", "base\n")
    ctx.cli("commit", "-m", "base")
    ctx.cli("bookmark", "create", "main", "-r", "@-")
    ctx.cli("new", "main", "-m", "topic with real work")
    ctx.write(f"{ctx.work}/topic.txt", "work\n")
    ctx.cli("bookmark", "create", "topic", "-r", "@")
    # The accident: abandon the topic, then delete its bookmark, so the
    # commit is hidden and nothing names it anymore.
    ctx.cli("abandon", "topic")
    ctx.cli("bookmark", "delete", "topic")


PROMPT = """The repo holds `main`, and did hold a `topic` bookmark with real
work (topic.txt) -- but someone ran `abandon` on it and deleted the
bookmark. The commit is hidden and nothing names it now.

Goal: get the topic back, exactly as it was:

- bookmark `topic` exists again and names the recovered commit.
- topic.txt reads "work".
- the recovered commit sits on `main`, with no conflicts.
"""


def check(ctx):
    failures = []
    repo = ctx.open()
    try:
        topic = repo.resolve("topic")
        main = repo.resolve("main")
    except Exception as e:  # noqa: BLE001 -- resolution is the check
        return [f"cannot resolve topic/main: {e}"]
    try:
        if topic.read_file("topic.txt") != b"work\n":
            failures.append("topic.txt content is not the original work")
    except Exception as e:  # noqa: BLE001
        failures.append(f"cannot read topic.txt: {e}")
    if [p.hex() for p in topic.parent_ids] != [main.id.hex()]:
        failures.append("topic is not parented on main")
    if repo.revset("conflicts()"):
        failures.append("conflicts present")
    return failures
