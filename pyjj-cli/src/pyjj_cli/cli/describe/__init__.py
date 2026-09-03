# cli/describe package — describes + new/edit/commit/diffedit/resolve/sign/unsign/metaedit/version/root
# Split from the old 83-line monolith where `describe.py:add_parsers` registered 11 unrelated top-level commands.


def add_parsers(sub) -> None:
    from . import commit, describe, diffedit, edit, metaedit, new, resolve, root, sign, unsign, version

    describe.register(sub)
    new.register(sub)
    edit.register(sub)
    commit.register(sub)
    diffedit.register(sub)
    resolve.register(sub)
    sign.register(sub)
    unsign.register(sub)
    metaedit.register(sub)
    version.register(sub)
    root.register(sub)
