# Revsets: selecting commits

A revset selects a set of commits. `-r/--revision(s)` takes one on `log`, `diff`, `describe`, `rebase`, and most other commands. Quote the whole expression for the shell.

## Symbols

| Symbol | Meaning |
|---|---|
| `@` | working-copy commit of this workspace |
| `<workspace>@` | working-copy commit of another workspace (`ws2@`) |
| `<name>@<remote>` | remote-tracking bookmark (`main@origin`); `main@git` is the colocated Git ref |
| commit-id or change-id prefix | that commit |

- Resolution order for a bare word: tag, then bookmark, then commit/change id. A bookmark named `7dd1` shadows commit prefix `7dd1`; `commit_id(7dd1)` / `change_id(...)` bypass it.
- A symbol that parses as an expression needs quotes: a bookmark `x-` is `'"x-"'`; bare `x-` is "parents of `x`".
- A bare change id that is divergent is an error. Use `change_id(x)` for all versions, or `x/0`, `x/1` for one.
- Revsets see visible commits only, plus any hidden commit named by id and its ancestors, for that one query. `hidden()` is always empty (alias of `~visible()` evaluated over visible commits), so it cannot list abandoned commits. Find them via `pyjj op log` and `at_operation(op, x)` or `--at-op`.

## Operators, tightest first

| # | Operator | Meaning |
|---|---|---|
| 1 | `f(x)` | function call |
| 2 | `x-`, `x+` | parents, children |
| 3 | `p:x` | string/date pattern (`glob:"a*"`) |
| 4 | `x::`, `::x`, `x::y`, `::` | descendants / ancestors (inclusive) / ancestry path x to y / all |
| 4 | `x..`, `..x`, `x..y`, `..` | not ancestors of x / ancestors of x minus root / ancestors of y minus ancestors of x / all minus root |
| 5 | `~x` | not x |
| 6 | `x & y`, `x ~ y` | intersection, difference |
| 7 | `x \| y` | union |

- Same tier associates left to right: `A::D ~ B & C` is `(A::D ~ B) & C`. `::` binds tighter than `~`: `~B::` is `~(B::)`.
- `x-`/`x+` chain: `x---` is the great-grandparent generation only.
- `..` does not distribute over `|`: `(A|B)..` is `A.. & B..`. Write `A.. | B..` for "after either".

Given `A -> {B, C} -> D` (D merges B and C):

```
D- = {C, B}     B- = {A}        A- = {root()}    D+ = {}
A+ = {C, B}     B+ = {D}        B:: = {D, B}     A:: = {D, C, B, A}
B..D = {D, C}   B::D = {D, B}   B::C = {}        A.. = {D, C, B}
::B = {B, A, root()}            (B|C).. = {D}    B.. | C.. = {D, C}
```

## Functions

Graph:

| Function | Meaning |
|---|---|
| `parents(x, [n])`, `children(x, [n])` | exactly the n-th generation: `parents(x, 3)` = `x---`. Default 1 |
| `ancestors(x, [n])`, `descendants(x, [n])` | `::x`, `x::`, limited to n generations |
| `first_parent(x, [n])`, `first_ancestors(x, [n])` | follow only the first parent |
| `reachable(srcs, domain)` | everything reachable from srcs through parent/child edges without leaving `domain`: `reachable(@, mutable())` is the whole stack you are on |
| `connected(x)` | `x::x` |
| `heads(x)`, `roots(x)` | members with no descendant / no ancestor in `x` |
| `fork_point(x)` | common ancestor of all of `x`; `x` itself if one commit |

Sets: `all()`, `none()`, `root()`, `visible_heads()` (= `heads(all())`), `working_copies()` (the `@` of every workspace).

Identity and refs:

| Function | Meaning |
|---|---|
| `change_id(p)`, `commit_id(p)` | by prefix; ambiguous prefix errors; a divergent change gives several |
| `bookmarks([pat])`, `tags([pat])` | local targets. A pattern that matches nothing gives an empty set, not an error |
| `remote_bookmarks([pat], [remote=pat])`, `remote_tags(...)` | remote targets; `@git` excluded unless `remote="git"` or `"*"` |
| `tracked_remote_bookmarks(...)`, `untracked_remote_bookmarks(...)` | subsets |

