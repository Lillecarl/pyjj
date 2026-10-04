"""Pure plan model behind an arrange-style reorder/abandon UI.

Ports the state machine in jj's `cli/src/commands/arrange.rs` (`State`,
`swap_commits`, `to_rewrite_plan`, `RewritePlan::execute`'s ordering)
without any UI or repository access: everything is commit-id hex
strings, so this is unit-testable with plain dicts -- the same
data-in/data-out split `pyjj.graph_dot.resolve_plan` already uses for
`graph plan`/`graph apply`. `mutations.arrange()` takes a plan from
here and executes it against a real repo.

Layout of one state:

- `parents`: every commit the UI shows, target and context alike, each
  mapped to its parent ids. Context commits (jj's external parents and
  external children) live here too, because a swap rewrites parent
  references everywhere uniformly -- but only non-external commits
  reach the plan.
- `external`: context ids. Swaps never move *onto* one (jj's
  external-parent/external-child guards), and external ids never reach
  the plan (jj excludes them from `to_rewrite_plan`; external children
  rebase onto the rearranged stack via the normal
  `rebase_descendants()` afterward instead).

The caller builds the target set gap-free (jj refuses gappy revsets up
front with "Cannot arrange revset with gaps in.") -- this module
assumes that, and raises `ValueError` on a parent cycle the same way
jj's `topo_order_forward` panics on one.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlanEntry:
    """One rewrite: give `id` these `parents`, or abandon it."""

    id: str
    parents: list[str]
    abandon: bool = False


@dataclass
class ArrangeState:
    """The reorder/abandon state for one target set.

    `parents` maps every shown commit (targets plus context) to its
    parent ids; `external` names the context ids among them;
    `abandoned` names the targets marked for abandon (`a` in jj's UI,
    `p` un-marks). `heads` fixes the display/tie-break order the way
    jj's `head_order` does.
    """

    parents: dict[str, list[str]]
    external: set[str] = field(default_factory=set)
    abandoned: set[str] = field(default_factory=set)
    heads: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.heads = list(self.heads) or [
            id for id in self.parents
            if id not in self.external
            and not any(id in ps for ps in self.parents.values())
        ]
        self.order: list[str] = []
        self.refresh_order()

    @property
    def targets(self) -> set[str]:
        return set(self.parents) - self.external

    def refresh_order(self) -> None:
        """Recompute display order after a parent change: children
        before parents, heads first -- jj's `update_commit_order`
        (which walks `head_order` in order, so the result is
        deterministic for a given state)."""
        order: list[str] = []
        seen: set[str] = set()

        def visit(id: str) -> None:
            if id in seen or id not in self.parents:
                return
            seen.add(id)
            order.append(id)
            for parent in self.parents[id]:
                visit(parent)

        for head in self.heads:
            visit(head)
        # Anything unreachable from the heads (should not happen in a
        # gap-free set) keeps a stable tail rather than vanishing.
        for id in self.parents:
            visit(id)
        self.order = order

    def _swap(self, a_id: str, b_id: str) -> None:
        """Exchange two commits' positions: their own parents, every
        parent reference to either of them, and their head slots --
        exactly jj's `swap_commits`."""
        if a_id == b_id:
            return
        self.heads = [b_id if id == a_id else a_id if id == b_id else id
                      for id in self.heads]
        for id, ps in self.parents.items():
            self.parents[id] = [b_id if p == a_id else a_id if p == b_id else p
                                for p in ps]
        self.parents[a_id], self.parents[b_id] = (
            self.parents[b_id], self.parents[a_id])
        self.refresh_order()

    def swap_with_parent(self, id: str) -> bool:
        """Swap a commit with its parent (`J` in jj's UI). Only when it
        has exactly one parent and that parent is editable -- otherwise
        a no-op returning `False`, same as jj."""
        ps = self.parents[id]
        if len(ps) != 1 or ps[0] in self.external:
            return False
        self._swap(id, ps[0])
        return True

    def swap_with_child(self, id: str) -> bool:
        """Swap a commit with its child (`K` in jj's UI). Only when it
        has exactly one child and that child is editable -- otherwise
        a no-op returning `False`, same as jj."""
        children = sorted(
            other for other, ps in self.parents.items() if id in ps)
        if len(children) != 1 or children[0] in self.external:
            return False
        self._swap(id, children[0])
        return True

    def set_abandoned(self, id: str, abandon: bool) -> None:
        """Mark (`a`) or un-mark (`p`) a target for abandon."""
        if id in self.external:
            raise ValueError(f"cannot abandon context commit {id}")
        if abandon:
            self.abandoned.add(id)
        else:
            self.abandoned.discard(id)

    def to_plan(self) -> list[PlanEntry]:
        """The rewrite plan in execution order: parents before
        children along the *new* parent edges (jj's
        `topo_order_forward` over the plan), so every rewrite sees its
        destination's successor already written."""
        plan_ids = [id for id in self.parents if id not in self.external]
        in_plan = set(plan_ids)
        order: list[str] = []
        done: set[str] = set()
        visiting: set[str] = set()

        def visit(id: str) -> None:
            if id in done:
                return
            if id in visiting:
                raise ValueError(f"parent cycle involving {id}")
            visiting.add(id)
            for parent in self.parents[id]:
                if parent in in_plan:
                    visit(parent)
            visiting.discard(id)
            done.add(id)
            order.append(id)

        for id in plan_ids:
            visit(id)
        return [PlanEntry(id=id, parents=list(self.parents[id]),
                          abandon=id in self.abandoned)
                for id in order]


def resolve_parents(rewritten: dict[str, str],
                    abandoned: dict[str, list[str]],
                    ids: list[str]) -> list[str]:
    """Map parent ids through in-flight rewrites, mirroring
    `MutableRepo::new_parents`: a rewritten id becomes its successor,
    an abandoned id becomes its own parents (recursively), anything
    else passes through. Order-preserving with duplicates dropped,
    same as jj's `rewritten_ids_with` walk."""
    resolved: list[str] = []
    seen: set[str] = set()
    stack = list(reversed(ids))
    while stack:
        id = stack.pop()
        if id in seen:
            continue
        seen.add(id)
        if id in rewritten:
            stack.append(rewritten[id])
        elif id in abandoned:
            stack.extend(reversed(abandoned[id]))
        else:
            resolved.append(id)
    return resolved
