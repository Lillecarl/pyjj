"""Hunk-level and line-level selection helpers for AI agents.

This module mirrors jj-hunk's tiny JSON DSL for granular commit splitting,
extended with per-file line ranges for true line-level control.

Spec format (JSON or YAML, same as jj-hunk):
{
  "files": {
    "path/to/file": {"hunks": [0, 1, "hunk-abc..."], "ids": ["hunk-..."], "lines": [[10,15]], "action": "keep"|"reset"},
    "other.rs": {"action": "keep"}
  },
  "default": "keep"|"reset"  // default "reset"
}

- {"hunks": [indices|ids]} — select hunks by index (0-based) or stable id (hunk-<sha256>)
- {"ids": ["hunk-..."]} — select by id (merged with hunks)
- {"lines": [[start,end], ...]} — select hunks whose after_range overlaps these 1-indexed line ranges in the *after* file (end exclusive)
                            For line-within-hunk granularity, use per-hunk objects: {"hunks": [{"index":0, "lines":[0,2]}]}
                            where lines are 0-indexed within that hunk's added block (insert/replace) or removed block (delete).
- {"action": "keep"} — keep all changes in file
- {"action": "reset"} — discard all changes in file
- "default": action for unlisted files

hunks entries in "hunks" may be:
  int -> whole hunk by index
  str -> whole hunk by id (or numeric string -> index)
  dict -> {"index": int, "id": str, "lines": [int...]} or {"index": int, "added_lines": [...], "removed_lines": [...]}

Ids are sha256 of type+removed+added+context, same as jj-hunk, so specs are stable across re-listing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

try:
    import yaml  # type: ignore

    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    from pydantic import BaseModel, Field as PydanticField, ValidationError, field_validator, model_validator

    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False
    BaseModel = object  # type: ignore
    ValidationError = Exception  # type: ignore

# Mirror jj-hunk's diff.rs constants
HUNK_ID_PREFIX = "hunk-"
CONTEXT_LINES = 3


@dataclass
class HunkSelection:
    indices: set[int] = field(default_factory=set)
    ids: set[str] = field(default_factory=set)

    def is_empty(self) -> bool:
        return not self.indices and not self.ids

    def matches(self, index: int, hunk_id: str) -> bool:
        return index in self.indices or hunk_id in self.ids


@dataclass
class FileSpec:
    action: str | None = None  # "keep" | "reset" | None
    selection: HunkSelection = field(default_factory=HunkSelection)
    line_ranges: list[tuple[int, int]] = field(default_factory=list)  # per-file line ranges
    per_hunk_lines: dict[int, set[int]] = field(default_factory=dict)  # hunk index -> set of line indices within that hunk's added block
    per_hunk_added: dict[int, set[int]] = field(default_factory=dict)
    per_hunk_removed: dict[int, set[int]] = field(default_factory=dict)


@dataclass
class Spec:
    files: dict[str, FileSpec] = field(default_factory=dict)
    default: str = "reset"  # "keep" | "reset"


# Pydantic models for validation (used when available)
if HAS_PYDANTIC:

    class HunkObjectModel(BaseModel):  # type: ignore
        index: int | None = None
        id: str | None = None
        lines: list[int] | None = None
        added_lines: list[int] | None = None
        removed_lines: list[int] | None = None
        added: list[int] | None = None
        removed: list[int] | None = None

        @field_validator("id")  # type: ignore
        @classmethod
        def validate_id(cls, v):
            if v is None:
                return v
            nid = normalize_hunk_id(v)
            if nid is None:
                raise ValueError(f"Invalid hunk id: {v!r}")
            return nid

        @model_validator(mode="after")  # type: ignore
        def check_index_or_id(self):
            if self.index is None and self.id is None:
                raise ValueError("Hunk object must have 'index' or 'id'")
            return self

    class FileSpecModel(BaseModel):  # type: ignore
        action: Literal["keep", "reset"] | None = None
        hunks: list[int | str | HunkObjectModel] = PydanticField(default_factory=list)
        ids: list[str] = PydanticField(default_factory=list)
        lines: list[tuple[int, int]] = PydanticField(default_factory=list)

        @field_validator("ids")  # type: ignore
        @classmethod
        def validate_ids(cls, v):
            out = []
            for item in v:
                nid = normalize_hunk_id(item)
                if nid is None:
                    raise ValueError(f"Invalid hunk id: {item!r}")
                out.append(nid)
            return out

        @field_validator("lines")  # type: ignore
        @classmethod
        def validate_lines(cls, v):
            out = []
            for entry in v:
                if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                    raise ValueError(f"Each 'lines' entry must be [start, end], got {entry!r}")
                start, end = entry
                if not isinstance(start, int) or not isinstance(end, int):
                    raise ValueError(f"Line range must be [int, int], got {entry!r}")
                if start < 1 or end < 1 or end < start:
                    raise ValueError(f"Invalid line range [{start}, {end}]")
                out.append((start, end))
            return out

        @field_validator("hunks", mode="before")  # type: ignore
        @classmethod
        def validate_hunks(cls, v):
            # This runs before Pydantic's type coercion, so we handle raw input
            if not isinstance(v, list):
                raise ValueError("'hunks' must be a list")
            out = []
            for entry in v:
                if isinstance(entry, int):
                    out.append(entry)
                elif isinstance(entry, str):
                    trimmed = entry.strip()
                    if not trimmed:
                        raise ValueError("Empty hunk selector")
                    try:
                        idx = int(trimmed)
                        out.append(idx)
                    except ValueError:
                        nid = normalize_hunk_id(trimmed)
                        if nid is None:
                            raise ValueError(f"Invalid hunk selector: {entry!r}")
                        out.append(nid)
                elif isinstance(entry, dict):
                    # Validate via HunkObjectModel
                    obj = HunkObjectModel(**entry)
                    out.append(obj)
                else:
                    raise ValueError(f"Invalid hunk entry: {entry!r}")
            return out

    class SpecModel(BaseModel):  # type: ignore
        files: dict[str, FileSpecModel] = PydanticField(default_factory=dict)
        default: Literal["keep", "reset"] = "reset"


def normalize_hunk_id(value: str) -> str | None:
    trimmed = value.strip()
    if not trimmed:
        return None
    hex_part = trimmed
    for prefix in (HUNK_ID_PREFIX, "id:", "sha:", "sha256:"):
        if trimmed.startswith(prefix):
            hex_part = trimmed[len(prefix) :]
            break
    hex_part = hex_part.strip()
    if not hex_part or not all(c in "0123456789abcdefABCDEF" for c in hex_part):
        return None
    return f"{HUNK_ID_PREFIX}{hex_part.lower()}"


def compute_hunk_id(hunk_type: str, removed: str, added: str, context_before: str, context_after: str) -> str:
    h = hashlib.sha256()
    h.update(b"type\x00")
    h.update(hunk_type.encode())
    h.update(b"\x00removed\x00")
    h.update(removed.encode())
    h.update(b"\x00added\x00")
    h.update(added.encode())
    # Mirror jj-hunk's context handling
    if context_before or context_after:
        h.update(b"\x00context\x00")
        h.update(context_before.encode())
        h.update(b"\x00")
        h.update(context_after.encode())
    else:
        h.update(b"\x00context\x00")
    return f"{HUNK_ID_PREFIX}{h.hexdigest()}"


def _determine_hunk_type(removed: str, added: str) -> str:
    if not removed and added:
        return "insert"
    if removed and not added:
        return "delete"
    return "replace"


def _build_context(before_lines: list[str], before_start: int, before_len: int) -> tuple[str, str] | None:
    if not before_lines:
        return None
    start_idx = max(0, min(before_start - 1, len(before_lines)))
    before_start_ctx = max(0, start_idx - CONTEXT_LINES)
    before_slice = before_lines[before_start_ctx:start_idx]
    after_start = min(start_idx + before_len, len(before_lines))
    after_end = min(after_start + CONTEXT_LINES, len(before_lines))
    after_slice = before_lines[after_start:after_end]
    if not before_slice and not after_slice:
        return None
    return ("".join(before_slice), "".join(after_slice))


def _split_lines_with_endings(text: str) -> list[str]:
    if not text:
        return []
    lines: list[str] = []
    start = 0
    for idx, ch in enumerate(text):
        if ch == "\n":
            lines.append(text[start : idx + 1])
            start = idx + 1
    if start < len(text):
        lines.append(text[start:])
    return lines


def _count_lines(value: str) -> int:
    if not value:
        return 0
    return value.count("\n") + (0 if value.endswith("\n") else 1)


def get_hunks_detailed(before: str, after: str) -> list[dict[str, Any]]:
    """Return detailed hunks like jj-hunk's get_hunks, with ids, types, ranges, context."""
    # Use similar's TextDiff via Python difflib as approx, but we can reuse pyjj's diff_hunks
    # For now, reimplement using difflib-like grouping similar to jj-hunk's similar crate.
    # To avoid Rust dependency for detailed, we replicate logic in Python using difflib.
    import difflib

    before_lines = _split_lines_with_endings(before)
    after_lines = _split_lines_with_endings(after)
    # Use difflib.SequenceMatcher to get matching blocks, then derive hunks
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    hunks: list[dict[str, Any]] = []
    before_line = 1
    after_line = 1
    hunk_idx = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            # Update line counters for equal block
            before_line += i2 - i1
            after_line += j2 - j1
            continue
        # For replace/delete/insert, group contiguous non-equal opcodes into one hunk
        # difflib already groups, but we need to merge consecutive non-equal?
        # SequenceMatcher already gives minimal opcodes, but we need to merge adjacent non-equal
        # Actually we treat each opcode as a hunk for simplicity; but to match similar's grouping,
        # we should merge consecutive non-equal opcodes if they are adjacent without equal between.
        # Since we iterate, each non-equal opcode is a hunk.
        removed = "".join(before_lines[i1:i2])
        added = "".join(after_lines[j1:j2])
        hunk_type = _determine_hunk_type(removed, added)
        before_len = i2 - i1
        after_len = j2 - j1
        before_range = {"start": before_line, "lines": before_len}
        after_range = {"start": after_line, "lines": after_len}
        # Context
        ctx = _build_context(before_lines, before_line, before_len)
        ctx_before, ctx_after = ctx if ctx else ("", "")
        hunk_id = compute_hunk_id(hunk_type, removed, added, ctx_before, ctx_after)
        hunks.append(
            {
                "index": hunk_idx,
                "id": hunk_id,
                "type": hunk_type,
                "removed": removed,
                "added": added,
                "before": before_range,
                "after": after_range,
                "context": {"pre": ctx_before, "post": ctx_after} if ctx else None,
            }
        )
        hunk_idx += 1
        before_line += before_len
        after_line += after_len
    return hunks


