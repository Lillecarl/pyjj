"""Hunk- and line-level selection specs, for agents that split commits.

A spec is JSON or YAML:

    {"files": {PATH: FILE, ...}, "default": "keep" | "reset"}

`default` (`"reset"` when absent) decides every changed file the spec
does not name. A FILE is one of:

    {"action": "keep" | "reset"}    the whole file
    {"hunks": [SEL, ...], "ids": [ID, ...], "lines": [[start, end], ...]}

A SEL names a hunk, or lines of one hunk:

    0, "0"                          the hunk at that index
    "hunk-<hex>"                    the hunk with that id
    {"index": 0, "added": [0, 2], "removed": [1]}
    {"id": "hunk-<hex>", "lines": [0]}

`added` and `removed` are 0-based lines within the hunk's added and
removed blocks. `lines` means `added` for a hunk that adds lines and
`removed` for one that only deletes. A partly selected hunk keeps the
removed lines not selected, then adds the added lines selected.

The file-level `lines` are 1-based, end-exclusive ranges. They select
every hunk whose lines in the new file overlap one, or whose lines in
the old file do, for a hunk that only deletes.

Indices follow jj's own line diff, the numbering `Transaction.squash`
and `Transaction.split_selected` take. An id hashes the hunk's type,
removed and added lines, and three lines of context, as jj-hunk does,
so an id survives re-listing.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Final, Literal, Self

import pyjj_bindings
import yaml
from pydantic import (
    AfterValidator,
    AliasChoices,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

Action = Literal["keep", "reset"]
HunkType = Literal["insert", "delete", "replace"]

HUNK_ID_PREFIX: Final = "hunk-"
CONTEXT_LINES: Final = 3


def normalize_hunk_id(value: str) -> str | None:
    """`hunk-<lowercase hex>` from an id in any accepted spelling, or `None`."""
    text = value.strip()
    for prefix in (HUNK_ID_PREFIX, "id:", "sha:", "sha256:"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    if not text or not all(c in "0123456789abcdefABCDEF" for c in text):
        return None
    return f"{HUNK_ID_PREFIX}{text.lower()}"


def _hunk_id(value: str) -> str:
    normalized = normalize_hunk_id(value)
    if normalized is None:
        raise ValueError(f"invalid hunk id {value!r}")
    return normalized


def _selector(value: object) -> object:
    """A numeric string is an index; any other string is an id."""
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return value


HunkId = Annotated[str, AfterValidator(_hunk_id)]
Index = Annotated[StrictInt, Field(ge=0)]


class HunkLines(BaseModel):
    """One hunk, by index or id, with an optional choice of its lines."""

    model_config = ConfigDict(extra="forbid")

    index: Index | None = None
    id: HunkId | None = None
    lines: list[Index] | None = None
    added: list[Index] | None = Field(
        default=None, validation_alias=AliasChoices("added", "added_lines"))
    removed: list[Index] | None = Field(
        default=None, validation_alias=AliasChoices("removed", "removed_lines"))

    @model_validator(mode="after")
    def _one_hunk(self) -> Self:
        if (self.index is None) == (self.id is None):
            raise ValueError("a hunk object names exactly one of 'index' or 'id'")
        return self

    @property
    def key(self) -> int | str:
        return self.index if self.index is not None else str(self.id)

    @property
    def whole(self) -> bool:
        return self.lines is None and self.added is None and self.removed is None


class FileSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Action | None = None
    hunks: list[Annotated[Index | HunkId | HunkLines, BeforeValidator(_selector)]] = []
    ids: list[HunkId] = []
    lines: list[tuple[StrictInt, StrictInt]] = []

    @field_validator("lines")
    @classmethod
    def _ranges(cls, ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
        for start, end in ranges:
            if not 1 <= start < end:
                raise ValueError(
                    f"line range [{start}, {end}] is empty or not 1-based; "
                    "the end is exclusive")
        return ranges

    @model_validator(mode="after")
    def _action_alone(self) -> Self:
        if self.action is not None and (self.hunks or self.ids or self.lines):
            raise ValueError("'action' decides the whole file; drop hunks, ids and lines")
        return self


class Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: dict[str, FileSpec] = {}
    default: Action = "reset"


@dataclass(frozen=True)
class LineRange:
    start: int
    lines: int


@dataclass(frozen=True)
class Hunk:
    index: int
    id: str
    type: HunkType
    removed: bytes
    added: bytes
    before: LineRange
    after: LineRange
    context: tuple[bytes, bytes] | None

    def to_json(self) -> dict[str, Any]:
        """The record `pyjj hunk list` prints, jj-hunk's shape."""
        def text(data: bytes) -> str:
            return data.decode()
        return {
            "index": self.index,
            "id": self.id,
            "type": self.type,
            "removed": text(self.removed),
            "added": text(self.added),
            "before": {"start": self.before.start, "lines": self.before.lines},
            "after": {"start": self.after.start, "lines": self.after.lines},
            "context": (None if self.context is None else
                        {"pre": text(self.context[0]), "post": text(self.context[1])}),
        }


