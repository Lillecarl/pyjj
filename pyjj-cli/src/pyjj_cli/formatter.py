"""jj's colour formatter, ported.

Text carries a stack of semantic labels -- `bookmark_list`, then
`bookmark`, then `name` -- and the labels decide the style. That is jj's
design, and copying it is not a matter of taste: the styles compose. A
change id's prefix is one colour, and the same field under a working
copy is another, with the row bold. A table of one style per field
cannot say that, so pyjj-cli's hand-written escape sequences cannot
either.

Three parts, all of them jj's:

* the palette from `cli/src/config/colors.toml`, in file order, because
  the order breaks ties;
* the matching from `cli/src/formatter.rs`: a rule applies when its
  labels appear in order in the stack, not necessarily next to each
  other, and every rule that applies merges;
* the emitter, which writes only what changed since the last span, one
  escape sequence per attribute.

Colours are the 256-colour indices jj uses, so `red` is `38;5;1` and
`bright red` is `38;5;9`. `default` means no colour, which prints `39`
and is not the same as leaving the attribute alone.
"""

from __future__ import annotations

import contextlib
import io
import typing

# The eight names and their bright forms, as 256-colour indices. jj
# writes these as `38;5;N` rather than the 30-37 range, so a terminal
# theme cannot reinterpret them.
_COLOURS = {
    "black": 0, "red": 1, "green": 2, "yellow": 3,
    "blue": 4, "magenta": 5, "cyan": 6, "white": 7,
}
_COLOURS.update({f"bright {name}": index + 8
                 for name, index in list(_COLOURS.items())})


