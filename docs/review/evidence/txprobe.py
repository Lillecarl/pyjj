"""Probe Transaction/CommitBuilder lifetime and semantics. One case per subprocess.

usage: python txprobe.py <tmpdir>            (driver)
       python txprobe.py <tmpdir> <case>     (one case)
"""
import subprocess
import sys
import tempfile

import pyjj_bindings as b


def setup(base):
    tmp = tempfile.mkdtemp(dir=base)
    s = b.UserSettings(load_config=False).with_command_args(
        [("config", 'user.name="Repo Settings"'), ("config", 'user.email="repo@x"')]
    )
    ws, repo = b.Workspace.init_internal_git(s, tmp)
    return s, ws, repo


def case_commit_without_rebase(base):
    s, ws, repo = setup(base)
    tx = repo.start_transaction(s)
    root = repo.resolve_single(s, "root()")
    c = tx.new_commit(s, [root.id]).set_description("a").write(repo)
    tx.new_commit(s, [c.id]).set_description("child").write(repo)
    tx.rewrite_commit(s, c).set_description("a2").write(repo)
    try:
        tx.commit("x")
    except BaseException as e:  # noqa: BLE001
        print("raised", type(e).__mro__, str(e)[:120])
    print("repr after:", repr(tx))


def case_builder_after_commit(base):
    s, ws, repo = setup(base)
    tx = repo.start_transaction(s)
    root = repo.resolve_single(s, "root()")
    builder = tx.new_commit(s, [root.id])
    tx.commit("x")
    print("committed; tx repr:", repr(tx), "; now writing stale builder", flush=True)
    c = builder.set_description("after commit").write(repo)
    print("WROTE after commit:", c, flush=True)


def case_builder_after_tx_dropped(base):
    s, ws, repo = setup(base)
    root = repo.resolve_single(s, "root()")
    builder = repo.start_transaction(s).new_commit(s, [root.id])
    import gc
    gc.collect()
    junk = [bytearray(4096) for _ in range(2000)]  # reuse freed memory
    print("tx dropped; writing builder", flush=True)
    c = builder.set_description("dangling").write(repo)
    print("WROTE with dropped tx:", c, flush=True)
    del junk


def case_settings_split(base):
    s, ws, repo = setup(base)
    other = b.UserSettings(load_config=False).with_command_args(
        [("config", 'user.name="Passed Settings"'), ("config", 'user.email="passed@x"')]
    )
    tx = repo.start_transaction(other)
    root = repo.resolve_single(s, "root()")
    c = tx.new_commit(other, [root.id]).write(repo)
    tx.rebase_descendants()
    r2 = tx.commit("x")
    print("author:", c.author.name, "| op user:", r2.operation)


def case_write_wrong_repo(base):
    s, ws, repo = setup(base)
    tx = repo.start_transaction(s)
    root = repo.resolve_single(s, "root()")
    c = tx.new_commit(s, [root.id]).set_description("x").write(repo)
    print("is_hidden against attached repo:", c.is_hidden(repo))
    co = tx.check_out(ws.workspace_name, c)
    print("check_out commit:", co)


CASES = {n[5:]: f for n, f in globals().items() if n.startswith("case_")}

if __name__ == "__main__":
    base = sys.argv[1]
    if len(sys.argv) > 2:
        CASES[sys.argv[2]](base)
        sys.exit(0)
    for name in CASES:
        p = subprocess.run([sys.executable, __file__, base, name], capture_output=True, text=True, timeout=60)
        print(f"== {name}: exit {p.returncode}")
        print(p.stdout.rstrip())
        if p.stderr.strip():
            print("stderr:", p.stderr.strip()[-600:])