def parse_spec(spec_str: str) -> Spec:
    """Parse JSON or YAML spec string into Spec object. Uses pydantic for validation when available."""
    spec_str = spec_str.strip()
    if not spec_str:
        raise ValueError("Spec is empty")
    # Try JSON first
    try:
        data = json.loads(spec_str)
    except json.JSONDecodeError as je:
        if HAS_YAML:
            try:
                data = yaml.safe_load(spec_str)
            except Exception as ye:
                raise ValueError(f"Failed to parse spec as JSON ({je}) or YAML ({ye})") from ye
        else:
            raise ValueError(f"Failed to parse spec as JSON ({je}); YAML not available") from je
    if not isinstance(data, dict):
        raise ValueError("Spec must be a JSON object")
    # Use pydantic for validation if available
    if HAS_PYDANTIC:
        try:
            model = SpecModel.model_validate(data)  # type: ignore
            # Convert pydantic model to internal Spec dataclass
            spec = Spec(default=model.default)
            for path, fmodel in model.files.items():
                # Handle action-only case
                if fmodel.action is not None and not fmodel.hunks and not fmodel.ids and not fmodel.lines:
                    spec.files[path] = FileSpec(action=fmodel.action)
                    continue
                file_spec = FileSpec(action=fmodel.action)
                # Process hunks (already validated, but need to populate FileSpec)
                for entry in fmodel.hunks:
                    if isinstance(entry, int):
                        file_spec.selection.indices.add(entry)
                    elif isinstance(entry, str):
                        # Already normalized by validator
                        try:
                            idx = int(entry)
                            file_spec.selection.indices.add(idx)
                        except ValueError:
                            file_spec.selection.ids.add(entry)
                    else:  # HunkObjectModel
                        if entry.index is not None:
                            tgt = entry.index
                            if entry.lines is not None:
                                file_spec.per_hunk_lines.setdefault(tgt, set()).update(entry.lines)
                            if entry.added_lines is not None:
                                file_spec.per_hunk_added.setdefault(tgt, set()).update(entry.added_lines)
                            if entry.added is not None:
                                file_spec.per_hunk_added.setdefault(tgt, set()).update(entry.added)
                            if entry.removed_lines is not None:
                                file_spec.per_hunk_removed.setdefault(tgt, set()).update(entry.removed_lines)
                            if entry.removed is not None:
                                file_spec.per_hunk_removed.setdefault(tgt, set()).update(entry.removed)
                            if entry.lines is None and entry.added_lines is None and entry.added is None and entry.removed_lines is None and entry.removed is None:
                                file_spec.selection.indices.add(tgt)
                        elif entry.id is not None:
                            file_spec.selection.ids.add(entry.id)
                            # Per-hunk lines with id not yet supported via pydantic either, but validator would have caught
                for id_str in fmodel.ids:
                    file_spec.selection.ids.add(id_str)
                for start, end in fmodel.lines:
                    file_spec.line_ranges.append((start, end))
                spec.files[path] = file_spec
            return spec
        except ValidationError as ve:  # type: ignore
            # Re-raise as ValueError with details
            raise ValueError(f"Spec validation failed: {ve}") from ve
    # Fallback manual validation (when pydantic not available)
    files_data = data.get("files", {})
    if not isinstance(files_data, dict):
        raise ValueError("'files' must be an object")
    default = data.get("default", "reset")
    if default not in ("keep", "reset"):
        raise ValueError(f"Invalid default action: {default!r}")
    spec = Spec(default=default)
    for path, file_data in files_data.items():
        if not isinstance(path, str):
            raise ValueError(f"File path must be string, got {path!r}")
        if not isinstance(file_data, dict):
            raise ValueError(f"File spec for {path!r} must be object")
        # Handle {"action": "keep"} case
        if "action" in file_data and set(file_data.keys()) == {"action"}:
            action = file_data["action"]
            if action not in ("keep", "reset"):
                raise ValueError(f"Invalid action for {path!r}: {action!r}")
            spec.files[path] = FileSpec(action=action)
            continue
        # Handle case where file_data is {"action": "keep"} with other keys? Not allowed per jj-hunk, but we support.
        action = file_data.get("action")
        if action is not None and action not in ("keep", "reset"):
            raise ValueError(f"Invalid action for {path!r}: {action!r}")
        file_spec = FileSpec(action=action if action in ("keep", "reset") else None)
        # Parse hunks
        hunks_raw = file_data.get("hunks", [])
        ids_raw = file_data.get("ids", [])
        lines_raw = file_data.get("lines", [])
        if not isinstance(hunks_raw, list):
            raise ValueError(f"'hunks' for {path!r} must be list")
        if not isinstance(ids_raw, list):
            raise ValueError(f"'ids' for {path!r} must be list")
        # Process hunks entries: can be int, str, or dict with index/id and lines
        for entry in hunks_raw:
            if isinstance(entry, int):
                file_spec.selection.indices.add(entry)
            elif isinstance(entry, str):
                trimmed = entry.strip()
                if not trimmed:
                    raise ValueError(f"Empty hunk selector for {path!r}")
                # Try parse as index
                try:
                    idx = int(trimmed)
                    file_spec.selection.indices.add(idx)
                except ValueError:
                    nid = normalize_hunk_id(trimmed)
                    if nid is None:
                        raise ValueError(f"Invalid hunk selector for {path!r}: {entry!r}")
                    file_spec.selection.ids.add(nid)
            elif isinstance(entry, dict):
                # Per-hunk line selection: {"index": 0, "lines": [0,1]} or {"id": "...", "lines": [...]}
                idx = entry.get("index")
                hid = entry.get("id")
                lines = entry.get("lines")
                added_lines = entry.get("added_lines")
                removed_lines = entry.get("removed_lines")
                # Also support "added" and "removed" as aliases
                if added_lines is None and "added" in entry:
                    added_lines = entry["added"]
                if removed_lines is None and "removed" in entry:
                    removed_lines = entry["removed"]
                target_idx: int | None = None
                if idx is not None:
                    if not isinstance(idx, int):
                        raise ValueError(f"'index' must be int for {path!r}")
                    target_idx = idx
                elif hid is not None:
                    nid = normalize_hunk_id(str(hid))
                    if nid is None:
                        raise ValueError(f"Invalid id for {path!r}: {hid!r}")
                    # Need to resolve id to index later; for now store in selection and per-hunk
                    # We will add to selection ids, and also store per-hunk lines keyed by id string placeholder
                    # For simplicity, require index for per-hunk lines; id-based per-hunk lines not yet supported via lines filter
                    # Instead, we add id to selection and if lines specified, we need to map id to index at apply time
                    file_spec.selection.ids.add(nid)
                    # For per-hunk lines with id, we can't know index yet, so store under special key
                    # Use hash of id as key? Instead we store separately and handle at apply time.
                    # For now, require index for per-hunk line selection.
                    raise ValueError(f"Per-hunk lines with 'id' not yet supported for {path!r}, use 'index'")
                else:
                    raise ValueError(f"Per-hunk object for {path!r} must have 'index' or 'id'")
                if lines is not None:
                    if not isinstance(lines, list):
                        raise ValueError(f"'lines' must be list for {path!r}")
                    if target_idx is None:
                        raise ValueError(f"'lines' requires 'index' for {path!r}")
                    file_spec.per_hunk_lines.setdefault(target_idx, set()).update(int(x) for x in lines)
                if added_lines is not None:
                    if not isinstance(added_lines, list):
                        raise ValueError(f"'added_lines' must be list for {path!r}")
                    if target_idx is None:
                        raise ValueError(f"'added_lines' requires 'index' for {path!r}")
                    file_spec.per_hunk_added.setdefault(target_idx, set()).update(int(x) for x in added_lines)
                if removed_lines is not None:
                    if not isinstance(removed_lines, list):
                        raise ValueError(f"'removed_lines' must be list for {path!r}")
                    if target_idx is None:
                        raise ValueError(f"'removed_lines' requires 'index' for {path!r}")
                    file_spec.per_hunk_removed.setdefault(target_idx, set()).update(int(x) for x in removed_lines)
                # If no lines specified, this is just a whole-hunk selection via index
                if lines is None and added_lines is None and removed_lines is None:
                    if target_idx is not None:
                        file_spec.selection.indices.add(target_idx)
            else:
                raise ValueError(f"Invalid hunk entry for {path!r}: {entry!r}")
        # Process ids
        for id_str in ids_raw:
            if not isinstance(id_str, str):
                raise ValueError(f"Invalid id for {path!r}: {id_str!r}")
            nid = normalize_hunk_id(id_str)
            if nid is None:
                raise ValueError(f"Invalid hunk id for {path!r}: {id_str!r}")
            file_spec.selection.ids.add(nid)
        # Process lines (per-file line ranges)
        if lines_raw:
            if not isinstance(lines_raw, list):
                raise ValueError(f"'lines' for {path!r} must be list")
            for entry in lines_raw:
                if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                    raise ValueError(f"Each 'lines' entry for {path!r} must be [start, end]")
                start, end = entry
                if not isinstance(start, int) or not isinstance(end, int):
                    raise ValueError(f"Line range for {path!r} must be [int, int]")
                if start < 1 or end < 1 or end < start:
                    raise ValueError(f"Invalid line range for {path!r}: [{start}, {end}]")
                file_spec.line_ranges.append((start, end))
        # If file_spec has no action and empty selection but has line_ranges, that's fine
        spec.files[path] = file_spec
    return spec


