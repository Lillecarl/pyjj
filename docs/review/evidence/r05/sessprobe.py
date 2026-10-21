"""Probe pyjj.session (Repo/Atomic). One case per subprocess.

usage: python sessprobe.py <basedir>          (driver)
       python sessprobe.py <basedir> <case>   (one case)
"""
import os
import subprocess
import sys
import tempfile

import pyjj
import pyjj_bindings as b


def mkrepo(base):
    tmp = tempfile.mkdtemp(dir=base)
    s = b.UserSettings(load_config=False).with_command_args(
        [("config", 'user.name="T"'), ("config", 'user.email="t@x"')])
    b.Workspace.init_internal_git(s, tmp)
    return tmp


def open_repo(path):
    os.environ.setdefault("JJ_USER", "T")
    os.environ.setdefault("JJ_EMAIL", "t@x")
    return pyjj.open(path)


def write(path, name, text):
    with open(os.path.join(path, name), "w") as f:
        f.write(text)


def desc(repo, rev):
    c = repo.resolve(rev)
    return c.description.strip(), c.change_id.reverse_hex()[:8]


def case_split_non_wc(base):
    p = mkrepo(base)
    repo = open_repo(p)
    write(p, "a", "a\n"); write(p, "b", "b\n")
    with repo.atomic("c1") as tx:
        tx.commit(message="ab")          # @- = ab, @ = empty
    print("before: @ =", desc(repo, "@"), "@- =", desc(repo, "@-"))
    with repo.atomic("split") as tx:
        first, second = tx.split("@-", paths=["a"], message="only a")
    print("after:  @ =", desc(repo, "@"), "@- =", desc(repo, "@-"))
    print("@ parents:", [repo._repo.get_commit(i).description.strip() for i in repo.resolve("@").parent_ids])


def case_rebase_after_moved(base):
    p = mkrepo(base)
    repo = open_repo(p)
    for n in ("x", "y", "z"):
        write(p, n, n + "\n")
        with repo.atomic(n) as tx:
            tx.commit(message=n)
    try:
        with repo.atomic("two-step") as tx:
            print("x desc repr:", repr(repo.resolve("@---").description))
            tx.describe("description(substring:'y')", message="y2")
            tx.rebase("description(substring:'x')", after="description(substring:'y2')")
        print("ok; order:", [c.description.strip() for c in repo.revset("::@ & ~root()")])
        print("ok")
    except Exception as e:
        print("raised", type(e).__name__, str(e)[:300])


def case_new_leaves_empty(base):
    p = mkrepo(base)
    repo = open_repo(p)
    with repo.atomic("n") as tx:
        tx.new("@")
    print("empty undescribed non-root commits:",
          len(repo.revset("empty() & description(exact:'') & ~root() & ~@")))


def case_error_type(base):
    p = mkrepo(base)
    repo = open_repo(p)
    try:
        with repo.atomic("bad") as tx:
            tx.describe("nonexistent_xyz", message="m")
    except pyjj.RevsetEvalError:
        print("caught as RevsetEvalError")
    except pyjj.JjError:
        print("caught as JjError")
    except pyjj.PyjjError as e:
        print("only PyjjError; cause:", type(e.__cause__).__name__, "cause.cause:",
              type(getattr(e.__cause__, "__cause__", None)).__name__)


def case_failed_block_writes(base):
    p = mkrepo(base)
    repo = open_repo(p)
    before = repo.operation_id
    write(p, "dirty", "d\n")
    try:
        with repo.atomic("fail") as tx:
            raise RuntimeError("boom")
    except RuntimeError as e:
        print("raised", e, "cause is self:", e.__cause__ is e)
    repo.reload()
    print("op changed after failed block:", repo.operation_id != before)


def case_squash_root_child(base):
    p = mkrepo(base)
    repo = open_repo(p)
    write(p, "a", "a\n")
    try:
        with repo.atomic("sq") as tx:
            tx.squash("@-")   # @- is root()'s child? here @- is root
    except BaseException as e:
        print("raised", type(e).__mro__[:2], str(e)[:200])


def case_squash_merge(base):
    p = mkrepo(base)
    repo = open_repo(p)
    with repo.atomic("m") as tx:
        a = tx.new("root()", message="A", edit=False)
        bb = tx.new("root()", message="B", edit=False)
        tx.new([a.id.hex(), bb.id.hex()], message="M")
    write(p, "f", "f\n")
    try:
        with repo.atomic("sq") as tx:
            tx.squash("@")
        print("squash of a merge went into:", desc(repo, "@-") if False else "first parent (no error)")
    except BaseException as e:
        print("raised", type(e).__name__, str(e)[:200])


def case_second_block_after_checkout(base):
    p = mkrepo(base)
    repo = open_repo(p)
    write(p, "a", "a\n")
    with repo.atomic("c") as tx:
        tx.commit(message="A")
    write(p, "b", "b\n")
    with repo.atomic("d") as tx:
        tx.describe("@", message="B")
    c = repo.resolve("@")
    print("@ =", c.description.strip(), "files:", sorted(c.list_files()))
    print("@- files:", sorted(repo.resolve("@-").list_files()))


CASES = {k[5:]: v for k, v in dict(globals()).items() if k.startswith("case_")}

if __name__ == "__main__":
    base = sys.argv[1]
    if len(sys.argv) == 3:
        CASES[sys.argv[2]](base)
        sys.exit(0)
    for name in CASES:
        r = subprocess.run([sys.executable, __file__, base, name], capture_output=True, text=True, timeout=60)
        print(f"== {name}: exit {r.returncode}")
        print(r.stdout.rstrip())
        if r.stderr.strip():
            print("stderr:", r.stderr.strip()[-600:])
