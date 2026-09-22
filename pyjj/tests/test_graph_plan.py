"""What `resolve_plan` turns a target graph into.

Pure: every case here states the repository's current parents as a
dict, so the reshapes can be as awkward as they like without building
a repository to hold them.

The ordering cases are the point. A rebase reads its destination as it
stands *now*, so emitting a child before the parent it is moving onto
lands it on that parent's old position. Declaration order does not
imply that, and a graph edited by hand or by an agent declares nodes
in whatever order it likes.
"""

import pytest

from pyjj.graph_dot import PlanError, parse_dot, render_dot, resolve_plan


def _edges(**spec):
    """`{key: [(parent, "direct"), ...]}` from `key=[parents]`."""
    return {key: [(parent, "direct") for parent in parents]
            for key, parents in spec.items()}


def _plan(nodes, edges, current):
    return resolve_plan(nodes, edges, current)


def test_a_graph_matching_the_repository_is_no_work():
    nodes = ["c", "b", "a"]
    edges = _edges(c=["b"], b=["a"], a=["base"])
    current = {"c": ["b"], "b": ["a"], "a": ["base"]}
    assert _plan(nodes, edges, current) == []


def test_only_the_nodes_that_differ_are_emitted():
    nodes = ["c", "b", "a"]
    edges = _edges(c=["b"], b=["base"], a=["base"])
    current = {"c": ["b"], "b": ["a"], "a": ["base"]}
    assert _plan(nodes, edges, current) == [("b", ["base"])]


def test_a_chain_becomes_a_fan():
    """The kr8s move: a line of commits becomes parallel topics."""
    nodes = ["c", "b", "a"]
    edges = _edges(c=["base"], b=["base"], a=["base"])
    current = {"c": ["b"], "b": ["a"], "a": ["base"]}
    steps = _plan(nodes, edges, current)
    assert sorted(steps) == [("b", ["base"]), ("c", ["base"])]


def test_a_fan_becomes_a_chain_parents_first():
    """Serialising three parallel topics. `c` moves onto `b`, so `b`
    has to reach its own new position first."""
    nodes = ["a", "b", "c"]
    edges = _edges(a=["base"], b=["a"], c=["b"])
    current = {"a": ["base"], "b": ["base"], "c": ["base"]}
    steps = _plan(nodes, edges, current)
    assert [key for key, _parents in steps] == ["b", "c"]


def test_a_swap_is_ordered_by_the_target_not_the_declaration():
    """`a` and `b` trade places. Declared child-first on purpose: the
    plan must still move `b` before `a` lands on it."""
    nodes = ["a", "b"]
    edges = _edges(b=["base"], a=["b"])
    current = {"a": ["base"], "b": ["a"]}
    steps = _plan(nodes, edges, current)
    assert [key for key, _parents in steps] == ["b", "a"]


def test_a_deep_chain_reversal_orders_every_step():
    """Five commits reversed end to end. Every node moves, and each
    one's new parent must move before it."""
    chain = ["e", "d", "c", "b", "a"]
    current = {"a": ["base"], "b": ["a"], "c": ["b"], "d": ["c"], "e": ["d"]}
    edges = _edges(a=["b"], b=["c"], c=["d"], d=["e"], e=["base"])
    steps = _plan(chain, edges, current)
    assert [key for key, _parents in steps] == ["e", "d", "c", "b", "a"]


def test_a_merge_keeps_the_parent_order_the_graph_gives():
    """A merge's first parent is not interchangeable with its second,
    so the plan carries the order rather than a set."""
    nodes = ["m", "p1", "p2"]
    edges = _edges(m=["p2", "p1"], p1=["base"], p2=["base"])
    current = {"m": ["p1", "p2"], "p1": ["base"], "p2": ["base"]}
    assert _plan(nodes, edges, current) == [("m", ["p2", "p1"])]


def test_a_merge_gaining_a_parent_waits_for_it():
    """The parallelize case: `d` moves beside the topics and the merge
    then takes it. The merge must come second."""
    nodes = ["m", "d", "a", "b"]
    edges = _edges(m=["a", "b", "d"], d=["base"], a=["base"], b=["base"])
    current = {"m": ["a", "b"], "d": ["m"], "a": ["base"], "b": ["base"]}
    steps = _plan(nodes, edges, current)
    assert [key for key, _parents in steps] == ["d", "m"]


def test_a_merge_losing_a_parent():
    nodes = ["m", "a", "b"]
    edges = _edges(m=["a"], a=["base"], b=["base"])
    current = {"m": ["a", "b"], "a": ["base"], "b": ["base"]}
    assert _plan(nodes, edges, current) == [("m", ["a"])]


