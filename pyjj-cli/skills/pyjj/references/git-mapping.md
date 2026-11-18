# Git to pyjj concept and command mapping

Read first when coming from Git. The two traps: assuming a staging area, and assuming `pyjj commit` behaves like `git commit`.

## Concepts

| Git | pyjj / jj | Difference |
|---|---|---|
| Working tree | Working copy | Same. |
| Index / staging area | None | Nothing to `add`. The working tree is already part of `@`, a real commit, snapshotted on almost every command. |
| `HEAD` | `@` | Always a real commit; no detached state. |
| Branch | Bookmark | Does not move on commit. Moves only when set explicitly or when its commit is rewritten (it follows). No "current branch". |
| `git worktree add` | `pyjj workspace add <path>` | Second working directory on the same repo. |
| `git commit` | `pyjj commit -m 'msg'` | Also creates a new empty child and moves `@` to it. See below. |
| `git commit --amend` | `pyjj describe` (message) or `pyjj squash` (content) | Split in two; `describe` never touches content. |
| `git add -p` + several commits | `pyjj split <fileset>` repeated, or `pyjj hunk` for sub-file granularity | See below. |
| `git reset --soft HEAD~1` | `pyjj squash --use-destination-message` (from the commit being undone) | Folds `@` into its parent, keeping the parent's message. |
| `git reset --hard HEAD` | `pyjj abandon` (on `@`) or `pyjj restore` | Discards `@`'s changes; recoverable via `pyjj undo` / `pyjj op log`. |
| `git checkout <rev>` | `pyjj new <rev>` | New commit on `<rev>`, `@` moves there. No flag needed for an old commit. |
| `git checkout <rev>` then amend in place | `pyjj edit <rev>` | A rewrite: needs explicit request ([safety-and-undo.md](safety-and-undo.md)). |
| `git stash` | `pyjj new <elsewhere>` | Edits already live in commit `@`; navigate away, return with `pyjj new <old @'s change id>` or `pyjj edit`. |
| `git reflog` | `pyjj op log` | Covers commits, bookmarks, workspaces; pairs with `undo` / `op restore`. |
| `git cherry-pick` | `pyjj duplicate` | Rewrite-adjacent: ask first. |
| `git rebase` | `pyjj rebase` | More selection modes (`-s`/`-b`/`-r`); see [rebase-and-merge.md](rebase-and-merge.md). Ask first. |
| `git merge` | `pyjj new <rev1> <rev2>` | Creates the merge commit directly. |
| `git log <revspec>` | `pyjj log -r '<revset>'` | Revset language: [revsets.md](revsets.md). |
| Commit SHA | Commit id (changes on every rewrite) and change id (stable across rewrites) | Refer to a logical commit by change id. |

## `pyjj commit` vs `git commit`

`pyjj commit -m 'msg'` = `pyjj describe -m 'msg'` on `@`, then `pyjj new`. Afterwards `@` is always a fresh empty commit; you never sit on the commit just finished.

```
Before:                      After:
@  edits, no message         @' new, empty (this is @ now)
|                       =>   |
P  parent                    @  same content, described 'msg'
                             |
                             P
```

Finish a task with `commit`. `describe` alone leaves `@` open to absorb unrelated edits.

## `pyjj split` vs `git add -p`

Git: stage part, commit it, repeat; the rest stays uncommitted and new commits land after. pyjj: the edits already are commit `@`; `split` divides it. The matched part becomes the earlier commit and keeps `@`'s original change id. The rest stays `@`, open, with a new change id.

```
Before:                      After:
@  all edits, no message     @  unmatched edits (still open, new change id)
|                       =>   |
P                            K  matched edits, 'msg' (original change id)
                             |
                             P
```

Verified in pyjj (`pyjj split a -m 'only a'`). Split pieces off the front repeatedly while `@` keeps absorbing edits. Default way to turn mixed work into clean commits. See [splitting.md](splitting.md); sub-file granularity: `pyjj hunk` ([hunk.md](hunk.md)).

## Read-only git is fine

`git log --oneline --graph --all`, `git diff`, `git show`, `git status` work in a colocated repo. Never a git write; see [safety-and-undo.md](safety-and-undo.md).

## Quick lookup

| Git | pyjj |
|---|---|
| `git status` | `pyjj status` (`pyjj st`) |
| `git log --oneline -25` | `pyjj log --limit 25 -T builtin_log_compact_full_description` |
| `git show <rev>` | `pyjj show -r <rev> --git` |
| `git diff` | `pyjj diff --git` (working copy vs parent) |
| `git diff <a> <b>` | `pyjj diff --git --from <a> --to <b>` |
| `git add <path>` | nothing; `pyjj file track <path>` only if `snapshot.auto-track` was narrowed |
| `git restore <path>` | `pyjj restore <path>` |
| `git branch` | `pyjj bookmark list` |
| `git branch -d <name>` | `pyjj bookmark forget <name>` (local only) or `pyjj bookmark delete <name>` (propagates on push) |
| `git checkout -b <name>` | `pyjj bookmark create <name>` (does not move `@`) |
| `git tag` | `pyjj tag list` / `pyjj tag set <name> -r <rev>` / `pyjj tag delete <name>` |
| `git push` | `pyjj git push --bookmark <name>` |
| `git fetch` | `pyjj git fetch` |
| `git clone` | `pyjj git clone <url> [<dest>]` |
| `git worktree add <path>` | `pyjj workspace add <path>` |
| `git blame` | `pyjj file annotate <path>` |

Verified against pyjj v0.1.0-b02afea63cf86f2fad18f4b73a5f507e0eeb84a1 and jj 0.47.
