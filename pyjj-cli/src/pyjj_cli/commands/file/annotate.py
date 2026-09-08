"""file subcommand: file_annotate."""
import sys
from pathlib import Path

import pyjj
from ...formatter import render_block
from ..common import (
    CommandError,
    _commit_context,
    _resolve_template,
    _finish,
    _format_timestamp,
    _load,
    _resolve_all,
    _resolve_one,
    _short_id_spans,
    use_color,
    _wc_commit,
)

def file_annotate(args) -> int:
    """`jj file annotate` — which commit last touched each line.

    jj puts four columns before the text: the change id, the author's
    email up to the `@` in eight characters, the committer timestamp,
    and the line number. pyjj-cli printed a twelve-character commit id
    and nothing else, which named a commit the reader cannot address --
    a change id is what jj resolves.
    """
    try:
        settings, ws, repo = _load(args)
        commit = _resolve_one(repo, settings, args.revision)
        template = _resolve_template(settings, ws, args, "file_annotate")
        lines = commit.annotate(repo, args.path)
        commits: dict[str, object] = {}
        for number, ann in enumerate(lines, start=1):
            key = ann.commit_id.hex()
            line = ann.line.removesuffix(b"\n")
            origin = commits.get(key)
            if origin is None:
                origin = commits[key] = repo.get_commit(ann.commit_id)
            if template is not None:
                # A template replaces the four columns, not just their
                # shape, so the commit's own variables come with the
                # line's -- the same names every other listing offers.
                context = _commit_context(repo, settings, origin, [])
                context["line_number"] = number
                context["content"] = line.decode("utf-8", "surrogateescape")
                print(template.render(context))
                continue
            local = (origin.author.email or "").split("@")[0][:8]
            stamp = _format_timestamp(origin.committer.timestamp)
            # jj's `templates.file_annotate`: four columns joined by a
            # space, then `: `, then the line. The padding a column
            # needs is written outside that column's own label, so a
            # short email is yellow only where the email is.
            spans = _short_id_spans(
                origin.change_id.reverse_hex(),
                repo.shortest_change_id_prefix_len(origin.change_id, settings),
                "change_id")
            spans = [(text, f"commit {labels}") for text, labels in spans]
            spans += [
                (" ", ""),
                (local, "commit author email local"),
                (" " * (8 - len(local)), ""),
                (" ", ""),
                (stamp, "commit committer timestamp local format"),
                (" ", ""),
                (" " * max(0, 4 - len(str(number))), ""),
                (str(number), "line_number"),
                (": ", ""),
                (line.decode("utf-8", "surrogateescape"), "content"),
            ]
            rendered = render_block([spans], (), use_color(settings))
            sys.stdout.flush()
            sys.stdout.buffer.write(
                rendered.encode("utf-8", "surrogateescape") + b"\n")
            sys.stdout.buffer.flush()
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0
