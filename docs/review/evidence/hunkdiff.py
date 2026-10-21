import importlib.util
spec = importlib.util.spec_from_file_location("pyjj_hunk", "/home/lillecarl/Code/pyjj/pyjj/pyjj/hunk.py")
import sys
H = importlib.util.module_from_spec(spec); sys.modules["pyjj_hunk"] = H; spec.loader.exec_module(H)
"""Compare Rust diff_hunks indices with Python hunk.get_hunks_detailed indices."""
import random, sys
import pyjj_bindings as b
random.seed(1)
cases = [
    ("a\nb\nc\nd\n", "a\nB\nc\nD\n"),
    ("x\na\nb\nx\n", "x\nb\na\nx\n"),
    ("a\nb\nc\n", "c\nb\na\n"),
    ("}\n}\nfoo\n}\n", "}\nbar\n}\nfoo\n}\n}\n"),
]
for _ in range(300):
    base = [random.choice("abc}{x") + "\n" for _ in range(8)]
    new = [l if random.random() > .3 else random.choice("abc}{xy") + "\n" for l in base]
    if random.random() < .5: new.insert(random.randrange(len(new)), "z\n")
    cases.append(("".join(base), "".join(new)))
mism = 0
for i, (bf, af) in enumerate(cases):
    r = [(h.before, h.after) for h in b.diff_hunks(bf.encode(), af.encode())]
    p = [(h["removed"].encode(), h["added"].encode()) for h in H.get_hunks_detailed(bf, af)]
    if r != p:
        mism += 1
        if mism <= 3:
            print("case", i, repr(bf), "->", repr(af)); print("  rust:", r); print("  py:  ", p)
print(f"{mism}/{len(cases)} cases disagree")
