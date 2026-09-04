"""The CLI coverage matrix, measured rather than maintained by hand.

`jj util markdown-help` prints clap's whole tree, so the list of
subcommands and flags jj accepts comes straight from the binary under
test. pyjj-cli's own `argparse` tree gives the other side. The
difference is checked against a recorded baseline.

The baseline is exact, the way `UNIMPLEMENTED` in the parity suite is
strict: adding a flag jj has turns this red until the baseline is
regenerated, and so does losing one. That is the point -- the file is a
ledger of what is not covered yet, and it only shrinks on purpose.

Regenerate with:

    PYJJ_PARITY_JJ=<jj> python -c 'import json, cli_surface; \\
        print(json.dumps(cli_surface.compare(), indent=2, sort_keys=True))' \\
        > pyjj/tests/parity/cli_surface_baseline.json
"""

import json
from pathlib import Path

import pytest

from parity import cli_surface

BASELINE = Path(__file__).parent / "parity" / "cli_surface_baseline.json"


@pytest.fixture(scope="module")
def measured():
    return cli_surface.compare()


def test_no_new_gaps(measured):
    """Every difference between the two CLIs is one the baseline knows.

    A failure here means either that pyjj-cli lost coverage, or that jj
    grew a flag -- both worth a look before the baseline moves.
    """
    expected = json.loads(BASELINE.read_text())
    assert measured == expected, (
        "the CLI surface moved; regenerate the baseline once you have "
        "read the diff (see this module's docstring)"
    )


def test_the_measurement_itself_works(measured):
    """A parser that silently found nothing would make the baseline
    vacuous, so pin the shape of what it reads."""
    jj = cli_surface.jj_surface()
    assert len(jj) > 100, "markdown-help should list every subcommand"
    # A command whose flags are stable and well known, as a canary for
    # the code-span reading: short form, long form and an alias.
    assert {"-r", "--revision", "-A", "--insert-after", "--after"} <= jj["split"]
    assert "" in jj, "the root command carries the global flags"
    assert "--at-operation" in jj[""]


def test_no_stale_exclusions():
    """Every documented exclusion still names something jj has.

    An exclusion outlives the flag it excuses if nobody checks, and the
    ledger then quietly under-reports.
    """
    assert cli_surface.stale_exclusions() == []


def test_pyjj_surface_covers_its_own_commands():
    """The `argparse` walk must descend into subcommand groups, or the
    comparison would report every nested command as missing."""
    py = cli_surface.pyjj_surface()
    assert "bookmark set" in py
    assert "git remote add" in py
    assert {"-r", "--revision"} <= py["split"]
