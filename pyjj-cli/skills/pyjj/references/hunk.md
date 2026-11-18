# `pyjj hunk`: hunk-level (sub-file) splitting

Use only when one file mixes concerns and file-level `pyjj split` ([splitting.md](splitting.md)) is not enough.

Subcommands: `list`, `split`, `commit`, `squash`, `schema` (JSON Schema of the spec, also `pyjj hunk --json-schema`).

## Listing

```bash
pyjj hunk list --format text       # compact: file, hunk count, index, type, id
pyjj hunk list                     # JSON (default); --format yaml also
pyjj hunk list -r <rev>            # hunks of another revision (default @)
```

- JSON carries full `removed`/`added` text, `before`/`after` line ranges and `context` per hunk: large. There is no `--include`/`--files`. Start with `--format text`, then read the JSON only for the file at hand:

```bash
pyjj hunk list | jq -c '.files[] | select(.path=="src/foo.py")'
```

- Hunk `type`: `insert`, `delete`, `replace`. Status letter in text: `M`/`A`.
- `index` is 0-based per file. `id` is `hunk-<sha256>`, stable unless the hunk content changes.

## Spec

JSON or YAML:

```json
{
  "files": {
    "src/foo.py": {"hunks": [0, 2]},
    "src/bar.py": {"action": "keep"},
    "src/baz.py": {"action": "reset"}
  },
  "default": "reset"
}
```

| Entry | Effect |
|---|---|
| `{"hunks": [0, 2]}` | those hunk indices |
| `{"ids": ["hunk-..."]}` | those hunks by id |
| `{"lines": [[5, 6]]}` | hunks overlapping these 1-based line ranges of the new file |
| `{"action": "keep"}` / `"reset"` | whole file included / excluded |
| top-level `"default"` | `reset` (default): unlisted files excluded. `keep`: included |

- Unknown keys are rejected (`additionalProperties: false`).
- Line-level choice inside a hunk: an entry of `hunks` may be an object `{"index": N}` (or `{"id": ...}`) with
  - `"lines": [i, ...]`: select those 0-based **added** lines only; the hunk's removed lines stay unremoved.
  - `"added": [...]`, `"removed": [...]`: select added and removed lines explicitly (e.g. `{"index": 0, "removed": [0], "added": [0]}` swaps one line).
- `default: keep` also sweeps in untracked-looking working-copy files (e.g. a spec file you just wrote in the repo).

## Executing

| Command | Result |
|---|---|
| `pyjj hunk split <spec> <msg>` | Two commits: matched hunks first (with `msg`), rest second (the new `@`, keeps the original description). |
| `pyjj hunk commit <spec> <msg>` | One commit with the matched hunks inserted before `@`; the rest stays in the working copy. |
| `pyjj hunk squash <spec>` | Matched hunks into the **parent** of the source revision (`-r`, default `@`). No destination flag, no message. |

- `split` and `commit` require a message; omitting it exits 2. `-` or `--stdin` reads it from stdin.
- `split` and `squash` take `-r <rev>`.
- Spec source: positional, `--spec`, `--spec-file <path>`, or `-` for stdin. With `--spec-file`, the one positional argument is the message. Prefer a spec file past two or three files.
- `--dry-run` writes nothing and reports (`Would write 2 commits.`). `--abort-on-conflict` writes nothing and exits 1 if the rewrite would add conflicts.
- Identity matches plain split: the first commit keeps the original change id; a bookmark on the original moves to the second.

```bash
pyjj hunk split '{"files": {"src/utils.py": {"hunks": [0]}}, "default": "reset"}' 'refactor: extract helper'
pyjj hunk commit '{"files": {"src/bug.py": {"action": "keep"}}}' 'fix: handle null case'
pyjj hunk squash '{"files": {"src/tests.py": {"action": "keep"}}}'
pyjj hunk split --spec-file spec.yaml 'feat: x'
cat spec.json | pyjj hunk commit - 'msg'
```

For a destination farther than the parent: peel with `pyjj hunk split`/`pyjj split`, then `pyjj squash --revision @-` ([splitting.md](splitting.md)).

## Hunk granularity

- Changes separated by at least one unchanged line are separate hunks, even if a unified diff would merge them in one `@@` block. A fix and a new function below it, separated by the usual two blank lines, are two hunks.
- Changed lines that are truly contiguous form one hunk (two adjacent edited lines: one `replace`). Options:
  1. Select by line inside the hunk (`lines`, or `added`/`removed`, above).
  2. Take the whole file with `{"action": "keep"}`.
  3. Commit the unambiguous parts first, keep editing, re-list.

Verified against pyjj-cli v0.1.0-b02afea63cf86f2fad18f4b73a5f507e0eeb84a1 and jj 0.47.
