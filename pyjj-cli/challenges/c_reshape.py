"""reshape: describe a stack and move a bookmark in ONE operation.

Exercises `repo.atomic` for transactional multi-operation mutation: no
single CLI command describes three commits and moves a bookmark, so
three CLI calls would cost three operations. One script block costs one.
"""

TITLE = "describe a stack and move a bookmark in one atomic block"

DESCRIPTION = "ctf reshape"


def setup(ctx):
    ctx.git_init(ctx.work)
    ctx.write(f"{ctx.work}/base.txt", "base\n")
    ctx.cli("commit", "-m", "base")
    ctx.cli("bookmark", "create", "main", "-r", "@-")
    for name in ("f1.txt", "f2.txt", "f3.txt"):
        # `@`: the file just written snapshots into the current commit,
        # so the new commit hangs off the one holding the previous file.
        # (`@-` would name the grandparent here and fork siblings.)
        ctx.cli("new", "main" if name == "f1.txt" else "@")
        ctx.write(f"{ctx.work}/{name}", name + "\n")
    ctx.cli("bookmark", "create", "release", "-r", "@")
    ctx.cli("new", "@", "-m", "keepalive")


PROMPT = """The repo holds `main` with a stack of three undescribed commits
on it (f1.txt, f2.txt, f3.txt), bookmark `release` on the top, and an
empty keepalive commit above that.

Goal, all in a single operation: give the three stack commits the
descriptions "one", "two", "three" (bottom to top) and move `release`
onto the middle commit ("two"). Write a `pyjj python` script that does
it in one `repo.atomic("""" + DESCRIPTION + """")` block -- the operation
description must be exactly \"""" + DESCRIPTION + """". Run it with
`{pyjj} -R {work} python <script>`.
"""


def _single_parent(repo, commit):
    if len(commit.parent_ids) != 1:
        raise RuntimeError(f"{commit.description!r} has "
                           f"{len(commit.parent_ids)} parents")
    return repo.get_commit(commit.parent_ids[0])


def check(ctx):
    import pyjj_bindings as bindings

    failures = []
    settings = bindings.UserSettings()
    ws = bindings.Workspace.load(settings, ctx.work)
    repo = ws.load_at_head()
    try:
        release = repo.get_bookmark("release")
        main = repo.get_bookmark("main")
    except Exception as e:  # noqa: BLE001 -- repo state is the check
        return [f"cannot load repo: {e}"]
    if release is None or len(release.target_ids) != 1:
        return ["bookmark release is missing or conflicted"]
    if main is None or len(main.target_ids) != 1:
        return ["bookmark main is missing or conflicted"]
    try:
        second = repo.get_commit(release.target_ids[0])
        if second.description != "two":
            failures.append(f"release names {second.description!r}, "
                            "want 'two'")
        first = _single_parent(repo, second)
        if first.description != "one":
            failures.append(f"commit under release is {first.description!r}, "
                            "want 'one'")
        if _single_parent(repo, first).id.hex() != main.target_ids[0].hex():
            failures.append("the described stack does not sit on main")
        kids = [repo.get_commit(c.id).description
                for c in repo.revset(settings, "release+")]
        if "three" not in kids:
            failures.append(f"no commit described 'three' above release "
                            f"(children: {kids})")
    except Exception as e:  # noqa: BLE001
        failures.append(f"cannot walk the stack: {e}")
    ops = [op.description for op in repo.operation_log()
           if op.description == DESCRIPTION]
    if len(ops) != 1:
        failures.append(f"{len(ops)} operations described {DESCRIPTION!r}, "
                        "want exactly 1 (one atomic block)")
    # Colocated git export: a tracked `name@git` must follow the local
    # target the way the CLI's transaction-finish keeps them. A script
    # that rewrites without exporting leaves them stale behind it.
    locals_ = {mark.name: [i.hex() for i in mark.target_ids]
               for mark in repo.bookmarks()}
    for remote in repo.remote_bookmarks():
        if not remote.tracked:
            continue
        want = locals_.get(remote.name)
        got = [i.hex() for i in remote.target_ids]
        if want is not None and got != want:
            failures.append(f"{remote.name}@{remote.remote} names "
                            f"{got}, want the local target {want}")
    return failures