def compute_hunk_id(hunk_type: str, removed: bytes, added: bytes,
                    context: tuple[bytes, bytes] | None) -> str:
    digest = hashlib.sha256()
    digest.update(b"type\x00" + hunk_type.encode())
    digest.update(b"\x00removed\x00" + removed)
    digest.update(b"\x00added\x00" + added)
    digest.update(b"\x00context\x00")
    if context is not None:
        digest.update(context[0] + b"\x00" + context[1])
    return f"{HUNK_ID_PREFIX}{digest.hexdigest()}"


def _lines(data: bytes) -> list[bytes]:
    """Lines with their endings. Only `\\n` ends a line, as in jj."""
    *lines, tail = data.split(b"\n")
    return [line + b"\n" for line in lines] + ([tail] if tail else [])


def _segments(before: bytes, after: bytes) -> list[tuple[str, bytes, bytes]]:
    return pyjj_bindings.content_hunks(before, after, by="line")


def is_binary(data: bytes) -> bool:
    try:
        data.decode()
    except UnicodeDecodeError:
        return True
    return False


def get_hunks(before: bytes, after: bytes) -> list[Hunk]:
    """The changed regions between two versions of a file, in jj's order."""
    before_lines = _lines(before)
    hunks: list[Hunk] = []
    before_line = after_line = 1
    for kind, removed, added in _segments(before, after):
        removed_count, added_count = len(_lines(removed)), len(_lines(added))
        if kind != "matching":
            hunk_type: HunkType = ("insert" if not removed else
                                   "delete" if not added else "replace")
            start = before_line - 1
            pre = b"".join(before_lines[max(0, start - CONTEXT_LINES):start])
            end = start + removed_count
            post = b"".join(before_lines[end:end + CONTEXT_LINES])
            context = (pre, post) if pre or post else None
            hunks.append(Hunk(
                index=len(hunks),
                id=compute_hunk_id(hunk_type, removed, added, context),
                type=hunk_type,
                removed=removed,
                added=added,
                before=LineRange(before_line, removed_count),
                after=LineRange(after_line, added_count),
                context=context,
            ))
        before_line += removed_count
        after_line += added_count
    return hunks


@dataclass(frozen=True)
class _Pick:
    """The lines of one hunk to take: added lines to add, removed lines to drop."""

    added: frozenset[int]
    removed: frozenset[int]

    @classmethod
    def whole(cls, hunk: Hunk) -> _Pick:
        return cls(frozenset(range(hunk.after.lines)),
                   frozenset(range(hunk.before.lines)))

    def __or__(self, other: _Pick) -> _Pick:
        return _Pick(self.added | other.added, self.removed | other.removed)


def _overlaps(hunk: Hunk, ranges: Iterable[tuple[int, int]]) -> bool:
    span = hunk.after if hunk.type != "delete" else hunk.before
    return any(start < span.start + span.lines and end > span.start
               for start, end in ranges)


