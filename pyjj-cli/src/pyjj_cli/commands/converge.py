"""pyjj-cli command: converge -- resolve divergent changes.

Mirrors `cli/src/commands/converge.rs`, through the
`jj_lib::converge` primitives the bindings expose
(`ReadonlyRepo.find_divergent_changes`,
`TruncatedEvolutionGraph.converge`,
`Transaction.apply_converge_solution`).

Only the automatic path is implemented: when the heuristics settle
the author, description and parents, the solution is written exactly
like jj writes it. Where jj would prompt (choosing among several
divergent changes, or filling in an attribute the heuristics could
not solve), this prints jj's own "could not" message and exits 1 --
a CLI cannot prompt, so there is no interactive half to fall back to.
`--no-interactive` therefore behaves exactly like jj's; without it,
the auto-solvable cases behave exactly like jj's too.
"""
import sys

import pyjj

from .common import (
    CommandError,
    _check_rewritable,
    _finish,
    _load,
    _start_transaction,
)


def _short_change(repo, settings, change_id) -> str:
    n = repo.shortest_change_id_prefix_len(change_id, settings)
    return change_id.hex()[:n]


def _report(found) -> None:
    """`Found N divergent change(s)...`, jj's shape, on stderr."""
    print(f"Found {len(found)} divergent change(s) in the specified "
          f"revset:", file=sys.stderr)
    for change in found:
        print(f"- Change: {change.change_id.hex()} with "
              f"{len(change.commits)} commits:", file=sys.stderr)
        for commit in change.commits[:10]:
            first_line = commit.description.split("\n", 1)[0]
            print(f"    {commit.id.hex()[:12]} {first_line}",
                  file=sys.stderr)
        if len(change.commits) > 10:
            print(f"    ... and {len(change.commits) - 10} more",
                  file=sys.stderr)
        print(file=sys.stderr)


def converge(args) -> int:
    """`jj converge [-r REVSETS] [--no-interactive]`."""
    try:
        settings, ws, repo = _load(args)
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {e.message}", file=sys.stderr)
        return 1

    try:
        revisions = list(getattr(args, "revisions", None) or [])
        if revisions:
            search = " | ".join(f"({expr})" for expr in revisions)
        else:
            search = settings.get_string("revsets.converge")
            if search is None:
                raise CommandError("revsets.converge is not set")

        tx = _start_transaction(repo, settings)
        _check_rewritable(tx, settings, repo.revset(settings, search))

        found = repo.find_divergent_changes(settings, search)
        if not found:
            if revisions:
                print("No divergence found among the specified "
                      "revisions.", file=sys.stderr)
            else:
                print("No divergent changes found.", file=sys.stderr)
            return 0
        _report(found)

        if len(found) > 1:
            # jj prompts here; without a prompter the only honest move
            # is jj's own --no-interactive error, whose hint (run jj
            # converge interactively) is exactly right.
            print("Error: Cannot automatically choose which change to "
                  "converge", file=sys.stderr)
            print("Hint: Run `jj converge` in interactive mode, or "
                  "specify a revset that resolves to only one change ID",
                  file=sys.stderr)
            return 1
        change = found[0]

        print(f"Attempting to converge change {change.change_id.hex()}...\n",
              file=sys.stderr)
        graph = pyjj.TruncatedEvolutionGraph(repo, change.commits)
        result = graph.converge()

        missing = []
        if not result.author.solved:
            missing.append("author")
        if not result.description.solved:
            missing.append("description")
        if not result.parents.solved:
            missing.append("parents")
        if missing:
            for kind in missing:
                print(f"Could not determine which {kind} to use.",
                      file=sys.stderr)
            print("Error: Could not converge change", file=sys.stderr)
            return 1

        tree = result.tree
        if tree is None:
            second = graph.converge(
                author=result.author.value,
                description=result.description.value,
                parents=result.parents.value)
            tree = second.tree
            if tree is None:
                print("Error: Failed to converge tree", file=sys.stderr)
                return 1

        solution, num_rebased = tx.apply_converge_solution(
            result.author.value, result.description.value,
            result.parents.value, tree, change.change_id,
            [c.id for c in change.commits])
        print(f"Successfully converged change: created commit "
              f"{solution.id.hex()[:12]}.", file=sys.stderr)
        if num_rebased > 0:
            print(f"Rebased {num_rebased} descendants", file=sys.stderr)
        short = _short_change(repo, settings, change.change_id)
        _finish(tx,
                f"converge {short} with {len(change.commits)} predecessors",
                settings, ws, repo)
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
