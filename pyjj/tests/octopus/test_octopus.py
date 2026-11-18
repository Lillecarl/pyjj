"""The octopus labs, solved by the recipes in the pyjj-octopus skill.

Each scenario's checker must fail on the fresh lab and pass after the
skill's recipe. A recipe that stops working here is a skill that tells
agents the wrong thing. The same labs feed the subagent runs; see the
docstring of `octolab.py`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from octolab import SCENARIOS, Lab, build, check, pj, set_line


def _skill_script() -> Path:
    done = subprocess.run(
        ["pyjj", "skill", "path", "pyjj-octopus"],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        pytest.skip(f"pyjj-octopus skill not installed: {done.stderr.strip()}")
    return Path(done.stdout.strip()).parent / "octopus.py"


def _octopus_check(lab: Lab) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["pyjj", "python", str(_skill_script()), "check"],
        cwd=lab.fork,
        capture_output=True,
        text=True,
        check=False,
    )


def _wc(lab: Lab) -> str:
    return pj(lab.fork, "log", "-r", "@", "--no-graph", "-T", "{{ change_id_short }}")


def solve_absorb(lab: Lab) -> None:
    pj(lab.fork, "absorb", "--into", "trunk()..octopus-")


def solve_move(lab: Lab) -> None:
    x = _wc(lab)
    pj(lab.fork, "rebase", "-r", x, "-A", "gamma")
    pj(lab.fork, "bookmark", "set", "gamma", "-r", x)
    pj(lab.fork, "new", "octopus")


def solve_squash(lab: Lab) -> None:
    pj(lab.fork, "squash", "--from", "@", "--into", "alpha", "alpha.py")


def solve_new_topic(lab: Lab) -> None:
    x = _wc(lab)
    pj(lab.fork, "rebase", "-r", x, "-d", "trunk()")
    pj(lab.fork, "bookmark", "create", "delta", "-r", x)
    pj(lab.fork, "rebase", "-r", "octopus", "-d", "octopus-", "-d", "delta")
    pj(lab.fork, "new", "octopus")


def _resolve_k2(lab: Lab, value: str) -> None:
    """Recipe F, including its last step: back to the work commit W."""
    work = _wc(lab)
    root = pj(
        lab.fork,
        "log",
        "-r",
        "roots(conflicts())",
        "--no-graph",
        "-T",
        "{{ change_id_short }}",
    )
    pj(lab.fork, "new", root)
    text = (lab.fork / "config.txt").read_text().splitlines()
    out, inside = [], False
    for line in text:
        if line.startswith("<<<<<<<"):
            inside = True
            out.append(f"k2 = {value}")
        elif line.startswith(">>>>>>>"):
            inside = False
        elif not inside:
            out.append(line)
    (lab.fork / "config.txt").write_text("\n".join(out) + "\n")
    pj(lab.fork, "squash")
    # `pyjj new` abandoned W if it was empty; only work has to be returned to.
    if pj(lab.fork, "log", "-r", f"present({work})", "--no-graph", "-T", "x"):
        pj(lab.fork, "edit", work)
    else:
        pj(lab.fork, "new", "octopus")


def solve_sync(lab: Lab) -> None:
    pj(lab.fork, "git", "fetch", "--remote", "upstream")
    pj(lab.fork, "rebase", "-b", "octopus", "-d", "trunk()", "--skip-emptied")
    _resolve_k2(lab, "alpha")


def test_unconditional_new_octopus_strands_work(tmp_path: Path) -> None:
    """Why recipe F ends with `edit W`: `new octopus` would leave the
    unfinished work in a sibling, and the check says so."""
    lab = build("sync-dirty", tmp_path / "lab")
    pj(lab.fork, "git", "fetch", "--remote", "upstream")
    pj(lab.fork, "rebase", "-b", "octopus", "-d", "trunk()", "--skip-emptied")
    pj(lab.fork, "new", "octopus")
    result = _octopus_check(lab)
    assert result.returncode == 1
    assert "unfinished work left on the octopus, outside @" in result.stdout


def solve_landed(lab: Lab) -> None:
    pj(lab.fork, "git", "fetch", "--remote", "upstream")
    pj(lab.fork, "rebase", "-b", "octopus", "-d", "trunk()", "--skip-emptied")
    pj(lab.fork, "simplify-parents", "-r", "octopus")
    pj(lab.fork, "bookmark", "delete", "alpha")


def solve_cross_lane(lab: Lab) -> None:
    x = _wc(lab)
    pj(lab.fork, "rebase", "-s", "roots(trunk()..beta)", "-d", "alpha")
    pj(lab.fork, "rebase", "-r", x, "-A", "beta")
    pj(lab.fork, "bookmark", "set", "beta", "-r", x)
    pj(lab.fork, "new", "octopus")


SOLUTIONS = {
    "absorb": solve_absorb,
    "move": solve_move,
    "squash": solve_squash,
    "new-topic": solve_new_topic,
    "sync": solve_sync,
    "sync-dirty": solve_sync,
    "landed": solve_landed,
    "cross-lane": solve_cross_lane,
}


def test_every_scenario_has_a_solution() -> None:
    assert set(SOLUTIONS) == set(SCENARIOS)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_recipe_solves_the_scenario(name: str, tmp_path: Path) -> None:
    lab = build(name, tmp_path / "lab")
    assert check(name, lab.root), "the fresh lab already passes its check"
    SOLUTIONS[name](lab)
    assert check(name, lab.root) == []
    result = _octopus_check(lab)
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_names_a_forgotten_bookmark_move(tmp_path: Path) -> None:
    lab = build("move", tmp_path / "lab")
    pj(lab.fork, "rebase", "-r", "@", "-A", "gamma")
    pj(lab.fork, "new", "octopus")
    result = _octopus_check(lab)
    assert result.returncode == 1
    assert "pyjj bookmark set gamma -r" in result.stdout


def test_check_predicts_the_sync_conflict(tmp_path: Path) -> None:
    lab = build("sync", tmp_path / "lab")
    pj(lab.fork, "git", "fetch", "--remote", "upstream")
    result = _octopus_check(lab)
    assert "a sync would start conflicts at:" in result.stdout
    assert "alpha: tune k2" in result.stdout
    # The prediction wrote no operation.
    assert "fetch" in pj(lab.fork, "op", "log", "--no-graph", "--limit", "1")


def test_check_names_the_colliding_topics(tmp_path: Path) -> None:
    lab = build("absorb", tmp_path / "lab")
    pj(lab.fork, "restore")
    pj(lab.fork, "new", "beta", "-m", "beta: tune k2")
    set_line(lab.fork / "config.txt", "k2", "beta")
    pj(lab.fork, "bookmark", "set", "beta", "-r", "@")
    pj(lab.fork, "rebase", "-r", "octopus", "-d", "alpha", "-d", "beta", "-d", "gamma")
    pj(lab.fork, "new", "octopus")
    result = _octopus_check(lab)
    assert result.returncode == 1
    assert (
        "topics alpha and beta conflict with each other in config.txt" in result.stdout
    )


def test_check_finds_marker_lines_a_resolution_left(tmp_path: Path) -> None:
    """A hand edit that keeps part of a block is no conflict to jj."""
    lab = build("sync", tmp_path / "lab")
    pj(lab.fork, "git", "fetch", "--remote", "upstream")
    pj(lab.fork, "rebase", "-b", "octopus", "-d", "trunk()", "--skip-emptied")
    root = pj(
        lab.fork,
        "log",
        "-r",
        "roots(conflicts())",
        "--no-graph",
        "-T",
        "{{ change_id_short }}",
    )
    pj(lab.fork, "new", root)
    text = (lab.fork / "config.txt").read_text()
    kept = [line for line in text.splitlines() if not line.startswith("<<<<<<<")]
    (lab.fork / "config.txt").write_text("\n".join(kept) + "\n")
    pj(lab.fork, "squash")
    pj(lab.fork, "new", "octopus")
    assert pj(lab.fork, "log", "-r", "conflicts()", "--no-graph") == ""
    result = _octopus_check(lab)
    assert result.returncode == 1
    assert "leaves conflict-marker lines in config.txt" in result.stdout


def test_check_predicts_a_landed_topic(tmp_path: Path) -> None:
    lab = build("landed", tmp_path / "lab")
    pj(lab.fork, "git", "fetch", "--remote", "upstream")
    result = _octopus_check(lab)
    assert "upstream already has alpha" in result.stdout


def test_check_wants_trunk_on_upstream(tmp_path: Path) -> None:
    """The fork's own main moves ahead and the trunk() pin is gone:
    jj's default trunk() then picks the fork's main."""
    lab = build("absorb", tmp_path / "lab")
    pj(lab.fork, "config", "unset", "--repo", 'revset-aliases."trunk()"')
    pj(lab.fork, "new", "main", "-m", "fork-only change")
    pj(lab.fork, "bookmark", "set", "main", "-r", "@")
    pj(lab.fork, "git", "push", "--remote", "origin", "-b", "main")
    pj(lab.fork, "new", "octopus")
    result = _octopus_check(lab)
    assert result.returncode == 1
    assert "trunk() is not on the upstream remote" in result.stdout


def test_an_archive_bookmark_is_only_a_note(tmp_path: Path) -> None:
    lab = build("absorb", tmp_path / "lab")
    pj(lab.fork, "restore")
    pj(lab.fork, "bookmark", "create", "archive/old", "-r", "alpha-")
    pj(lab.fork, "new", "main", "-m", "wip elsewhere")
    pj(lab.fork, "bookmark", "create", "wip", "-r", "@")
    pj(lab.fork, "new", "octopus")
    result = _octopus_check(lab)
    assert result.returncode == 0, result.stdout
    assert "NOTE     bookmark wip is not in the octopus" in result.stdout


def test_check_refuses_changes_in_the_octopus(tmp_path: Path) -> None:
    lab = build("squash", tmp_path / "lab")
    pj(lab.fork, "squash", "--from", "@", "--into", "octopus", "notes.txt")
    result = _octopus_check(lab)
    assert result.returncode == 1
    assert "holds changes of its own" in result.stdout