_RULES: tuple[tuple[tuple[str, ...], dict], ...] = (
    (('error',), {'fg': 'default', 'bold': True}),
    (('error_source',), {'fg': 'default'}),
    (('warning',), {'fg': 'default', 'bold': True}),
    (('hint',), {'fg': 'default'}),
    (('error', 'heading'), {'fg': 'red', 'bold': True}),
    (('error_source', 'heading'), {'bold': True}),
    (('warning', 'heading'), {'fg': 'yellow', 'bold': True}),
    (('hint', 'heading'), {'fg': 'cyan', 'bold': True}),
    (('conflict_description',), {'fg': 'yellow'}),
    (('conflict_description', 'difficult'), {'fg': 'red'}),
    (('commit_id',), {'fg': 'blue'}),
    (('change_id',), {'fg': 'magenta'}),
    (('prefix',), {'bold': True}),
    (('rest',), {'fg': 'bright black'}),
    (('change_offset',), {'bold': True}),
    (('hidden', 'prefix'), {'fg': 'default'}),
    (('author',), {'fg': 'yellow'}),
    (('committer',), {'fg': 'yellow'}),
    (('timestamp',), {'fg': 'cyan'}),
    (('working_copies',), {'fg': 'green'}),
    (('workspace_name',), {'fg': 'green'}),
    (('bookmark',), {'fg': 'magenta'}),
    (('bookmarks',), {'fg': 'magenta'}),
    (('local_bookmarks',), {'fg': 'magenta'}),
    (('remote_bookmarks',), {'fg': 'magenta'}),
    (('tag',), {'fg': 'magenta'}),
    (('tags',), {'fg': 'magenta'}),
    (('git_ref',), {'fg': 'green'}),
    (('divergent',), {'fg': 'magenta'}),
    (('mutable', 'divergent'), {'fg': 'red'}),
    (('mutable', 'divergent', 'change_id'), {'fg': 'red'}),
    (('conflict',), {'fg': 'red'}),
    (('empty',), {'fg': 'green'}),
    (('placeholder',), {'fg': 'red'}),
    (('description', 'placeholder'), {'fg': 'yellow'}),
    (('empty', 'description', 'placeholder'), {'fg': 'green'}),
    (('separator',), {'fg': 'bright black'}),
    (('elided',), {'fg': 'bright black'}),
    (('root',), {'fg': 'green'}),
    (('working_copy',), {'bold': True}),
    (('working_copy', 'commit_id'), {'fg': 'bright blue'}),
    (('working_copy', 'change_id'), {'fg': 'bright magenta'}),
    (('working_copy', 'author'), {'fg': 'yellow'}),
    (('working_copy', 'committer'), {'fg': 'yellow'}),
    (('working_copy', 'timestamp'), {'fg': 'bright cyan'}),
    (('working_copy', 'working_copies'), {'fg': 'bright green'}),
    (('working_copy', 'bookmark'), {'fg': 'bright magenta'}),
    (('working_copy', 'bookmarks'), {'fg': 'bright magenta'}),
    (('working_copy', 'local_bookmarks'), {'fg': 'bright magenta'}),
    (('working_copy', 'remote_bookmarks'), {'fg': 'bright magenta'}),
    (('working_copy', 'tag'), {'fg': 'bright magenta'}),
    (('working_copy', 'tags'), {'fg': 'bright magenta'}),
    (('working_copy', 'git_ref'), {'fg': 'bright green'}),
    (('working_copy', 'divergent'), {'fg': 'bright magenta'}),
    (('working_copy', 'mutable', 'divergent'), {'fg': 'bright red'}),
    (('working_copy', 'mutable', 'divergent', 'change_id'), {'fg': 'bright red'}),
    (('working_copy', 'conflict'), {'fg': 'bright red'}),
    (('working_copy', 'empty'), {'fg': 'bright green'}),
    (('working_copy', 'placeholder'), {'fg': 'bright red'}),
    (('working_copy', 'description', 'placeholder'), {'fg': 'yellow'}),
    (('working_copy', 'empty', 'description', 'placeholder'), {'fg': 'bright green'}),
    (('config_list', 'name'), {'fg': 'green'}),
    (('config_list', 'value'), {'fg': 'yellow'}),
    (('config_list', 'source'), {'fg': 'blue'}),
    (('config_list', 'path'), {'fg': 'magenta'}),
    (('config_list', 'overridden'), {'fg': 'bright black'}),
    (('config_list', 'overridden', 'name'), {'fg': 'bright black'}),
    (('config_list', 'overridden', 'value'), {'fg': 'bright black'}),
    (('config_list', 'overridden', 'source'), {'fg': 'bright black'}),
    (('config_list', 'overridden', 'path'), {'fg': 'bright black'}),
    (('diff', 'header'), {'fg': 'yellow'}),
    (('diff', 'empty'), {'fg': 'cyan'}),
    (('diff', 'binary'), {'fg': 'cyan'}),
    (('diff', 'file_header'), {'bold': True}),
    (('diff', 'hunk_header'), {'fg': 'cyan'}),
    (('diff', 'context', 'line_number'), {'dim': True}),
    (('diff', 'removed'), {'fg': 'red'}),
    (('diff', 'added'), {'fg': 'green'}),
    (('diff', 'token'), {'underline': True}),
    (('diff', 'modified'), {'fg': 'cyan'}),
    (('diff', 'untracked'), {'fg': 'magenta'}),
    (('diff', 'renamed'), {'fg': 'cyan'}),
    (('diff', 'copied'), {'fg': 'green'}),
    (('diff', 'access-denied'), {'bg': 'red'}),
    (('operation', 'id'), {'fg': 'blue'}),
    (('operation', 'user'), {'fg': 'yellow'}),
    (('operation', 'time'), {'fg': 'cyan'}),
    (('operation', 'attributes'), {'fg': 'magenta'}),
    (('operation', 'current_operation'), {'bold': True}),
    (('operation', 'current_operation', 'id'), {'fg': 'bright blue'}),
    (('operation', 'current_operation', 'user'), {'fg': 'yellow'}),
    (('operation', 'current_operation', 'time'), {'fg': 'bright cyan'}),
    (('operation', 'current_operation', 'attributes'), {'fg': 'bright magenta'}),
    (('node', 'elided'), {'fg': 'bright black'}),
    (('node', 'working_copy'), {'fg': 'green', 'bold': True}),
    (('node', 'current_operation'), {'fg': 'green', 'bold': True}),
    (('node', 'immutable'), {'fg': 'bright cyan', 'bold': True}),
    (('node', 'conflicted'), {'fg': 'red', 'bold': True}),
    (('signature', 'display'), {'fg': 'yellow'}),
    (('signature', 'key'), {'fg': 'cyan'}),
    (('signature', 'status', 'good'), {'fg': 'green'}),
    (('signature', 'status', 'unknown'), {'fg': 'yellow'}),
    (('signature', 'status', 'bad'), {'fg': 'red'}),
    (('signature', 'status', 'invalid'), {'fg': 'red'}),
    (('arrange', 'context', 'commit'), {'dim': True}),
)


