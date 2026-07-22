"""Presentation-only diff formatting for the preview pane. Built on
`pyjj_bindings.diff_hunks`, a pure content-diff free function -- everything
here is Rich styling on top, not jj_lib logic, which is why it lives in
pyjjui rather than becoming a new pyjj binding.
"""

from rich.console import Group
from rich.text import Text

import pyjj

_STATUS_LABEL = {
    "added": "A",
    "removed": "D",
    "modified": "M",
    "executable": "M",
    "copied": "C",
    "renamed": "R",
}

# Binary/very large files aren't worth line-diffing for a preview pane.
_MAX_PREVIEW_BYTES = 512 * 1024


def render_commit_diff(commit: pyjj.Commit, parent: pyjj.Commit) -> Group:
    """Render `commit`'s diff against `parent` as a series of Rich renderables."""
    entries = commit.diff_with_copies(parent)
    if not entries:
        return Group(Text("(empty diff)", style="dim italic"))

    blocks: list[Text] = []
    for entry in entries:
        blocks.append(_render_entry_header(entry))
        blocks.append(_render_entry_body(commit, parent, entry))
    return Group(*blocks)


def _render_entry_header(entry: pyjj.DiffEntry) -> Text:
    label = _STATUS_LABEL.get(entry.status, "?")
    header = Text(f"{label} ", style="bold yellow")
    if entry.source_path and entry.source_path != entry.path:
        header.append(f"{entry.source_path} -> {entry.path}", style="bold")
    else:
        header.append(entry.path, style="bold")
    return header


def _render_entry_body(commit: pyjj.Commit, parent: pyjj.Commit, entry: pyjj.DiffEntry) -> Text:
    if entry.status not in ("modified", "renamed", "copied"):
        return Text()

    before = _read_or_empty(parent, entry.source_path or entry.path)
    after = _read_or_empty(commit, entry.path)
    if before is None or after is None:
        return Text("(binary or unreadable file)", style="dim italic")
    if len(before) > _MAX_PREVIEW_BYTES or len(after) > _MAX_PREVIEW_BYTES:
        return Text("(file too large to preview)", style="dim italic")

    body = Text()
    for hunk in pyjj.diff_hunks(before, after):
        for line in hunk.before.decode("utf-8", errors="replace").splitlines():
            body.append(f"-{line}\n", style="red")
        for line in hunk.after.decode("utf-8", errors="replace").splitlines():
            body.append(f"+{line}\n", style="green")
    return body


def _read_or_empty(commit: pyjj.Commit, path: str) -> bytes | None:
    if not commit.file_exists(path):
        return b""
    try:
        return commit.read_file(path)
    except pyjj.JjError:
        return None
