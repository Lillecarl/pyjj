"""Records what real `jj` prints for every catalogue entry.

Run it when the catalogue grows, or when the pinned jj changes:

    nix run --file . tests -- -q -k test_capture_the_corpus --capture-corpus

The goldens are committed. That is the point: a recapture under a
different jj shows up as a diff to read rather than as a silent change,
and `manifest.json` records which jj produced them so the difference is
never a mystery.

Capture uses `--color=debug`, which wraps every span as
`<<label stack::text>>`. One capture therefore carries all three
renderings, and the strip-equality that makes that true is asserted here
rather than assumed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import COLOUR_SUFFIX, GOLDEN_SUFFIX, PLAIN_SUFFIX, normalize, strip_markers
from .catalogue import CATALOGUE
from .fixtures import FIXTURES

GOLDENS = Path(__file__).with_name("goldens")
MANIFEST = Path(__file__).with_name("manifest.json")


def _op_ids(jj_bin: str, repo: Path, env: dict) -> list[str]:
    out = subprocess.run(
        [jj_bin, "-R", str(repo), "--no-pager", "--ignore-working-copy",
         "op", "log", "--no-graph", "-T", 'self.id() ++ "\n"'],
        env=env, capture_output=True, text=True, cwd=str(repo),
    )
    return [line for line in out.stdout.splitlines() if line]


def run_jj(pair, argv, colour: str) -> str:
    """One read-only invocation against the pair's jj-driven repo."""
    env = pair._env(bump=False)
    proc = subprocess.run(
        [pair.jj_bin, "-R", str(pair.cli_repo), "--no-pager",
         "--ignore-working-copy", f"--color={colour}", *argv],
        env=env, capture_output=True, text=True, cwd=str(pair.cli_repo),
        stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"jj failed ({proc.returncode}) on {list(argv)}\n{proc.stderr}"
        )
    return proc.stdout


def capture(pair_factory) -> dict:
    """Captures every entry, one fixture build per fixture.

    `pair_factory(name)` returns a fresh `RepoPair` for a fixture.
    """
    GOLDENS.mkdir(exist_ok=True)
    written = {}
    unlabelled: list[str] = []
    for name in sorted({entry.fixture for entry in CATALOGUE}):
        pair = pair_factory(name)
        FIXTURES[name](pair)
        env = pair._env(bump=False)
        context = {
            "repo": pair.cli_repo,
            "op_ids": _op_ids(pair.jj_bin, pair.cli_repo, env),
            # Set by a fixture that builds one; see `_normalize_remote`.
            "remote": getattr(pair, "remote", None),
        }
        for entry in CATALOGUE:
            if entry.fixture != name:
                continue
            debug = run_jj(pair, entry.argv, "debug")
            always = run_jj(pair, entry.argv, "always")
            never = run_jj(pair, entry.argv, "never")
            # Strip the markers from the debug form and you should have
            # exactly what a terminal shows. Where that fails, the
            # output's own text closed a marker early -- a conflicted
            # file contains `>>>>>>>` -- and jj's debug format cannot
            # express it. Record the coloured rendering instead of a
            # label specification that would be wrong.
            labelled = strip_markers(debug) == always
            debug_path = GOLDENS / f"{entry.id}{GOLDEN_SUFFIX}"
            colour_path = GOLDENS / f"{entry.id}{COLOUR_SUFFIX}"
            debug_path.unlink(missing_ok=True)
            colour_path.unlink(missing_ok=True)
            if labelled:
                debug_path.write_text(normalize(debug, entry.normalize, context))
            else:
                unlabelled.append(entry.id)
                colour_path.write_text(normalize(always, entry.normalize, context))
            # The plain rendering is captured, never derived. jj's
            # colour-words diff changes shape when colour is off (see the
            # package docstring), so stripping the ANSI would record an
            # output jj does not produce.
            text = normalize(never, entry.normalize, context)
            (GOLDENS / f"{entry.id}{PLAIN_SUFFIX}").write_text(text)
            written[entry.id] = text
    MANIFEST.write_text(json.dumps({
        "jj": _jj_version(pair.jj_bin),
        "captured": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "entries": len(written),
        # Entries whose output collides with jj's own debug marker
        # syntax, so they carry no label specification.
        "unlabelled": sorted(unlabelled),
    }, indent=2, sort_keys=True) + "\n")
    return written


def _jj_version(jj_bin: str) -> str:
    out = subprocess.run([jj_bin, "--version"], capture_output=True, text=True)
    return out.stdout.strip()
