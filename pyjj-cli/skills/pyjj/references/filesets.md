# Filesets: selecting files

A fileset selects files, as a revset selects commits. It is the argument language jj gives `diff`, `split`, `restore`, `file list`, and others.

## Where pyjj parses filesets

- Full fileset language (verified): the `files()` revset (`pyjj log -r 'files(...)'`) and `pyjj file delete`.
- Every other path-taking command (`diff`, `status`, `log`, `split`, `restore`, `squash`, `absorb`, `commit`, `file list|show|annotate|track|untrack|edit|chmod`, `interdiff`, `fix`, `resolve`) treats each argument as a plain path prefix. `glob:"*.lock"`, `~src`, `src | docs`, `root:x`, `all()` fail there with `Warning: No matching entries for paths: ...` and select nothing (pyjj differs from jj here; bug reported).
- Plain paths work everywhere: cwd-relative, absolute allowed, directories match recursively, `src/`, `./src`, `src/../docs` fine. Several paths are a union. To express exclusion or globs on those commands, pass the explicit paths; or select commits with `files(...)` and list paths with `pyjj diff -s -r ...`.
- `files()` resolves patterns against the workspace root, not the cwd (pyjj differs from jj here; bug reported): `cwd:`, `file:`, `glob:` and bare paths from a subdirectory behave as if run at the root, and `..` is rejected. Run from the root and use root-relative paths.
- `pyjj file list` prints repo-relative paths from a subdirectory; jj prints cwd-relative.

## File patterns

A bare `"path"` is `prefix-glob:`: matches the file, or everything under a directory.

| Pattern | Meaning |
|---|---|
| `cwd:"p"` | cwd-relative prefix (file, or directory recursively) |
| `file:"p"`, `cwd-file:"p"` | exactly that file; a directory matches nothing |
| `glob:"g"`, `cwd-glob:"g"` | cwd-relative wildcard |
| `prefix-glob:"g"`, `cwd-prefix-glob:"g"` | glob that also matches under matching directories |
| `root:"p"`, `root-file:"p"`, `root-glob:"g"`, `root-prefix-glob:"g"` | same, relative to the workspace root |

- Append `-i` for case-insensitive globs: `glob-i:"**/*.txt"`.
- Glob `*` does not cross `/`; `**` does. `glob:"*.rs"` matches only a top-level `.rs` file, not `src/main.rs`; use `glob:"**/*.rs"`. `glob:"s*"` does not match `src/x`, `prefix-glob:"s*"` does.
- `prefix-glob:"*.d"` = `glob:"*.d" | glob:"*.d/**"`. Bare `"**/*.lock"` works, so lock files at any depth need no `glob:`.
- Quote a path only when it holds spaces or metacharacters, or sits next to an operator: `'"dir with space"'`, `'~"dir with space"'`. Unquoted `dir with space` is a syntax error in `files()`.

## Operators, tightest first

| # | Operator | Meaning |
|---|---|---|
| 1 | `f(x)` | function call |
| 2 | `p:x` | pattern |
| 3 | `~x` | everything except x |
| 4 | `x & y`, `x ~ y` | both / x without y |
| 5 | `x \| y` | either |

`"src" ~ "src/sub" | "docs"` is `("src" ~ "src/sub") | "docs"`.

Functions: `all()`, `none()`.

## Aliases

```
pyjj config set --repo 'fileset-aliases.LOCK' '"**/Cargo.lock" | "**/package-lock.json"'
pyjj config set --repo 'fileset-aliases."locks()"' 'glob:"**/*.lock"'
```

Use as `files(LOCK)`, `files(~LOCK)`, `files(locks())`. An alias resolves at the root like any `files()` pattern.

## Examples

```
pyjj log -r 'files("src")'
pyjj log -r 'files(~glob:"*.lock")'                     # any file except top-level *.lock
pyjj log -r 'files(glob:"**/*.rs" ~ "**/test*")'        # rust files outside test-ish paths
pyjj log -r 'files("src" ~ glob:"**/*test*")'
pyjj file delete 'glob:"**/*.py"'                       # rewrite @ without every .py file
pyjj split src/main.rs -m '...'                         # plain path: main.rs goes in the first commit
```

Verified against pyjj v0.1.0-b02afea63cf86f2fad18f4b73a5f507e0eeb84a1 and jj 0.47.