def _hunk_overlaps_line_ranges(hunk_after_start: int, hunk_after_len: int, line_ranges: list[tuple[int, int]]) -> bool:
    """Check if hunk's after_range overlaps any of the file's line ranges."""
    if not line_ranges:
        return False
    hunk_end = hunk_after_start + hunk_after_len
    for start, end in line_ranges:
        # start inclusive, end exclusive (like Python), but spec uses 1-indexed
        # hunk range is also 1-indexed
        if start < hunk_end and end > hunk_after_start:
            return True
    return False


def file_spec_decides_keep(spec: Spec, path: str, hunk_idx: int | None = None, hunk_id: str | None = None, after_start: int | None = None, after_len: int | None = None) -> bool | None:
    """Decide for a given file/hunk whether it should be kept.
    Returns True (keep), False (reset), or None (defer to default handling at file level).
    This is a helper for per-hunk decisions.
    """
    file_spec = spec.files.get(path)
    if file_spec is None:
        return None
    if file_spec.action == "keep":
        return True
    if file_spec.action == "reset":
        return False
    # Check hunk-level selection
    if hunk_idx is not None and hunk_id is not None:
        if file_spec.selection.matches(hunk_idx, hunk_id):
            return True
        # Check per-hunk line selection: if this hunk has per-hunk line filter, then the file spec
        # is not a simple keep/reset, but a partial hunk. The caller should handle per-hunk lines separately.
        # For now, if the hunk has per-hunk line filters, we consider it not matched as whole hunk.
    # Check line_ranges
    if file_spec.line_ranges and after_start is not None and after_len is not None:
        if _hunk_overlaps_line_ranges(after_start, after_len, file_spec.line_ranges):
            return True
    return None