def test_a_subtree_moves_under_a_different_parent():
    nodes = ["x", "y", "a", "b"]
    edges = _edges(x=["b"], y=["x"], a=["base"], b=["base"])
    current = {"x": ["a"], "y": ["x"], "a": ["base"], "b": ["base"]}
    steps = _plan(nodes, edges, current)
    assert steps == [("x", ["b"])]


def test_a_node_may_point_outside_the_graph():
    """`main` is named as a parent without being described. It is a
    fixed point, not a node that has to be ordered."""
    nodes = ["a"]
    edges = _edges(a=["main"])
    assert _plan(nodes, edges, {"a": ["base"]}) == [("a", ["main"])]


def test_two_roots_onto_one_new_base():
    nodes = ["a", "b"]
    edges = _edges(a=["newbase"], b=["newbase"])
    current = {"a": ["oldbase"], "b": ["oldbase"]}
    assert sorted(_plan(nodes, edges, current)) == [
        ("a", ["newbase"]), ("b", ["newbase"])]


def test_a_diamond_orders_both_sides_before_the_join():
    nodes = ["join", "left", "right", "base"]
    edges = _edges(join=["left", "right"], left=["base"], right=["base"],
                   base=["root"])
    current = {"join": ["left"], "left": ["base"], "right": ["base"],
               "base": ["root"]}
    steps = _plan(nodes, edges, current)
    assert [key for key, _parents in steps] == ["join"]


def test_a_reordered_diamond_moves_the_sides_before_the_join():
    nodes = ["join", "left", "right", "base"]
    edges = _edges(join=["left", "right"], left=["base"], right=["left"],
                   base=["root"])
    current = {"join": ["left", "right"], "left": ["base"],
               "right": ["base"], "base": ["root"]}
    steps = _plan(nodes, edges, current)
    assert [key for key, _parents in steps] == ["right"]


def test_a_two_node_cycle_is_refused():
    with pytest.raises(PlanError, match="cycle"):
        _plan(["a", "b"], _edges(a=["b"], b=["a"]),
              {"a": ["base"], "b": ["base"]})


def test_a_long_cycle_is_refused():
    with pytest.raises(PlanError, match="cycle"):
        _plan(["a", "b", "c", "d"],
              _edges(a=["b"], b=["c"], c=["d"], d=["a"]),
              {key: ["base"] for key in "abcd"})


def test_a_cycle_is_refused_even_when_other_nodes_are_fine():
    """The clean part of the graph must not be applied first and the
    cycle discovered halfway through."""
    with pytest.raises(PlanError, match="cycle"):
        _plan(["ok", "a", "b"],
              _edges(ok=["base"], a=["b"], b=["a"]),
              {"ok": ["other"], "a": ["base"], "b": ["base"]})


def test_a_self_parent_is_refused():
    with pytest.raises(PlanError, match="its own parent"):
        _plan(["a"], _edges(a=["a"]), {"a": ["base"]})


def test_a_repeated_parent_is_refused():
    """A commit cannot be its merge's parent twice, and DOT will carry
    the duplicate edge happily."""
    with pytest.raises(PlanError, match="twice"):
        _plan(["m", "a"], _edges(m=["a", "a"], a=["base"]),
              {"m": ["a"], "a": ["base"]})


def test_applying_the_plan_twice_is_a_no_op():
    """Idempotence, stated as the resolver sees it: replay the steps
    onto `current` and the second pass finds nothing."""
    nodes = ["m", "d", "a"]
    edges = _edges(m=["a", "d"], d=["base"], a=["base"])
    current = {"m": ["a"], "d": ["m"], "a": ["base"]}
    steps = _plan(nodes, edges, current)
    assert steps
    for key, parents in steps:
        current[key] = parents
    assert _plan(nodes, edges, current) == []


def test_a_graph_this_module_wrote_round_trips_into_a_plan():
    """The whole loop: emit, read back, and find no work to do."""
    items = [("m", [("a", "direct"), ("b", "direct")]),
             ("a", [("base", "direct")]),
             ("b", [("base", "direct")])]
    nodes, edges = parse_dot(render_dot(items, {}))
    current = {"m": ["a", "b"], "a": ["base"], "b": ["base"]}
    assert resolve_plan(nodes, edges, current) == []


def test_an_indirect_edge_is_still_a_parent_edge():
    """`--dot` writes an elided run as a dashed edge. A plan reads the
    target as literal parents, so the style does not change the work."""
    items = [("a", [("base", "indirect")])]
    nodes, edges = parse_dot(render_dot(items, {}))
    assert resolve_plan(nodes, edges, {"a": ["other"]}) == [("a", ["base"])]
