"""skill subcommand: path — where the bundled agent skill lives.

The skill ships at `share/skills/pyjj-cli/<name>/SKILL.md` (the nixpkgs
FHS layout), but no running process can guess that prefix: a combined
Python env does not merge `share/`, and a source checkout has no
`$out` at all. So the build writes its own skill directory into
`skill_dir.txt` beside the installed package, and a checkout falls
back to its own `skills/` tree. Anything else is "not installed here",
said plainly rather than as a missing file.
"""
import sys
from pathlib import Path


def _installed_dir():
    """The skill directory the build recorded, or `None`."""
    try:
        from importlib.resources import files
        marker = files("pyjj_cli") / "skill_dir.txt"
        if marker.is_file():
            return Path(marker.read_text(encoding="utf-8").strip())
    except Exception:  # noqa: BLE001 -- any lookup failure is "not here"
        pass
    return None


def _checkout_dir():
    """The `skills/` tree of a source checkout, or `None`."""
    try:
        import pyjj_cli
        root = Path(pyjj_cli.__file__).resolve().parents[2]
        if (root / "pyproject.toml").is_file():
            return root / "skills"
    except Exception:  # noqa: BLE001 -- same as above
        pass
    return None


def locate(name: str) -> Path | None:
    """The installed `SKILL.md` for `name`, by any layout that has one."""
    for base in (_installed_dir(), _checkout_dir()):
        if base is None:
            continue
        candidate = base / name / "SKILL.md"
        if candidate.is_file():
            return candidate
    return None


def skill_path(args) -> int:
    name = getattr(args, "name", None) or "pyjj"
    found = locate(name)
    if found is None:
        print(f"Error: no skill {name!r} installed here "
              f"(looked under share/skills/pyjj-cli and the source tree)",
              file=sys.stderr)
        return 1
    print(str(found))
    return 0