def style_for(labels: tuple[str, ...], rules=_RULES) -> dict:
    """The style a label stack asks for.

    A rule matches when its labels appear in the stack in order, though
    not necessarily next to each other, so `diff removed` matches
    `diff color_words removed`. Every matching rule merges, and jj
    ranks them by how late in the stack they matched: the reversed list
    of matched positions, compared as a list. That makes `a d` beat both
    `d` and `a b c` against the stack `a b c d`. Rules that tie fall
    back to the palette's own order, which is why it is kept.
    """
    matched = []
    for index, (required, style) in enumerate(rules):
        positions = []
        start = 0
        for label in required:
            while start < len(labels) and labels[start] != label:
                start += 1
            if start == len(labels):
                break
            positions.append(start)
            start += 1
        if len(positions) == len(required):
            positions.reverse()
            matched.append((positions, index, style))
    matched.sort(key=lambda item: (item[0], item[1]))
    out: dict = {}
    for _positions, _index, style in matched:
        out.update(style)
    return out


def _colour_code(name: str, ground: int) -> str:
    """`38;5;N` for a foreground name, `48;5;N` for a background one."""
    if name == "default":
        return str(ground + 1)
    return f"{ground};5;{_COLOURS[name]}"


# The order `write_new_style` emits attributes in. Each goes out as its
# own escape sequence, the way jj writes them.
_ATTRIBUTES = (
    ("bold", "1", None),
    ("dim", "2", None),
    ("italic", "3", "23"),
    ("underline", "4", "24"),
    ("crossed_out", "9", "29"),
    ("reverse", "7", "27"),
)


def transition(old: dict, new: dict) -> str:
    """The escape sequences that carry `old` to `new`.

    Turning bold or dim off is the awkward case. The code for it resets
    intensity, and on some terminals `NoBold` double-underlines instead,
    so jj writes a full reset and re-applies everything else. That is
    why a style change can start with `0`.
    """
    if old == new:
        return ""
    out = []
    if (old.get("bold") and not new.get("bold")) or (
            old.get("dim") and not new.get("dim")):
        out.append("\x1b[0m")
        old = {}
    for name, on, off in _ATTRIBUTES:
        was, now = bool(old.get(name)), bool(new.get(name))
        if was == now:
            continue
        if now:
            out.append(f"\x1b[{on}m")
        elif off is not None:
            out.append(f"\x1b[{off}m")
    for name, ground in (("fg", 38), ("bg", 48)):
        if old.get(name) != new.get(name):
            colour = new.get(name, "default")
            out.append(f"\x1b[{_colour_code(colour, ground)}m")
    return "".join(out)


