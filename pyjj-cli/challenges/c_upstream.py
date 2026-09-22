"""upstream: fetch a moved upstream main and rebase a local topic onto it."""

TITLE = "fetch upstream main and rebase a local topic onto it"


def setup(ctx):
    ctx.git_init(ctx.upstream)
    ctx.write(f"{ctx.upstream}/app.txt", "v1\n")
    ctx.cli("commit", "-m", "app v1", repo=ctx.upstream)
    ctx.cli("bookmark", "create", "main", "-r", "@-", repo=ctx.upstream)
    # The local clone, with its own topic on the old main.
    ctx.raw("git", "clone", ctx.upstream, ctx.work)
    ctx.cli("new", "main", "-m", "local topic")
    ctx.write(f"{ctx.work}/topic.txt", "local\n")
    ctx.cli("bookmark", "create", "topic", "-r", "@")
    # Upstream moves on without us.
    ctx.cli("new", "main", "-m", "upstream v2", repo=ctx.upstream)
    ctx.write(f"{ctx.upstream}/app.txt", "v2\n")
    ctx.cli("commit", "-m", "upstream v2", repo=ctx.upstream)
    ctx.cli("bookmark", "set", "main", "-r", "@-", repo=ctx.upstream)


PROMPT = """The repo is a clone of the upstream at {upstream} (remote
`origin`). Since cloning, upstream's `main` moved from app.txt "v1" to
"v2", and this repo holds a local `topic` commit (topic.txt) still
sitting on the old main.

Goal: bring the upstream movement in and restack the local work on it:

- fetch from `origin`.
- rebase `topic` onto the fetched upstream `main`.
- topic.txt keeps "local"; the rebased topic's app.txt reads "v2".
- no conflicts.
"""


def check(ctx):
    failures = []
    repo = ctx.open()
    try:
        topic = repo.resolve("topic")
    except Exception as e:  # noqa: BLE001 -- resolution is the check
        return [f"cannot resolve topic: {e}"]
    try:
        if topic.read_file("topic.txt") != b"local\n":
            failures.append("topic.txt content changed")
        if topic.read_file("app.txt") != b"v2\n":
            failures.append("topic is not on the new upstream main")
    except Exception as e:  # noqa: BLE001
        failures.append(f"cannot read topic files: {e}")
    if repo.revset("conflicts()"):
        failures.append("conflicts present")
    return failures
