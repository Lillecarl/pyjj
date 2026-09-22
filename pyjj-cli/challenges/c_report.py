"""report: query the repo from a script and write a JSON report.

Exercises `pyjj python` for querying: the question is structural (every
bookmark's commit, description and file list), which is one loop over
the session API and an awkward template.
"""

TITLE = "report every bookmark via a pyjj python script"

REPORT = "report.json"


def setup(ctx):
    ctx.git_init(ctx.work)
    ctx.write(f"{ctx.work}/base.txt", "base\n")
    ctx.cli("commit", "-m", "base commit")
    ctx.cli("bookmark", "create", "main", "-r", "@-")
    ctx.cli("new", "main", "-m", "add alpha")
    ctx.write(f"{ctx.work}/alpha.txt", "alpha\n")
    ctx.cli("bookmark", "create", "alpha", "-r", "@")
    ctx.cli("new", "main", "-m", "add beta")
    ctx.write(f"{ctx.work}/beta.txt", "beta\n")
    ctx.write(f"{ctx.work}/shared.txt", "shared\n")
    ctx.cli("bookmark", "create", "beta", "-r", "@")


PROMPT = """The repo holds `main` with two topics off it (`alpha`,
`beta`), each adding files.

Goal: write a `pyjj python` script (run it with `{pyjj} -R {work}
python <script>`) that queries the repo through the session API and
writes `{arena}/""" + REPORT + """` as JSON of this shape:

    {{"<bookmark>": {{"commit": "<full hex>",
                      "description": "<first line>",
                      "files": ["sorted", "full", "file", "list"]}}}}

One entry per local bookmark. `files` is the commit's whole file list,
sorted. `description` is the first line of the commit's description.
"""


def _expected(ctx):
    import pyjj_bindings as bindings

    settings = bindings.UserSettings()
    ws = bindings.Workspace.load(settings, ctx.work)
    repo = ws.load_at_head()
    expected = {}
    for mark in repo.bookmarks():
        if mark.has_conflict or len(mark.target_ids) != 1:
            raise RuntimeError(f"bookmark {mark.name} is conflicted")
        commit = repo.get_commit(mark.target_ids[0])
        description = commit.description
        if callable(description):
            description = description()
        expected[mark.name] = {
            "commit": mark.target_ids[0].hex(),
            "description": description.splitlines()[0] if description else "",
            "files": sorted(commit.list_files()),
        }
    return expected


def check(ctx):
    import json
    import os

    path = os.path.join(ctx.arena, REPORT)
    if not os.path.exists(path):
        return [f"{REPORT} was not written"]
    try:
        with open(path, encoding="utf-8") as handle:
            got = json.load(handle)
    except (OSError, ValueError) as e:
        return [f"{REPORT} is not valid JSON: {e}"]
    try:
        expected = _expected(ctx)
    except Exception as e:  # noqa: BLE001 -- repo state is the check
        return [f"cannot read repo state: {e}"]
    failures = []
    if set(got) != set(expected):
        return [f"bookmarks {sorted(got)} != {sorted(expected)}"]
    for name in expected:
        for field in ("commit", "description", "files"):
            if got[name].get(field) != expected[name][field]:
                failures.append(f"{name}.{field}: {got[name].get(field)!r} "
                                f"!= {expected[name][field]!r}")
    return failures
