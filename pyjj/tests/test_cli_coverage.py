"""Which of jj's subcommands and flags actually have a test behind them.

`cli_surface` reads the authoritative list out of `jj util
markdown-help`. Tests claim items off it with `@pytest.mark.covers`, and
the marks are gathered at collection time (see `conftest.py`). This
module compares the two.

The distinction from `test_cli_surface` matters. That one asks whether
pyjj-cli *parses* a flag, which is cheap to satisfy and easy to satisfy
falsely -- `jj diff --git` parsed for a long time while being ignored
outright. This one asks whether anything *exercises* it. A flag is only
really covered when a test would notice it breaking.

Byte-identical output is deliberately not the bar. A test claims a flag
by exercising it and asserting whatever is worth asserting about it:
that it changes the repository the way jj does, that it errors where jj
errors, or that it prints something the test checks. Matching jj's
formatting exactly is not required, and "equal or better" output is
fine.

The unclaimed list is recorded in `cli_coverage_baseline.json` and
asserted exactly, so it only shrinks on purpose -- the same discipline
`UNIMPLEMENTED` and the surface baseline use.

Regenerate after adding marks:

    nix run --file . tests -- --write-coverage-baseline

The whole suite has to be collected for that, since the marks come from
collection -- a `-k` run would record only the part it collected.
"""

import json
from pathlib import Path

import pytest

from parity import cli_surface

BASELINE = Path(__file__).parent / "parity" / "cli_coverage_baseline.json"


def test_no_stale_claims(coverage_marks):
    """Every `covers` mark names something jj has and is not excluded.

    A mark for a flag jj dropped, or for one the exclusion list already
    excuses, checks off nothing while making the ledger look smaller.
    """
    assert cli_surface.stale_claims(coverage_marks) == []


def test_coverage_matches_the_baseline(coverage_marks, coverage_is_complete,
                                       pytestconfig):
    """The unclaimed list is exactly what the baseline records."""
    if not coverage_is_complete:
        pytest.skip("-k/-m narrowed collection, so the marks seen are partial")
    measured = cli_surface.unclaimed(coverage_marks)
    if pytestconfig.getoption("--write-coverage-baseline"):
        BASELINE.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n")
        pytest.skip(f"baseline rewritten: {BASELINE}")
    expected = json.loads(BASELINE.read_text())
    assert measured == expected, (
        "CLI coverage moved; regenerate the baseline once you have read "
        "the diff (see this module's docstring)"
    )


def test_the_checklist_is_the_whole_surface():
    """A checklist that quietly lost entries would make coverage look
    complete, so pin its shape."""
    checklist = cli_surface.checklist()
    assert len(checklist) > 100
    # Excluded things must not appear as items to claim.
    assert "gerrit upload" not in checklist
    assert "--keyword" not in checklist.get("help", set())
    # Every spelling of an option is its own item: pyjj-cli accepted two
    # of these three until the surface comparison caught the third.
    assert {"-A", "--insert-after", "--after"} <= checklist["split"]
