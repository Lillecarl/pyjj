"""Probe pyjj.hunk edge cases (pure Python plus one repo case)."""
import os
import sys
import tempfile

import pyjj_bindings as b
from pyjj import hunk as H


def spec(files, default="reset"):
    import json
    return H.parse_spec(json.dumps({"files": files, "default": default}))


def show(label, value):
    print(f"{label}: {value!r}")


# 1. no trailing newline: change last line only
before, after = b"a\nb", b"a\nc"
hs = H.get_hunks_detailed(before.decode(), after.decode())
show("no-eol hunks", [(h["removed"], h["added"]) for h in hs])
show("no-eol keep all", H.apply_spec_to_file_content(before, after, spec({"f": {"hunks": [0]}}).files["f"], "reset"))
# adding a trailing newline only
hs = H.get_hunks_detailed("a", "a\n")
show("add-eol hunks", [(h["removed"], h["added"]) for h in hs])

# 2. CRLF
before, after = b"a\r\nb\r\n", b"a\r\nB\r\n"
show("crlf keep", H.apply_spec_to_file_content(before, after, spec({"f": {"hunks": [0]}}).files["f"], "reset"))
# lone CR / unicode line separators survive?
before, after = "x y\n".encode(), "x z\n".encode()
show("u2028 keep", H.apply_spec_to_file_content(before, after, spec({"f": {"hunks": [0]}}).files["f"], "reset"))

# 3. empty files
show("empty->content hunks", [(h["type"], h["before"]) for h in H.get_hunks_detailed("", "x\n")])
show("empty->content keep", H.apply_spec_to_file_content(b"", b"x\n", spec({"f": {"hunks": [0]}}).files["f"], "reset"))

# 4. binary: hunk selection silently resets
show("binary hunks[0]", H.apply_spec_to_file_content(b"\xff\x00a", b"\xff\x00b", spec({"f": {"hunks": [0]}}).files["f"], "reset"))
show("binary lines", H.apply_spec_to_file_content(b"\xff\x00a", b"\xff\x00b", spec({"f": {"lines": [[1, 2]]}}).files["f"], "reset"))

# 5. per-hunk lines on a replace hunk: removed lines vanish
before, after = b"old1\nold2\n", b"new1\nnew2\n"
show("replace keep added line 0", H.apply_spec_to_file_content(before, after, spec({"f": {"hunks": [{"index": 0, "lines": [0]}]}}).files["f"], "reset"))
# per_hunk_removed semantics: lines listed are KEPT in file (opposite of "select deletion")
before, after = b"a\nb\nc\n", b""
show("delete hunk removed_lines=[0]", H.apply_spec_to_file_content(before, after, spec({"f": {"hunks": [{"index": 0, "removed_lines": [0]}]}}).files["f"], "reset"))

# 6. line range [n, n] is accepted (empty under end-exclusive) ; delete hunk never matched by ranges
s6 = spec({"f": {"lines": [[2, 2]]}})
show("lines [2,2] accepted", s6.files["f"].line_ranges)
show("delete hunk vs lines [1,3]", H.apply_spec_to_file_content(b"a\nb\nc\n", b"a\nc\n", spec({"f": {"lines": [[1, 3]]}}).files["f"], "reset"))

# 7. id + lines: pydantic path silently drops lines; manual path raises
try:
    s7 = spec({"f": {"hunks": [{"id": "hunk-ab", "lines": [0]}]}})
    show("id+lines (pydantic)", (s7.files["f"].selection.ids, s7.files["f"].per_hunk_lines))
except ValueError as e:
    show("id+lines raised", str(e)[:120])
H.HAS_PYDANTIC = False
try:
    s7 = spec({"f": {"hunks": [{"id": "hunk-ab", "lines": [0]}]}})
    show("id+lines (manual)", s7.files["f"].selection.ids)
except ValueError as e:
    show("id+lines (manual) raised", str(e)[:120])
# bool accepted as index
show("bool index (manual)", spec({"f": {"hunks": [True]}}).files["f"].selection.indices)
H.HAS_PYDANTIC = True
show("bool index (pydantic)", spec({"f": {"hunks": [True]}}).files["f"].selection.indices)

# 8. action plus hunks: hunks ignored
show("action reset + hunks", H.apply_spec_to_file_content(b"a\n", b"b\n", spec({"f": {"action": "reset", "hunks": [0]}}).files["f"], "keep"))

# 9. repo: deleted file with keep -> spec_to_overrides gives b"" not None
base = sys.argv[1]
p = tempfile.mkdtemp(dir=base)
import pyjj
b.Workspace.init_internal_git(b.UserSettings(), p)
for n in ("gone.txt", "bin.dat"):
    with open(os.path.join(p, n), "wb") as f:
        f.write(b"x\n" if n == "gone.txt" else b"\xff\x00\x01")
r = pyjj.open(p)
with r.atomic("c") as tx:
    tx.commit(message="base")
os.remove(os.path.join(p, "gone.txt"))
with open(os.path.join(p, "bin.dat"), "wb") as f:
    f.write(b"\xff\x00\x02")
r.snapshot()
wc = r.resolve("@")
contents = H.collect_file_contents_for_commit(r._repo, wc, r.settings)
show("collected", contents)
ov = H.spec_to_overrides(r._repo, wc, spec({}, default="keep"), r.settings)
show("overrides default=keep", ov)
show("list_hunks_for_commit", H.list_hunks_for_commit(wc))
