"""Tests for arrange_plan.py's pure reorder/abandon model.

No repository involved -- every state is a plain `{id: [parents]}`
dict, so these run without fixtures. Each behavior mirrors the
`arrange.rs` function named in its docstring.
"""

import pytest

from pyjjui.arrange_plan import ArrangeState, PlanEntry, resolve_parents


def chain(*ids):
    """A linear stack's `{id: [parent]}` map; the first id is on root."""
    parents = {}
    previous = "root"
    for id in ids:
        parents[id] = [previous]
        previous = id
    return parents


def test_order_runs_children_first():
    """`update_commit_order`: heads first, children before parents."""
    state = ArrangeState(chain("a", "b", "c"), heads=["c"])
    assert state.order == ["c", "b", "a"]


def test_swap_with_parent_exchanges_positions():
    """`swap_commits`: root-A-B-C with B swapped onto A's slot becomes
    root-B-A-C -- B takes A's parents, A takes B's, C follows B."""
    state = ArrangeState(chain("a", "b", "c"), heads=["c"])
    assert state.swap_with_parent("b") is True
    assert state.parents == {
        "a": ["b"],
        "b": ["root"],
        "c": ["a"],
    }
    assert state.order == ["c", "a", "b"]


def test_swap_needs_exactly_one_editable_parent():
    """Merges (two parents) and external parents refuse the swap --
    jj's `swap_selection_down` guards, returning False."""
    state = ArrangeState(
        {"m": ["a", "b"], "a": ["root"], "b": ["root"]}, heads=["m"])
    assert state.swap_with_parent("m") is False
    assert state.parents["m"] == ["a", "b"]

    state = ArrangeState(
        {"a": ["root"], "b": ["a"]}, external={"root"}, heads=["b"])
    assert state.swap_with_parent("a") is False


def test_swap_with_child_needs_exactly_one_editable_child():
    """`swap_selection_up`: one child swaps; two children, or an
    external one, refuse."""
    state = ArrangeState(chain("a", "b", "c"), heads=["c"])
    assert state.swap_with_child("b") is True
    assert state.parents["b"] == ["c"]
    assert state.parents["c"] == ["a"]

    fork = ArrangeState(
        {"x": ["root"], "y": ["x"], "z": ["x"]}, heads=["y", "z"])
    assert fork.swap_with_child("x") is False

    state = ArrangeState(
        chain("a", "b"), heads=["b"])
    state.parents["ext"] = ["b"]
    state.external.add("ext")
    assert state.swap_with_child("b") is False


def test_abandon_marks_and_unmarks_but_never_context():
    """`a`/`p`: abandon toggles per target; context commits refuse."""
    state = ArrangeState(chain("a", "b"), heads=["b"])
    state.set_abandoned("a", True)
    assert state.abandoned == {"a"}
    state.set_abandoned("a", False)
    assert state.abandoned == set()

    state = ArrangeState({"a": ["root"]}, external={"root"})
    with pytest.raises(ValueError, match="context"):
        state.set_abandoned("root", True)


def test_plan_runs_parents_before_children():
    """`to_rewrite_plan` + `RewritePlan::execute`'s ordering: every
    entry's in-plan parents come earlier, carrying abandon flags."""
    state = ArrangeState(chain("a", "b", "c"), heads=["c"])
    state.swap_with_parent("b")
    state.set_abandoned("a", True)
    plan = state.to_plan()
    assert [(e.id, e.abandon) for e in plan] == [
        ("b", False), ("a", True), ("c", False)]
    assert [e.parents for e in plan] == [["root"], ["b"], ["a"]]
    position = {e.id: i for i, e in enumerate(plan)}
    for entry in plan:
        for parent in entry.parents:
            if parent in position:
                assert position[parent] < position[entry.id]


def test_plan_rejects_parent_cycles():
    """A parent cycle is a `ValueError`, where jj's
    `topo_order_forward` panics."""
    state = ArrangeState({"a": ["b"], "b": ["a"]}, heads=["a"])
    with pytest.raises(ValueError, match="cycle"):
        state.to_plan()


def test_resolve_parents_maps_rewrites_and_abandons():
    """`MutableRepo::new_parents`: rewritten ids become successors,
    abandoned ids become their own parents (recursively), the rest
    pass through, order-preserving with duplicates dropped."""
    assert resolve_parents({"b": "B2"}, {"a": ["root"]}, ["a", "b"]) == [
        "root", "B2"]
    # Recursive: abandoned `a` resolves through rewritten `root`... only
    # if `root` itself was rewritten; otherwise it passes through.
    assert resolve_parents({"x": "X2"}, {}, ["x", "x", "y"]) == ["X2", "y"]
    assert resolve_parents(
        {}, {"b": ["a"], "a": ["root"]}, ["b"]) == ["root"]


def test_plan_entry_defaults_to_keep():
    assert PlanEntry(id="a", parents=["root"]) == PlanEntry(
        id="a", parents=["root"], abandon=False)
