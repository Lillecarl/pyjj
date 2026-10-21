"""Probes for reviewer 04 (leaf Rust modules). usage: python -I leafprobe.py <tmpdir>"""
import sys
import tempfile

import pyjj_bindings as b

base = sys.argv[1]


def setup():
    tmp = tempfile.mkdtemp(dir=base)
    s = b.UserSettings(load_config=False).with_command_args(
        [("config", 'user.name="T"'), ("config", 'user.email="t@x"')]
    )
    ws, repo = b.Workspace.init_internal_git(s, tmp)
    return s, ws, repo


def mk(tx, s, repo, parents, files):
    c = tx.new_commit(s, parents).write(repo)
    return tx.edit_commit_tree(c, files).write(repo)


def show(label, c):
    out = {}
    for p in c.list_files():
        out[p] = c.read_file(p)
    print(label, out)


# 1. hunk selection with paths=None leaks other files; full deletion becomes empty file
s, ws, repo = setup()
tx = repo.start_transaction(s)
root = repo.resolve_single(s, "root()")
c1 = mk(tx, s, repo, [root.id], {"a.txt": b"1\n2\n", "b.txt": b"y\n"})
c2 = mk(tx, s, repo, [c1.id], {"a.txt": None, "b.txt": b"y2\n", "c.txt": b"new\n"})
show("c1", c1)
show("c2", c2)
hunks = b.diff_hunks(b"1\n2\n", b"")
print("hunks a.txt:", len(hunks))
first = tx.split_selected(c2, None, {"a.txt": list(range(len(hunks)))}).write(repo)
show("split first (asked: only a.txt deletion hunks)", first)
first2 = tx.split_selected(c2, None, {"c.txt": []}).write(repo)
show("split first (asked: zero hunks of c.txt)", first2)

# 2. fix key collision: same content at two paths
s, ws, repo = setup()
tx = repo.start_transaction(s)
root = repo.resolve_single(s, "root()")
c = mk(tx, s, repo, [root.id], {"x.rs": b"same\n", "x.txt": b"same\n"})
files = tx.fix_enumerate(s, c.id.hex())
print("enumerate:", [(f.path, f.key) for f in files])
fixes = {f.key: b"FORMATTED\n" for f in files if f.path.endswith(".rs")}
summary = tx.fix_apply(s, fixes, c.id.hex())
new = repo  # unused
for old, newid in summary.rewrites.items():
    print("rewrote", old, "->", newid)
    nc = tx.revset(s, newid.hex()) if hasattr(tx, "revset") else None
print("summary fixed", summary.num_fixed_commits)
tx.rebase_descendants()
repo2 = tx.commit("fix")
nc = repo2.get_commit(list(summary.rewrites.values())[0])
show("after fix (only .rs given new content)", nc)
