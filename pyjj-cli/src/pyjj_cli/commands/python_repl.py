"""`pyjj python`: run a script with pyjj importable.

The point is the environment, not the interpreter. pyjj is a native
extension with a closure of its own, so outside a Nix shell built for
it there is no `python3` that can `import pyjj` -- and an agent driving
this from a plain shell has no way to build one. The CLI carries that
closure already, so the CLI can lend it.

    pyjj python - <<'EOF'
    import pyjj
    with pyjj.open() as repo:
        with repo.atomic("tidy up") as tx:
            tx.squash("@", into="@-")
    EOF

The script starts with `pyjj`, `pyjj_bindings` and `repo` already
bound: `repo` is open on the `-R` path unless `--no-repo` says
otherwise, and the two modules are there either way. Nothing to
import, and nothing to get wrong on the first line.
"""
import sys

from .common import CommandError, _workspace_path


def python_repl(args) -> int:
    source = getattr(args, "file", None)
    script_args = list(getattr(args, "args", None) or [])

    if getattr(args, "source", None) is not None:
        text, name = args.source, "<pyjj python -c>"
    elif source in (None, "-"):
        text, name = sys.stdin.read(), "<pyjj python ->"
    else:
        try:
            with open(source, encoding="utf-8") as handle:
                text = handle.read()
        except OSError as e:
            print(f"Error: cannot read {source}: {e.strerror}",
                  file=sys.stderr)
            return 2
        name = source

    import pyjj
    import pyjj_bindings

    # Bound before anything can fail, and whatever `--no-repo` says: a
    # script that has to open with `import pyjj` first is a script an
    # agent gets wrong once per session for no reason.
    namespace = {
        "__name__": "__main__",
        "__file__": name,
        "pyjj": pyjj,
        "pyjj_bindings": pyjj_bindings,
        "repo": None,
    }
    if not getattr(args, "no_repo", False):
        try:
            namespace["repo"] = pyjj.open(_workspace_path(args))
        except Exception as e:  # noqa: BLE001
            # Not fatal: a script may be about to `git init`, or may
            # only want the API. It says so rather than failing here.
            print(f"Warning: no repository opened: "
                  f"{getattr(e, 'message', e)}", file=sys.stderr)

    # argv reads as it would for `python script.py a b`, so a script
    # can take arguments without knowing it was run this way.
    saved, sys.argv = sys.argv, [name, *script_args]
    try:
        exec(compile(text, name, "exec"), namespace)  # noqa: S102
    except SystemExit as e:
        return int(e.code or 0)
    except CommandError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        sys.argv = saved
    return 0