def apply_spec_to_file_content(before: bytes, after: bytes, file_spec: FileSpec | None, default: str, detailed_hunks: list[dict[str, Any]] | None = None) -> bytes:
    """Apply file_spec to a single file's before/after content, returning the content for the 'keep' side.
    If file_spec is None, default applies.
    detailed_hunks can be provided to avoid recomputing.
    Handles hunk-level and per-file line ranges, plus per-hunk line filtering.
    """
    if file_spec is None:
        return after if default == "keep" else before
    if file_spec.action == "keep":
        return after
    if file_spec.action == "reset":
        return before
    # Need to compute detailed hunks if not provided
    if detailed_hunks is None:
        try:
            before_s = before.decode()
            after_s = after.decode()
        except UnicodeDecodeError:
            # Binary: no hunk logic, treat as whole file
            # For binary, hunk selection doesn't apply; keep or reset whole file
            # Since action was not keep/reset, and we have no hunk info, fall back to default?
            # For now, if file_spec has any hunks/lines, we treat as not selected -> before
            # This matches jj-hunk's binary handling: mark as binary, no hunks.
            return before
        detailed_hunks = get_hunks_detailed(before_s, after_s)
    # If no hunks (identical), return before
    if not detailed_hunks:
        return before
    # Build selection sets
    # For each hunk, decide if it should be kept entirely, partially via per-hunk lines, or reset.
    # First, handle whole-hunk selections and line_ranges
    selected_hunks: set[int] = set()
    for hunk in detailed_hunks:
        idx = hunk["index"]
        hid = hunk["id"]
        after_start = hunk["after"]["start"]
        after_len = hunk["after"]["lines"]
        # Check whole-hunk match
        if file_spec.selection.matches(idx, hid):
            selected_hunks.add(idx)
            continue
        # Check per-hunk line filters: if this hunk has per_hunk_lines etc, then it's a partial hunk selection
        # For now, per_hunk_lines means the hunk is partially selected; we handle after loop.
        # Check line_ranges
        if _hunk_overlaps_line_ranges(after_start, after_len, file_spec.line_ranges):
            selected_hunks.add(idx)
    # Now handle per-hunk line-level filtering
    # For hunks that have per_hunk_lines / per_hunk_added / per_hunk_removed, we need to construct partial content
    # We will iterate hunks and build result piecewise, handling each hunk's content.
    # For simplicity, we will handle per-hunk lines by splitting that hunk's added/removed into lines and filtering.
    # If a hunk is in selected_hunks (whole), we keep its added block entirely.
    # If a hunk has per-hunk line filters, we keep only those lines (instead of whole).
    # Otherwise, we keep removed block.
    # This logic will be implemented in the caller that reconstructs file content from hunks.
    # For now, we implement a helper that returns the reconstructed file content given the selections.
    return _reconstruct_with_line_filters(before, after, detailed_hunks, file_spec, selected_hunks)


