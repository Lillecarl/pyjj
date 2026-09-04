"""A recorded corpus of what real `jj` prints, and what pyjj-cli owes it.

`assert_parity()` compares repository state, which says nothing about a
command that only reads. The scenarios in `test_parity.py` cover that a
command at a time, by running both CLIs and comparing. This module is
the other half of the same idea, kept as *data*: every entry names one
invocation, and a golden file records what jj printed for it.

Three things follow from having the output on disk rather than only in a
comparison.

- It is readable. Deciding what pyjj-cli should print no longer needs a
  probe repository built by hand each time.
- It carries jj's *labels*, not just its bytes. The goldens are captured
  with `--color=debug`, which wraps every span as `<<label stack::text>>`
  -- so the corpus says that a change id's unique prefix is
  `change_id shortest prefix` and the rest is `change_id shortest rest`.
  That is the specification for colouring pyjj-cli's own output later.
- It records the coloured and the plain rendering separately, because
  for the colour-words diff **they are not the same shape**. With colour
  on, jj puts a word-level change on one row -- `twoTWO`, the removed
  and added halves told apart by colour alone. With colour off it splits
  the same change into a removed row and an added row, because there
  would be no way to tell the halves apart. jj says so itself, in
  `show_color_words_diff_lines`: "Inline word hunks rely on color labels
  to distinguish sides."

  Stripping the ANSI from the coloured form therefore does *not* give
  the plain form, and a corpus that assumed it would hold pyjj-cli to an
  output jj never produces. Stripping only the markers does give
  `--color=always` exactly, and the capture tool asserts that rather
  than trusting it.

  That assertion earns its keep. jj's debug format wraps spans as
  `<<labels::text>>`, and a conflicted file's materialized content
  contains `>>>>>>>`, which closes a marker early. The format is
  ambiguous there, and no parser can fix it. Such an entry gets no
  `.debug` golden; it gets the `.ansi` rendering instead, and the
  manifest lists it, so the missing label specification is visible
  rather than silently wrong.

An entry declares the bar it is held to, which is the judgement about
that invocation written down rather than left implicit:

`bytes`
    Normalized output must match jj's exactly. The default.
`facts`
    pyjj-cli diverges on purpose here, so a scenario in
    `test_parity.py` checks what the output carries instead. The golden
    is still recorded, because it is still the reference.
`todo`
    Not implemented yet. The golden *is* the specification to build
    against, and the entry is a work item rather than an excuse.
`skip`
    Cannot be compared at all, with a reason that is about the output
    -- it depends on a terminal, a server, or the wall clock, or it is
    each tool's own identity. "Not implemented yet" is never a reason;
    that is `todo`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

GOLDEN_SUFFIX = ".debug"
PLAIN_SUFFIX = ".txt"
COLOUR_SUFFIX = ".ansi"


@dataclass(frozen=True)
class Entry:
    """One recorded invocation."""

    id: str
    argv: tuple[str, ...]
    fixture: str = "chain"
    bar: str = "bytes"
    #: Coverage-ledger items this entry exercises, e.g. ("diff", "--git").
    claims: tuple[str, ...] = ()
    #: Required for `todo` and `skip`.
    reason: str = ""
    #: Normalizers to apply before comparing. See `normalize`.
    normalize: tuple[str, ...] = ()
    #: Set when jj legitimately prints nothing here.
    may_be_empty: bool = False

    def __post_init__(self) -> None:
        if self.bar not in {"bytes", "facts", "todo", "skip"}:
            raise ValueError(f"{self.id}: unknown bar {self.bar!r}")
        if self.bar in {"todo", "skip"} and not self.reason:
            raise ValueError(f"{self.id}: {self.bar} needs a reason")


# -- normalization ------------------------------------------------------
#
# Some output cannot be equal between two repositories however correct
# both are: a path names where the repository sits, and an operation id
# is minted per repository. Rather than dropping those invocations, each
# entry names the substitutions to apply first, and the goldens store
# the normalized text. One mechanism covers the workspace root, the
# operation ids, and the relative times whose whole job is to change.

_AGO = re.compile(
    r"\b(?:\d+ (?:year|month|week|day|hour|minute|second|millisecond|microsecond)s?"
    r"|less than a microsecond)\b(?: ago)?"
)


def _normalize_root(text: str, context: dict) -> str:
    return text.replace(str(context["repo"]), "«root»")


def _normalize_op_ids(text: str, context: dict) -> str:
    for op_id in context.get("op_ids", ()):
        for width in (len(op_id), 12):
            text = text.replace(op_id[:width], "«op»")
    return text


def _normalize_ago(text: str, context: dict) -> str:
    return _AGO.sub("«ago»", text)


def _normalize_prog(text: str, context: dict) -> str:
    """Replaces the program name in a recorded command line.

    Both tools record the command that made each operation, and each
    records its own name -- jj writes `jj`, pyjj-cli writes `pyjj`.
    Neither is wrong, so the comparison drops the name and keeps the
    arguments, which is the part that has to agree.
    """
    return re.sub(r"(args: )(?:jj|pyjj)\b", r"\1«prog»", text)


def _normalize_host(text: str, context: dict) -> str:
    """Replaces the user and host jj stamps on an operation.

    The goldens are committed, so anything naming this machine would
    make them fail everywhere else.
    """
    import getpass
    import socket

    return text.replace(f"{getpass.getuser()}@{socket.gethostname()}", "«who»")


NORMALIZERS = {
    "root": _normalize_root,
    "op_ids": _normalize_op_ids,
    "ago": _normalize_ago,
    "host": _normalize_host,
    "prog": _normalize_prog,
}


def normalize(text: str, names, context: dict) -> str:
    """Applies the named substitutions, in the order given."""
    for name in names:
        text = NORMALIZERS[name](text, context)
    return text


def strip_markers(debug_text: str) -> str:
    """The debug form without its label markers: what `--color=always`
    prints."""
    return re.sub(r"<<[^:]*::(.*?)>>", r"\1", debug_text, flags=re.S)


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def coloured(debug_text: str) -> str:
    """What `--color=always` prints: the debug form without its markers."""
    return strip_markers(debug_text)


def labels(debug_text: str) -> list[tuple[str, str]]:
    """Every labelled span in a golden, as (label stack, text).

    This is what makes the corpus a colour specification rather than a
    pile of bytes.
    """
    return [
        (m.group(1), m.group(2))
        for m in re.finditer(r"<<([^:]*)::(.*?)>>", debug_text, flags=re.S)
    ]
