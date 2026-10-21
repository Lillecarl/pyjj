"""pyjj-cli rewrite command: arrange."""
import sys

from ..common import (
    _check_rewritable,
    _finish,
    command,
    write_tx,
)


@command
def arrange(args) -> int:
    """`jj arrange [REVSETS]` — reorder and abandon commits in a TUI.

    The TUI is pyjjui's port of jj's, so this needs pyjjui installed.
    """
    try:
        from pyjjui import mutations
        from pyjjui.screens.arrange import ArrangeScreen
        from textual.app import App
    except ImportError:
        print("Error: pyjj arrange needs pyjjui installed "
              "(pip install 'pyjj-cli[tui]')", file=sys.stderr)
        return 1
    with write_tx(args) as (settings, ws, repo, tx):
        revs = [*(args.revisions or []), *(args.revision_flags or [])]
        revset = ("|".join(f"({r})" for r in revs) if revs
                  else settings.get_string("revsets.arrange"))
        _check_rewritable(tx, settings, repo.revset(settings, revset))
        try:
            prepared = mutations.arrange_targets(repo, settings, revset)
        except mutations.ArrangeRefused as e:
            print(f"Error: {e}", file=sys.stderr)
            print(f"Hint: {e.hint}", file=sys.stderr)
            return 1
        if prepared is None:
            print("No revisions to arrange.", file=sys.stderr)
            return 0
        state, commits, _targets = prepared

        class ArrangeApp(App):
            def on_mount(self) -> None:
                self.push_screen(ArrangeScreen(state, commits),
                                 callback=self.exit)

        plan = ArrangeApp().run()
        if plan is None:
            print("Error: Canceled by user", file=sys.stderr)
            return 1
        mutations.apply_arrange_plan(tx, repo, settings, plan)
        _finish(tx, "arrange revisions", settings, ws, repo)
        return 0