def _reconstruct_with_line_filters(
    before: bytes,
    after: bytes,
    detailed_hunks: list[dict[str, Any]],
    file_spec: FileSpec,
    selected_hunks: set[int],
) -> bytes:
    """Reconstruct file content with line-level filters."""
    # Decode as text for line handling; if binary or decode fails, fall back
    try:
        before_s = before.decode()
        after_s = after.decode()
    except UnicodeDecodeError:
        return before if not selected_hunks else after
    # Use the detailed hunks to reconstruct, but need to handle per-hunk line filters
    # For each hunk, if it has per-hunk line filters, we need to produce a mixed hunk.
    # We will iterate through hunks in order, and for each, decide its output.
    # For hunks without per-hunk filters, use selected_hunks set.
    # For hunks with per-hunk filters, produce filtered content.
    # To do this, we need the original before/after strings and the hunks' removed/added.
    # We can reconstruct by walking through the file's hunks and building result.
    # However, detailed_hunks already contains removed/added for each hunk, but we need to know
    # the unchanged gaps between hunks. The detailed_hunks list alone doesn't give us the unchanged text.
    # Instead, we can use a similar approach to apply_selected_hunks but with per-hunk line granularity.
    # Simpler: Use the before/after strings and the hunks' positions to reconstruct.
    # We need the full before_lines and after_lines plus hunk ranges.
    # For now, we do a simple reconstruction: Start with empty result, iterate hunks, and for each,
    # append either the hunk's added (if selected) or removed (if not), and for gaps, append the unchanged text
    # which we can derive from the before/after strings.
    # But we don't have the unchanged gaps in detailed_hunks; we can recompute by diffing again with a more detailed walk.
    # Simpler: Reimplement the apply logic using the same approach as in diff.rs: iterate over diff opcodes and apply selection.
    # For per-hunk line filters, we need to split the hunk's added/removed into lines and filter.
    # Let's implement a direct line-filtering for each hunk that has per-hunk filters.
    # For hunks with per_hunk_lines etc, we will generate a filtered version of that hunk's added/removed.
    # Then we can use a helper that walks the diff and applies per-hunk decisions.
    before_lines = before_s.splitlines(keepends=True)
    after_lines = after_s.splitlines(keepends=True)
    # But we need to know the hunk boundaries to map. Instead, we can just use the detailed_hunks' removed/added and reassemble
    # by treating the file as: unchanged prefix + hunk0 + unchanged gap + hunk1 + ...
    # We don't have gaps, but we can compute gaps from the before/after strings and hunk ranges.
    # For simplicity, let's just do: For each hunk, if it has per-hunk line filter, we produce a filtered hunk content
    # by splitting its added/removed into lines and keeping only selected lines.
    # Then we can call a function that, given before/after and a dict of hunk index -> filtered content, reconstructs.
    # However, the cleanest is to just handle per-hunk line filtering by producing a new "selected" set where
    # the hunk's added content is filtered, and then use the standard hunk selection but with a modified after.
    # For now, we will handle the simple case: per_hunk_lines, per_hunk_added, per_hunk_removed
    # For each hunk that has such filters, we will compute its filtered added/removed and then treat the hunk as selected
    # if any lines are kept, otherwise not.
    # Actually, for per-hunk lines, the hunk is partially kept: we want to keep only some lines of its added block.
    # So we need to produce a new file where that hunk's region contains only the selected lines.
    # Example: hunk with added = "a\nb\nc\n" (3 lines), per_hunk_lines {0: {0,2}} means keep lines 0 and 2 -> "a\nc\n"
    # For delete hunk with removed = "a\nb\nc\n", per_hunk_removed {0: {0}}? But for delete, selecting lines to keep the deletion?
    # This is getting too specific; for MVP we can support per_hunk_lines as selecting added lines to keep for insert/replace hunks.
    # For delete hunks, per_hunk_lines would select which removed lines to keep deleted (i.e., not in final file).
    # Let's implement a helper that, for each hunk with per-hunk filters, builds the filtered added string.
    # Then we can reconstruct the file by iterating hunks and using either filtered added or removed.
    # We need the full file's line structure. Let's use the before/after strings and the hunks' removed/added to reconstruct.
    # Instead of trying to handle gaps, we can use the approach: Start with before content, then for each hunk in order, replace its removed block with either added (if selected) or filtered added.
    # But we need to know where each hunk's removed block appears in before. The hunk's before_range gives start line in before file.
    # We can reconstruct the final file by walking before_lines and after_lines.
    # Simpler: Use the existing apply logic but override per-hunk content.
    # Let's implement a function that, given before, after, and a dict of hunk_idx -> filtered_added (and filtered_removed), produces result.
    # For now, we will handle only per_hunk_lines and per_hunk_added as selecting added lines.
    # For each hunk with per_hunk_lines, we will produce filtered_added = selected lines from added.
    # Then the decision for that hunk is: if filtered_added is not empty, we consider the hunk "selected" but with filtered content.
    # We need to know the hunk's type to know whether to use added or removed.
    # For insert (removed empty): filtered_added is the lines to keep.
    # For delete (added empty): per_hunk_removed selecting which removed lines to delete? But delete hunk's added is empty, so after has no lines there. Selecting a subset of removed lines to delete would mean the final file should have the unselected removed lines.
    # For replace: both have content, and per_hunk_added selects which added lines to keep, and the rest would be the corresponding removed lines? Complex.
    # For MVP, we will support per_hunk_lines only for insert hunks (most common for line-level splitting of added code).
    # This is a reasonable limitation to document.
    filtered_hunks: dict[int, str] = {}
    for idx, line_set in file_spec.per_hunk_lines.items():
        # Find the hunk with this index
        hunk = next((h for h in detailed_hunks if h["index"] == idx), None)
        if not hunk:
            continue
        added = hunk["added"]
        added_lines = _split_lines_with_endings(added)
        filtered = "".join(added_lines[i] for i in sorted(line_set) if 0 <= i < len(added_lines))
        filtered_hunks[idx] = filtered
    for idx, line_set in file_spec.per_hunk_added.items():
        hunk = next((h for h in detailed_hunks if h["index"] == idx), None)
        if not hunk:
            continue
        added = hunk["added"]
        added_lines = _split_lines_with_endings(added)
        filtered = "".join(added_lines[i] for i in sorted(line_set) if 0 <= i < len(added_lines))
        filtered_hunks[idx] = filtered
    for idx, line_set in file_spec.per_hunk_removed.items():
        hunk = next((h for h in detailed_hunks if h["index"] == idx), None)
        if not hunk:
            continue
        removed = hunk["removed"]
        removed_lines = _split_lines_with_endings(removed)
        # For removed, selecting lines means which removed lines to keep deleted? Actually for delete, the final file omits removed lines.
        # If we select a subset of removed lines to keep deleted, the final file should omit those lines, keep the rest.
        # So filtered_removed is the lines NOT in line_set? Or the lines in line_set are the ones to delete?
        # Let's define: per_hunk_removed selects which removed lines to *keep* as deleted (i.e., not in final file).
        # So the final file's content for that hunk would be the removed lines that are NOT selected (since unselected removed lines are kept).
        # But that is confusing. For now, we will treat per_hunk_removed similarly: filtered content is the removed lines that are selected to be kept deleted, but the final file's hunk region would be the unselected removed lines?
        # Actually for delete hunk, the before has removed lines, after has nothing. The file's content in that region is either removed (if not selected) or empty (if selected).
        # For partial delete, we want to delete only some lines. So the final file should contain the removed lines that are NOT selected for deletion.
        # So filtered_removed should be the lines to keep (i.e., not deleted), which is complement of selected.
        # But the spec's "lines" for delete hunk could be interpreted as which lines to delete.
        # To keep it simple, we will treat per_hunk_removed as selecting which removed lines to *keep* in final file (i.e., not delete).
        # So the hunk's output for delete would be the selected removed lines.
        # This is ambiguous, but we need to pick one. Let's treat per_hunk_removed as lines to keep in final file.
        filtered = "".join(removed_lines[i] for i in sorted(line_set) if 0 <= i < len(removed_lines))
        filtered_hunks[idx] = filtered
    # Now reconstruct
    # If a hunk has a filtered entry, we will use that filtered content as the "added" for that hunk if hunk was considered selected,
    # otherwise we use removed.
    # But we need to know, for hunks with per-hunk filters, whether they are considered selected or not.
    # For now, if a hunk has a per-hunk filter, we treat it as selected with filtered content.
    # So we add those indices to selected_hunks if they have any filtered lines, otherwise they are not selected.
    for idx in filtered_hunks:
        if filtered_hunks[idx]:
            selected_hunks.add(idx)
        else:
            selected_hunks.discard(idx)
    # Now we have a set of hunks to keep (either whole or filtered). For filtered hunks, we need to use filtered content.
    # We will do a final pass: reconstruct file by walking hunks and using either filtered, added, or removed.
    # We need the unchanged gaps as well. To get gaps, we can use the before_lines and hunk ranges.
    # Simpler: Use the before and after strings and the hunks' positions to build result.
    # We can iterate over hunks in order, and for each, append the unchanged text before the hunk, then the hunk's selected content, then continue.
    # To do this, we need the byte offsets of each hunk's removed block in before.
    # Instead, we can use the approach of splitting before and after into lines and applying selection per hunk.
    # Let's use a line-based reconstruction: Build the final file line by line, using the hunks' before/after line numbers.
    # before_lines and after_lines are already split.
    # The file's final content is: unchanged lines from before that are not in any hunk's before_range, plus for each hunk, either its added (or filtered added) if selected, or its removed if not.
    # We can do this by walking the file's line numbers and hunks.
    # For each hunk, its before_range and after_range tell us which lines in before/after it corresponds to.
    # The unchanged gaps are the lines between hunks' before_ranges in before.
    # We can reconstruct by iterating hunks sorted by before_start, and appending gap + selected hunk content.
    # Let's do that.
    before_lines = _split_lines_with_endings(before_s)
    # after_lines not needed for gaps, but for selected hunks we use added
    result_parts: list[str] = []
    last_before_end = 0  # 0-indexed line number in before
    for hunk in sorted(detailed_hunks, key=lambda h: h["before"]["start"]):
        b_start = hunk["before"]["start"] - 1  # 0-indexed
        b_len = hunk["before"]["lines"]
        # Append gap from before
        if b_start > last_before_end:
            result_parts.extend(before_lines[last_before_end:b_start])
        # Append hunk content: either added (or filtered) if selected, else removed
        idx = hunk["index"]
        if idx in filtered_hunks:
            result_parts.append(filtered_hunks[idx])
        elif idx in selected_hunks:
            result_parts.append(hunk["added"])
        else:
            result_parts.append(hunk["removed"])
        last_before_end = b_start + b_len
    # Append tail gap
    result_parts.extend(before_lines[last_before_end:])
    return "".join(result_parts).encode()


