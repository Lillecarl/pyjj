"""flip: reverse a three-commit stack, all from one stdin script.

Forces `pyjj python -` (heredoc on stdin) rather than a script file:
the whole job -- resolving the commits, moving them, retargeting the
bookmark -- happens inside a single script read from stdin, in a
single atomic block. The outcome check (one operation, reversed
order, intact contents) is the grade; the stdin form is the exercise.
"""

TITLE = "reverse a stack from a single stdin script"

DESCRIPTION = "ctf flip"


def setup(ctx):
    ctx.git_init(ctx.work)
    ctx.write(f"{ctx.work}/base.txt", "base\n")
    ctx.cli("commit", "-m", "base")
    ctx.cli("bookmark", "create", "main", "-r", "@-")
    # `commit` describes @ and opens a fresh empty child on top, so
    # each loop turn's file lands in a new commit with no `new` needed.
    ctx.cli("new", "main")
    for name, word in (("a.txt", "first"), ("b.txt", "second"),
                       ("c.txt", "third")):
        ctx.write(f"{ctx.work}/{name}", name + "\n")
        ctx.cli("commit", "-m", word)
    ctx.cli("bookmark", "create", "tip", "-r", "@-")


PROMPT = """The repo holds `main` with a linear stack of three commits on
it: "first" (a.txt), "second" (b.txt), "third" (c.txt), bookmark `tip`
on the top.

Goal: reverse the stack so "third" sits on `main` and "first" is on
top, with `tip` following to the new top and all file contents intact.
Do it all from a single script fed on stdin:

    {pyjj} -R {work} python - <<'EOF'
    ... one repo.atomic(\"""" + DESCRIPTION + """") block ...
    EOF

Requirements: exactly one new operation described exactly \"""" + DESCRIPTION + """",
linear reversed order, no conflicts.
"""


def check(ctx):
    failures = []
    repo = ctx.open()
    try:
        tip = repo.resolve("tip")
        main = repo.resolve("main")
    except Exception as e:  # noqa: BLE001 -- resolution is the check
        return [f"cannot resolve tip/main: {e}"]
    try:
        first = tip
        if first.description.strip() != "first":
            failures.append(f"tip is {first.description.strip()!r}, "
                            "want 'first'")
        second = repo._repo.get_commit(first.parent_ids[0])
        if second.description.strip() != "second":
            failures.append(f"under tip is {second.description.strip()!r}, "
                            "want 'second'")
        third = repo._repo.get_commit(second.parent_ids[0])
        if third.description.strip() != "third":
            failures.append(f"third down is {third.description.strip()!r}, "
                            "want 'third'")
        if [p.hex() for p in third.parent_ids] != [main.id.hex()]:
            failures.append("'third' does not sit on main")
        for name in ("a.txt", "b.txt", "c.txt"):
            if tip.read_file(name) != f"{name}\n".encode():
                failures.append(f"{name} content changed at the tip")
    except Exception as e:  # noqa: BLE001
        failures.append(f"cannot walk the stack: {e}")
    if repo.revset("conflicts()"):
        failures.append("conflicts present")
    ops = [op.description for op in repo._repo.operation_log()
           if op.description == DESCRIPTION]
    if len(ops) != 1:
        failures.append(f"{len(ops)} operations described {DESCRIPTION!r}, "
                        "want exactly 1 (one atomic block)")
    return failures
