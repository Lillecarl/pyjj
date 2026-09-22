"""fixup: fold a working-copy fix back into its parent commit."""

TITLE = "squash a working-copy fix into its parent"


def setup(ctx):
    ctx.git_init(ctx.work)
    ctx.write(f"{ctx.work}/feat.txt", "v1\n")
    ctx.cli("commit", "-m", "feature")
    ctx.cli("bookmark", "create", "main", "-r", "@-")
    ctx.write(f"{ctx.work}/feat.txt", "v2\n")


PROMPT = """The repo holds one commit `feature` (bookmarked `main`) with
feat.txt at "v1", and the working copy on top edits feat.txt to "v2".

Goal: the fix belongs in `feature` itself, not in a new commit. Move
the working-copy change back into its parent so that:

- the `main` commit's feat.txt reads "v2".
- the working-copy commit is empty (no diff against its parent).
"""


def check(ctx):
    failures = []
    repo = ctx.open()
    try:
        main = repo.resolve("main")
        wc = repo.resolve("@")
    except Exception as e:  # noqa: BLE001 -- resolution is the check
        return [f"cannot resolve main/@: {e}"]
    try:
        if main.read_file("feat.txt") != b"v2\n":
            failures.append("main's feat.txt is not the fixed content")
    except Exception as e:  # noqa: BLE001
        failures.append(f"cannot read feat.txt on main: {e}")
    if [p.hex() for p in wc.parent_ids] != [main.id.hex()]:
        failures.append("@ is not a child of main")
    try:
        if wc.diff(main):
            failures.append("working copy still carries a diff")
    except Exception as e:  # noqa: BLE001
        failures.append(f"cannot diff @ against main: {e}")
    return failures
