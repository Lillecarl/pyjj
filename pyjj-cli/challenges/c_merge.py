"""merge: land three parallel branches in one merge commit.

The landing side of parallel agent work: three branches grown off the
same base, joined by a single merge. No rewrites of the branches
themselves -- the merge is one new commit, so the heads stay byte for
byte what they were.
"""

TITLE = "land three branches in one merge commit"


def setup(ctx):
    ctx.git_init(ctx.work)
    ctx.write(f"{ctx.work}/base.txt", "base\n")
    ctx.cli("commit", "-m", "base")
    ctx.cli("bookmark", "create", "main", "-r", "@-")
    for name in ("g1", "g2", "g3"):
        ctx.cli("new", "main", "-m", f"branch {name}")
        ctx.write(f"{ctx.work}/{name}.txt", name + "\n")
        ctx.cli("bookmark", "create", name, "-r", "@")


PROMPT = """The repo holds `main` with three independent branches off it:
`g1` (g1.txt), `g2` (g2.txt), `g3` (g3.txt).

Goal: land all three in a single merge commit without rewriting any
branch:

- one new commit described "merge all", whose parents are exactly the
  three branch heads.
- its tree holds base.txt plus g1.txt, g2.txt and g3.txt with their
  contents.
- bookmark `merged` on the merge commit; `g1`, `g2`, `g3` and `main`
  untouched; no conflicts.
"""


def check(ctx):
    failures = []
    repo = ctx.open()
    try:
        heads = [repo.resolve(name) for name in ("g1", "g2", "g3")]
        merged = repo.resolve("merged")
        main = repo.resolve("main")
    except Exception as e:  # noqa: BLE001 -- resolution is the check
        return [f"cannot resolve bookmarks: {e}"]
    want = sorted(c.id.hex() for c in heads)
    if sorted(p.hex() for p in merged.parent_ids) != want:
        failures.append("merge commit is not parented on the three heads")
    if merged.description.strip() != "merge all":
        failures.append(f"merge is described {merged.description.strip()!r}")
    try:
        for name in ("base.txt", "g1.txt", "g2.txt", "g3.txt"):
            want_content = "base\n" if name == "base.txt" else \
                f"{name[:-4]}\n"
            if merged.read_file(name) != want_content.encode():
                failures.append(f"merge tree's {name} is wrong")
    except Exception as e:  # noqa: BLE001
        failures.append(f"cannot read merge tree: {e}")
    if repo.revset("conflicts()"):
        failures.append("conflicts present")
    return failures