def apply_spec(spec: Spec, file_contents: dict[str, tuple[bytes, bytes]]) -> dict[str, bytes]:
    """Given a spec and a dict of path -> (before, after) bytes, return dict of path -> selected content for the 'keep' side.
    Handles default and per-file specs, hunk-level and line ranges.
    """
    result: dict[str, bytes] = {}
    for path, (before, after) in file_contents.items():
        file_spec = spec.files.get(path)
        # Determine if file should be considered
        if file_spec is None:
            # Use default
            result[path] = after if spec.default == "keep" else before
            continue
        # Use apply helper
        content = apply_spec_to_file_content(before, after, file_spec, spec.default)
        result[path] = content
    # For files not in file_contents but in spec? They are probably not changed, ignore.
    return result


def list_hunks_for_commit(commit, settings=None) -> dict[str, list[dict[str, Any]]]:
    """List detailed hunks for a commit's diff against its parent.
    Returns {path: [hunk_dict, ...]} where each hunk has id, type, removed, added, before/after ranges.
    If commit has no parent (root), returns empty.
    """
    import pyjj

    if not commit.parent_ids:
        return {}
    # Get parent commit
    # Need repo to get parent; commit object should have a way to get parent via repo?
    # For now, we require the caller to provide parent bytes via commit.read_file and parent.read_file
    # This helper is a convenience for CLI that has repo and commit.
    # To avoid needing repo, we will just return empty and let CLI handle per-file
    return {}


