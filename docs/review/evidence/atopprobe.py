"""revset at_operation() pointing at a descendant op, evaluated on an older repo."""
import sys, tempfile
import pyjj_bindings as b
tmp = tempfile.mkdtemp(dir=sys.argv[1])
s = b.UserSettings(load_config=False).with_command_args(
    [("config", 'user.name="T"'), ("config", 'user.email="t@x"')])
ws, old = b.Workspace.init_internal_git(s, tmp)
tx = old.start_transaction(s)
root = old.resolve_single(s, "root()")
tx.new_commit(s, [root.id]).set_description("new").write(old)
new = tx.commit("op2")
expr = f"at_operation({new.operation_id}, visible_heads())"
for name, fn in [("revset", lambda: old.revset(s, expr)),
                 ("log_graph", lambda: old.log_graph(s, expr)),
                 ("revset ~", lambda: old.revset(s, expr + " ~ root()"))]:
    try:
        r = fn(); print(name, "->", len(r), "results")
    except BaseException as e:
        print(name, "->", type(e).__name__, str(e)[:160])