Content and metadata:

| Function | Meaning |
|---|---|
| `description(p)`, `subject(p)` | whole message (ends with `\n`) / first line |
| `author(p)`, `author_name(p)`, `author_email(p)` and `committer*` | |
| `author_date(d)`, `committer_date(d)` | date pattern |
| `mine()` | author email is the configured `user.email` |
| `files(fileset)` | commits touching matching paths, see [filesets.md](filesets.md). Quote bare `.`: `files(".")` |
| `diff_lines(text, [files])`, `diff_lines_added(...)`, `diff_lines_removed(...)` | commits whose diff has a matching line |
| `empty()` | no file changes; includes content-free merges and `root()` |
| `conflicts()`, `merges()`, `divergent()`, `signed()` | |

Utilities:

| Function | Meaning |
|---|---|
| `present(x)` | `none()` instead of an error when a name does not exist |
| `coalesce(x, y, ...)` | first non-empty argument |
| `exactly(x, n)` | `x`, errors unless it has exactly n members: guard for commands needing one commit |
| `bisect(x)` | splits `x` roughly in half by descendant count |
| `at_operation(op, x)` | evaluate `x` as of operation `op` |

## String and date patterns

- Prefixes: `exact:`, `glob:`, `regex:` (substring search), `substring:`. Append `-i` for case-insensitive: `glob-i:"fix*"`.
- A bare string is `glob:` and must match the whole value. `description("fix")` matches nothing; use `description(substring:"fix")` or `description("*fix*")`. `description(exact:"fix: x")` also fails: the description ends with `\n`; use `subject(exact:"fix: x")`.
- Combine inside a pattern: `bookmarks(~glob:"ci/*")`, `bookmarks(exact:"a" | exact:"b")`.
- Dates: `after:"<date>"` (inclusive), `before:"<date>"` (strict). Forms: `2024-02-01`, `2024-02-01T12:00:00-08:00`, `2 days ago`, `5 minutes ago`, `yesterday`, `yesterday 5pm`. An unparsable date is a parse error.

## Built-in aliases

- `trunk()`: main/master/trunk bookmark on the default remote; `root()` when none. A local-only `main` does not count: with no remote, `trunk()` is `root()`, everything is mutable, and `trunk()..@` is all of history.
- `immutable_heads()` = `trunk() | tags() | untracked_remote_bookmarks()`. `immutable()` = `::(immutable_heads() | root())`. `mutable()` = `~immutable()`. Rewrites of immutable commits fail unless `--ignore-immutable`.
- `visible()` = `::visible_heads()`.

Custom aliases (a quoted function-style key needs quoting in the dotted path; both work):

```
pyjj config set --repo 'revset-aliases."trunk()"' main
pyjj config set --repo 'revset-aliases."mine_recent()"' 'mine() & author_date(after:"2 weeks ago")'
```

## Examples

```
pyjj log -r '@-'
pyjj log -r 'trunk()..@'                    # local work not on trunk
pyjj log -r 'remote_bookmarks()..'          # not on any remote
pyjj log -r 'reachable(@, mutable())'       # the mutable stack around @
pyjj log -r 'conflicts()'
pyjj log -r 'description(glob:"fix:*")'
pyjj log -r 'author(substring:"alice") & author_date(after:"yesterday")'
pyjj log -r 'files("src") & ~merges()'
pyjj diff -r 'A::B'                         # ancestry path from A to B
pyjj diff -r 'A..B'                         # everything B has that A lacks
```

## Templates

`-T` takes Jinja2 here, not jj's template language. Variables: `{{ change_id_short }}`, `{{ commit_id_short }}`, `{{ subject }}`, `{{ description }}`, `{{ bookmarks_str }}`, `{{ empty }}`, `{{ conflict }}`, `{{ author }}`. `pyjj log` ends each commit with a newline even when the template has none (jj concatenates). `{{ subject }}` prints `(no description set)` for an empty description.

```
pyjj log --no-graph -r 'mutable()' -T '{{ commit_id_short }} {{ subject }}'
```

Verified against pyjj v0.1.0-b02afea63cf86f2fad18f4b73a5f507e0eeb84a1 and jj 0.47.
