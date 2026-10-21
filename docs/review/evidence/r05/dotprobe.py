from pyjj.graph_dot import PlanError, parse_dot, resolve_abandons, resolve_plan, render_dot

# M merges A and B; A sits on B. Abandon A: jj's new_parents dedups to [B].
nodes = ["M", "A", "B"]
edges = {"M": [("A", "direct"), ("B", "direct")], "A": [("B", "direct")], "B": [("root", "direct")]}
current = {"M": ["A", "B"], "A": ["B"], "B": ["root"]}
kept, resolved, abandons = resolve_abandons(nodes, edges, current, {"A"})
print("resolved M:", resolved["M"])
try:
    print("plan:", resolve_plan(kept, resolved, current))
except PlanError as e:
    print("PlanError:", e)

# A real node whose label is "(not shown)" disappears on parse.
text = render_dot([("X", [("Y", "direct")]), ("Y", [])], {"X": "(not shown)"})
print("parsed nodes:", parse_dot(text)[0])
# Combined style is read as direct.
print("dashed,bold:", parse_dot('digraph { a -> b [style="dashed,bold"] }')[1])