def _picks(path: str, spec: FileSpec, hunks: list[Hunk]) -> dict[int, _Pick]:
    by_key: dict[int | str, Hunk] = {h.index: h for h in hunks} | {h.id: h for h in hunks}

    def find(key: int | str) -> Hunk:
        if key not in by_key:
            raise ValueError(f"{path}: no hunk {key!r}; the file has {len(hunks)}")
        return by_key[key]

    def checked(hunk: Hunk, side: str, count: int, chosen: list[int]) -> frozenset[int]:
        wrong = [n for n in chosen if n >= count]
        if wrong:
            raise ValueError(f"{path}: hunk {hunk.index} has {count} {side} "
                             f"lines, so {wrong} are out of range")
        return frozenset(chosen)

    picks: dict[int, _Pick] = {}

    def add(hunk: Hunk, pick: _Pick) -> None:
        picks[hunk.index] = picks[hunk.index] | pick if hunk.index in picks else pick

    for entry in [*spec.hunks, *spec.ids]:
        if not isinstance(entry, HunkLines):
            hunk = find(entry)
            add(hunk, _Pick.whole(hunk))
            continue
        hunk = find(entry.key)
        if entry.whole:
            add(hunk, _Pick.whole(hunk))
            continue
        added = list(entry.added or [])
        removed = list(entry.removed or [])
        (added if hunk.added else removed).extend(entry.lines or [])
        add(hunk, _Pick(checked(hunk, "added", hunk.after.lines, added),
                        checked(hunk, "removed", hunk.before.lines, removed)))
    for hunk in hunks:
        if _overlaps(hunk, spec.lines):
            add(hunk, _Pick.whole(hunk))
    return picks


def select_content(path: str, before: bytes | None, after: bytes | None,
                   spec: FileSpec | None, default: Action) -> bytes | None:
    """The content `spec` selects for one file: `before` with the chosen
    changes applied. `None` is an absent file, on either side."""
    action = default if spec is None else spec.action
    if action is not None:
        return after if action == "keep" else before
    if spec is None or not (spec.hunks or spec.ids or spec.lines):
        return before
    old, new = before or b"", after or b""
    if is_binary(old) or is_binary(new):
        raise ValueError(f"{path}: binary file; select it with action keep or reset")
    hunks = get_hunks(old, new)
    picks = _picks(path, spec, hunks)
    out: list[bytes] = []
    index = 0
    for kind, removed, added in _segments(old, new):
        if kind == "matching":
            out.append(removed)
            continue
        pick = picks.get(index, _Pick(frozenset(), frozenset()))
        index += 1
        out.extend(line for n, line in enumerate(_lines(removed)) if n not in pick.removed)
        out.extend(line for n, line in enumerate(_lines(added)) if n in pick.added)
    result = b"".join(out)
    if result == new:
        return after
    if result == old:
        return before
    return result


def collect_file_contents_for_commit(
        repo: pyjj_bindings.ReadonlyRepo, commit: pyjj_bindings.Commit,
) -> dict[str, tuple[bytes | None, bytes | None]]:
    """`{path: (before, after)}` for each file `commit` changes against its
    merged parents. `None` is an absent file."""
    paths = [entry.path for entry in commit.diff_from_parents(repo)]
    befores = commit.parent_contents(repo, paths)
    contents: dict[str, tuple[bytes | None, bytes | None]] = {}
    for path in paths:
        if commit.file_kind(path).endswith("conflict"):
            raise ValueError(f"{path}: the file has a conflict; resolve it first")
        after = commit.read_file(path) if commit.file_exists(path) else None
        contents[path] = (befores.get(path), after)
    return contents


def spec_to_overrides(repo: pyjj_bindings.ReadonlyRepo, commit: pyjj_bindings.Commit,
                      spec: Spec) -> dict[str, bytes | None]:
    """The selected content of each file whose selection differs from the
    parent, in the shape `split_selected_edited` and `squash_edited` take."""
    overrides: dict[str, bytes | None] = {}
    for path, (before, after) in collect_file_contents_for_commit(repo, commit).items():
        selected = select_content(path, before, after, spec.files.get(path), spec.default)
        if selected != before:
            overrides[path] = selected
    return overrides


def parse_spec(text: str) -> Spec:
    """A spec from JSON or YAML text. Raises `ValueError` on a bad spec."""
    if not text.strip():
        raise ValueError("Spec is empty")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as json_error:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as yaml_error:
            raise ValueError(
                f"Failed to parse spec as JSON ({json_error}) or YAML ({yaml_error})"
            ) from yaml_error
    if not isinstance(data, dict):
        raise ValueError("Spec must be a JSON object")
    # pydantic's ValidationError is a ValueError.
    return Spec.model_validate(data)


def load_spec_from_input(spec_str: str | None, spec_file: str | None) -> Spec:
    """A spec from a file, from stdin (`"-"`), or inline."""
    if spec_file:
        return parse_spec(Path(spec_file).read_text())
    if spec_str is None:
        raise ValueError("Spec is required")
    if spec_str == "-":
        return parse_spec(sys.stdin.read())
    return parse_spec(spec_str)