def collect_file_contents_for_commit(repo, commit, settings) -> dict[str, tuple[bytes, bytes]]:
    """Collect before/after bytes for each changed file in commit vs its parent.
    Returns {path: (before, after)}.
    """
    if not commit.parent_ids:
        return {}
    parent = repo.get_commit(commit.parent_ids[0])
    # Use commit.diff to get changed paths
    changed = {}
    for entry in commit.diff(parent):
        path = entry.path
        # Skip directories, etc.
        try:
            before = parent.read_file(path) if parent.file_exists(path) else b""
        except Exception:
            before = b""
        try:
            after = commit.read_file(path) if commit.file_exists(path) else b""
        except Exception:
            # Binary or conflict, skip hunk logic, treat as whole file
            before = b""
            after = b""
        changed[path] = (before, after)
    return changed


def spec_to_overrides(repo, commit, spec: Spec, settings=None) -> dict[str, bytes | None]:
    """Convert a Spec into content overrides for split_selected_edited.
    Returns {path: bytes or None} where None means delete, bytes is new content.
    For files where selected content == before, we return None if the file didn't exist before, or before if it did?
    Actually for split, the first commit's content should be selected content.
    If selected content == before (i.e., no changes kept for that file), we should not include that file in overrides,
    and the first commit will have the parent's version (i.e., not keep the changes).
    For simplicity, we return the selected content for each file where it differs from before, and handle
    the case where selected content == before as not overriding (keep parent).
    For files where selected content is different, we return the selected bytes.
    """
    file_contents = collect_file_contents_for_commit(repo, commit, settings)
    selected = apply_spec(spec, file_contents)
    overrides: dict[str, bytes | None] = {}
    for path, (before, after) in file_contents.items():
        sel = selected.get(path, before)
        if sel == before:
            # No change kept for this file in first commit
            # If the file was added (before == b""), and sel == before, then first commit should not have the file
            # That is equivalent to not overriding, but we need to ensure the file is not present
            # For split_selected_edited, we need to explicitly handle added files: if before is empty and sel is empty, we should set None to delete?
            # For now, we will not include this path in overrides if sel == before, and let the parent's version prevail
            # But if the file was newly added and we are not keeping it, the first commit should not have it, which is the parent's state (no file)
            # So not including it is correct.
            continue
        # sel is different from before, so it should be in first commit
        overrides[path] = sel
        # Handle the case where sel == b"" and file was added -> delete?
        # If sel is empty and before was empty (added file but we keep none of its hunks?), then first commit should not have file
        # That's already handled by continue above if sel == before (both empty), but if added file had hunks and we keep none, sel will be before (empty), so continue
        # If we keep some hunks of an added file, sel will be non-empty, so we include.
    # For files where spec says "keep" for a file not in file_contents (i.e., not changed), we don't need to do anything
    return overrides


def load_spec_from_input(spec_str: str | None, spec_file: str | None) -> Spec:
    """Load spec from inline string, file, or stdin ('-'). Handles JSON/YAML."""
    import sys
    from pathlib import Path

    if spec_file:
        content = Path(spec_file).read_text()
        return parse_spec(content)
    if spec_str is None:
        raise ValueError("Spec is required")
    if spec_str == "-":
        content = sys.stdin.read()
        if not content.strip():
            raise ValueError("Spec from stdin is empty")
        return parse_spec(content)
    return parse_spec(spec_str)
