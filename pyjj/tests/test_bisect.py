"""Tests for the `Bisector` binding (`jj_lib::bisect`).

The wrapper stores only the marks and rebuilds a real `Bisector` on every
call, so these tests care about two things: that the search finds the
right commit, and that replaying the marks never trips one of jj_lib's
`assert!`s (which would reach Python as a `PanicException`, not an
exception a caller can catch).
"""

import pytest

import pyjj


@pytest.fixture
def line(repo, settings, wc_commit):
    """Ten commits in a line, plus the repo loaded at the tip.

    Returns `(repo, ids)` with ids oldest-first, excluding the root and
    the initial working-copy commit.
    """
    ids = []
    parent = wc_commit
    for i in range(10):
        tx = repo.start_transaction(settings)
        builder = tx.new_commit(settings, [parent.id])
        builder.set_description(f"c{i}")
        commit = builder.write(repo)
        tx.set_wc_commit("default", commit.id)
        tx.rebase_descendants()
        repo = tx.commit(f"add c{i}")
        parent = repo.get_commit(commit.id)
        ids.append(parent.id)
    return repo, ids


def test_bisector_seeds_heads_as_bad(line, settings):
    repo, ids = line
    b = pyjj.Bisector(repo, settings, ["root()..@"])
    # `Bisector::new` assumes the range's heads are bad.
    assert [c.hex() for c in b.bad_commits] != []
    assert b.good_commits == []
    assert b.skipped_commits == []
    assert not b.aborted


def test_bisector_finds_the_first_bad_commit(line, settings):
    """Answer every step honestly against a known cutoff."""
    repo, ids = line
    order = [c.hex() for c in ids]
    first_bad = order[6]
    cutoff = order.index(first_bad)

    b = pyjj.Bisector(repo, settings, ["root()..@"])
    steps = 0
    while True:
        step = b.next_step()
        if step.kind == "done":
            break
        steps += 1
        assert steps < 50, "bisection did not converge"
        hex_id = step.commit.id.hex()
        # A commit is bad when it is at or after the cutoff.
        verdict = "bad" if order.index(hex_id) >= cutoff else "good"
        b.mark(step.commit.id, verdict)

    assert step.result == "found"
    assert [c.id.hex() for c in step.commits] == [first_bad]


def test_bisector_reports_remaining_count(line, settings):
    repo, _ids = line
    b = pyjj.Bisector(repo, settings, ["root()..@"])
    lower, upper = b.remaining_count()
    assert lower >= 0
    assert upper is None or upper >= lower


def test_skipping_everything_falls_back_to_the_seeded_head(line, settings):
    """Skipping every candidate still reports the head.

    The head is seeded bad at construction, so it stays the earliest
    revision known to be bad even when nothing else was decided.
    """
    repo, ids = line
    b = pyjj.Bisector(repo, settings, ["root()..@"])
    for _ in range(50):
        step = b.next_step()
        if step.kind == "done":
            break
        b.mark(step.commit.id, "skip")
    assert step.kind == "done"
    assert step.result == "found"
    assert [c.id.hex() for c in step.commits] == [ids[-1].hex()]


def test_empty_range_is_indeterminate(line, settings):
    """`Indeterminate` means the bad set was empty, i.e. no heads."""
    repo, _ids = line
    b = pyjj.Bisector(repo, settings, ["none()"])
    assert b.bad_commits == []
    step = b.next_step()
    assert step.kind == "done"
    assert step.result == "indeterminate"


def test_bisector_abort(line, settings):
    repo, _ids = line
    b = pyjj.Bisector(repo, settings, ["root()..@"])
    step = b.next_step()
    assert step.kind == "evaluate"
    b.mark(step.commit.id, "abort")
    assert b.aborted

    step = b.next_step()
    assert step.kind == "done"
    assert step.result == "abort"

    # Once aborted, further marks are refused rather than asserting.
    with pytest.raises(ValueError, match="aborted"):
        b.mark(step.commit.id if step.commit else _ids[0], "good")


def test_marking_a_seeded_head_good_raises(line, settings):
    """The case AGENTS.md called fragile: a conflicting mark.

    jj_lib's `mark_good` asserts the id is not already bad, and the head
    is seeded bad at construction. That must surface as `ValueError`, not
    a panic.
    """
    repo, _ids = line
    b = pyjj.Bisector(repo, settings, ["root()..@"])
    head = b.bad_commits[0]
    with pytest.raises(ValueError, match="already marked bad"):
        b.mark(head, "good")


def test_conflicting_marks_raise(line, settings):
    repo, _ids = line
    b = pyjj.Bisector(repo, settings, ["root()..@"])
    step = b.next_step()
    target = step.commit.id
    b.mark(target, "good")
    with pytest.raises(ValueError, match="already marked good"):
        b.mark(target, "bad")
    with pytest.raises(ValueError, match="already marked good"):
        b.mark(target, "skip")
    # Re-marking with the same verdict is a no-op, not an error.
    b.mark(target, "good")


def test_unknown_evaluation_name_raises(line, settings):
    repo, _ids = line
    b = pyjj.Bisector(repo, settings, ["root()..@"])
    with pytest.raises(ValueError, match="unknown evaluation"):
        b.mark(b.bad_commits[0], "maybe")


def test_invert_matches_find_good(line, settings):
    """`--find-good` swaps good and bad, and leaves the rest alone."""
    assert pyjj.Bisector.invert("good") == "bad"
    assert pyjj.Bisector.invert("bad") == "good"
    assert pyjj.Bisector.invert("skip") == "skip"
    assert pyjj.Bisector.invert("abort") == "abort"


def test_empty_range_rejected(line, settings):
    repo, _ids = line
    with pytest.raises(ValueError, match="at least one range"):
        pyjj.Bisector(repo, settings, [])