class Formatter:
    """One output stream, with a label stack over it.

    The style carries across spans and across lines, the way jj's does,
    so this wraps the whole of a command's output rather than one line
    of it. `close()` returns the terminal to plain text, which is what
    jj does when it drops a formatter.
    """

    def __init__(self, out, enabled: bool) -> None:
        self._out = out
        self._enabled = enabled
        self._labels: list[str] = []
        self._style: dict = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def push(self, *labels: str) -> None:
        self._labels.extend(labels)

    def pop(self, count: int = 1) -> None:
        del self._labels[len(self._labels) - count:]

    @contextlib.contextmanager
    def labeled(self, *labels: str):
        self.push(*labels)
        try:
            yield self
        finally:
            self.pop(len(labels))

    def write(self, text: str, *labels: str) -> None:
        """Write `text` under the current stack, plus `labels`."""
        if not text:
            return
        if not self._enabled:
            self._out.write(text)
            return
        with self.labeled(*labels):
            wanted = style_for(tuple(self._labels))
            self._out.write(transition(self._style, wanted))
            self._style = wanted
            self._out.write(text)

    def sync(self, *labels: str) -> None:
        """Move to the style of `labels` without writing any text.

        jj's templates write empty strings through the formatter, and
        its emitter computes the style even for those. So a row whose
        last span is coloured still steps back to the row's own style
        before the newline, which costs one escape sequence. This is
        that step.
        """
        if not self._enabled:
            return
        with self.labeled(*labels):
            wanted = style_for(tuple(self._labels))
            self._out.write(transition(self._style, wanted))
            self._style = wanted

    def close(self) -> None:
        if self._enabled and self._style:
            self._out.write(transition(self._style, {}))
            self._style = {}

    def __enter__(self) -> "Formatter":
        return self

    def __exit__(self, *exc) -> None:
        # An error part way through a listing must still leave the
        # terminal plain, so the reset runs even when the block raises.
        self.close()


def formatter(out, settings=None) -> Formatter:
    """The formatter for this run's stdout.

    The import is local: this module is the colour engine and nothing
    else, and a test of the engine should not have to load a repository
    library to reach it.
    """
    from .commands.common import use_color

    return Formatter(out, use_color(settings))


def _labels(labels) -> tuple[str, ...]:
    """Labels as a tuple, whether written as one or as a string.

    A span carries `"bookmark name"` in some callers and
    `("bookmark", "name")` in others. Both say the same thing.
    """
    return tuple(labels.split()) if isinstance(labels, str) else tuple(labels)


def separate(parts, gap: str = " ", labels=()):
    """jj's `separate(sep, ...)`: a gap between the non-empty parts.

    Each part is a list of spans. A part with no text drops, and so
    does the gap that would have led it -- a commit that carries no
    bookmarks prints no double space.
    """
    spans = []
    for part in parts:
        if not any(text for text, _labels in part):
            continue
        if spans:
            spans.append((gap, labels))
        spans.extend(part)
    return spans


class Line(typing.NamedTuple):
    """One line of spans, with labels of its own under the block's.

    A row is not always one label stack. An evolution log writes its
    commit under `working_copy mutable` and the operation under
    neither, so the line carries its own base and the block's is what
    they share.
    """

    spans: list
    base: object = ()


def render_block(lines, base=(), enabled: bool = True) -> str:
    """Rows of labelled spans, rendered into one string.

    `lines` is a list of lines. A line is a list of `(text, labels)`
    pairs, or a `Line` that adds a base of its own. Every `labels` sits
    under `base`.

    jj ends a line in two steps. It steps back to `base`, then writes
    the newline under no labels at all, so a line that ends in a
    coloured span costs two escape sequences. The last line has no
    newline: the caller adds it, either as a graph row or as a print.
    """
    out = io.StringIO()
    base = _labels(base)
    with Formatter(out, enabled) as fmt:
        last = len(lines) - 1
        for index, line in enumerate(lines):
            spans, under = line if isinstance(line, Line) else (line, ())
            under = base + _labels(under)
            for text, labels in spans:
                if text:
                    fmt.write(text, *under, *_labels(labels))
                else:
                    # jj computes the style even for an empty write, so
                    # a span that lands empty still costs its escape
                    # sequence -- `diff --stat` writes an empty `-` run
                    # on a file that only gained lines.
                    fmt.sync(*under, *_labels(labels))
            fmt.sync(*under)
            if index < last:
                fmt.write("\n")
    return out.getvalue()
