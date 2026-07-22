#!/usr/bin/env python3
"""Render pyjjui to an SVG or PNG for visual review.

Builds a small demo repo (via pyjjui/tests/testutils.py -- the same factory
the test suite's fixtures use, not reimplemented here) and takes a Textual
SVG screenshot of the running app, optionally converting it to PNG with
cairosvg. cairosvg specifically, not resvg: resvg's SVG parser rejects the
`clip-path` syntax Rich's SVG export uses and silently drops all text,
cairosvg (backed by cairo, same engine librsvg uses) renders it correctly --
confirmed empirically, not assumed.

Usage (from the pyjjui devShell -- `nix develop .#pyjjui`):
    python pyjjui/tools/screenshot.py
    python pyjjui/tools/screenshot.py --scenario merge
    python pyjjui/tools/screenshot.py --press d
    python pyjjui/tools/screenshot.py --out /tmp/log.png   # explicit path, opts out of the dev dir

With no `--out`, writes a PNG named after the scenario/keys/timestamp into
`pyjjui/.dev/screenshots/` (gitignored) instead of overwriting a fixed file --
meant to be run over and over while iterating so nothing from the previous
render gets clobbered before it's been looked at.
"""

import argparse
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pyjj
from textual._doc import take_svg_screenshot

_DEV_SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent / ".dev" / "screenshots"

# testutils.py lives in pyjjui/tests/, not under pyjjui/src/pyjjui/ -- it's
# deliberately test-only code, not shipped as part of the installed
# `pyjjui` package, so it isn't importable as `pyjjui.tests.testutils` and
# needs this path insertion instead.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
import testutils  # noqa: E402

from pyjjui.app import PyjjuiApp  # noqa: E402


def _build_settings(config_dir: Path) -> pyjj.UserSettings:
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    testutils.write_config(config_file)
    os.environ["JJ_CONFIG"] = str(config_file)
    return pyjj.UserSettings()


def _scenario_seeded(tmp_path: Path) -> tuple[pyjj.Workspace, pyjj.UserSettings]:
    """The default demo: two described commits, `A` then `B` (checked out)."""
    settings = _build_settings(tmp_path / "cfg")
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    workspace, _repo = pyjj.Workspace.init_internal_git(settings, str(ws_dir))
    testutils.seed_repo(workspace, settings)
    return workspace, settings


def _scenario_merge(tmp_path: Path) -> tuple[pyjj.Workspace, pyjj.UserSettings]:
    """A diamond merge, for checking the multi-lane graph layout."""
    settings = _build_settings(tmp_path / "cfg")
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    workspace, repo = pyjj.Workspace.init_internal_git(settings, str(ws_dir))
    root = repo.resolve_single(settings, "@")
    repo, a = testutils.new_child(workspace, repo, settings, root, "A")
    repo, b = testutils.new_child(workspace, repo, settings, a, "B (feature)")
    repo, c = testutils.new_child(workspace, repo, settings, a, "C (other branch)")

    tx = repo.start_transaction(settings)
    builder = tx.new_commit(settings, [b.id, c.id])
    builder.set_description("merge B+C")
    builder.set_author(testutils.FIXED_SIGNATURE)
    builder.set_committer(testutils.FIXED_SIGNATURE)
    merge_commit = builder.write(repo)
    tx.edit(workspace.workspace_name, merge_commit)
    tx.rebase_descendants()
    repo = tx.commit("merge")
    workspace.check_out(repo, merge_commit)
    return workspace, settings


_SCENARIOS = {
    "seeded": _scenario_seeded,
    "merge": _scenario_merge,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path (.svg or .png); defaults to an auto-named file under pyjjui/.dev/screenshots/",
    )
    parser.add_argument("--press", action="append", default=[], help="Key(s) to press before capturing; repeatable")
    parser.add_argument("--revset", default="all()")
    parser.add_argument(
        "--size",
        default="80x24",
        help="WIDTHxHEIGHT in terminal cells (default matches Pilot.run_test()'s own"
        " default -- keep it that small unless a scenario genuinely needs more width/height;"
        " bigger terminals mean bigger PNGs for no more signal)",
    )
    parser.add_argument("--scenario", choices=sorted(_SCENARIOS), default="seeded")
    parser.add_argument(
        "--scale",
        type=float,
        default=0.25,
        help="cairosvg raster scale (default 0.25): these renders are for checking layout"
        " -- panels, borders, row highlights, footer key-hint colors -- not for reading text,"
        " so text can blur without losing the thing actually being reviewed. Pass --scale 1"
        " for a crisp/legible render when you do need to read specific text.",
    )
    args = parser.parse_args()

    width_str, _, height_str = args.size.lower().partition("x")
    terminal_size = (int(width_str), int(height_str))

    out = args.out
    if out is None:
        keys = "_".join(args.press) or "noop"
        stamp = datetime.now().strftime("%H%M%S%f")
        _DEV_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        out = _DEV_SCREENSHOTS_DIR / f"{args.scenario}-{keys}-{stamp}.png"

    with tempfile.TemporaryDirectory() as tmp:
        workspace, settings = _SCENARIOS[args.scenario](Path(tmp))
        app = PyjjuiApp(workspace=workspace, settings=settings, revset=args.revset)
        svg = take_svg_screenshot(app=app, press=args.press, terminal_size=terminal_size)

    if out.suffix == ".png":
        import cairosvg

        cairosvg.svg2png(bytestring=svg.encode(), write_to=str(out), scale=args.scale)
    else:
        out.write_text(svg)

    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
