---
name: pyjj-octopus
description: Maintain a fork as several topic branches joined by one octopus merge, with day-to-day work on top of the merge. Load when a repository has an `octopus` bookmark, or when asked to move, squash or absorb work into a topic branch, start a new topic, sync topics with upstream, or resolve conflicts between them. Builds on the pyjj skill.
---

# Octopus fork workflow (pyjj)

## Shape

```
@          work commit: child of octopus. All new work starts here.
octopus    bookmark on an EMPTY merge whose parents are the topic tips
alpha beta gamma ...   topic bookmarks, one per lane
trunk()    the project's main (main@upstream), immutable
```

Setup, once per fork: pin `trunk()` to the project, because the fork's own
`main@origin` goes stale and jj's default `trunk()` may pick it:
```
pyjj config set --repo 'revset-aliases."trunk()"' 'main@upstream'
```
The check reports a `trunk()` that is not on the upstream remote.

- **Topic**: a bookmark on the last commit of its lane. A lane starts on
  `trunk()`, or on another topic when stacked (section H).
- **Octopus**: merge of every topic tip. Holds no changes of its own. Never
  squash, absorb or edit into it.
- **Work commit**: `@`, a child of `octopus`. Finished work moves into a
  topic (recipes below), and `@` is empty again.

**Coming back to the work commit.** Before a recipe, note W:
`pyjj log -r @ --no-graph -T '{{ change_id_short }}'`. A recipe that leaves
`@` elsewhere ends with "back to W": `pyjj edit W` if W still exists and is
not the commit you moved, else `pyjj new octopus`. `pyjj new octopus` while W
holds unfinished work strands it; the check flags that.

Commands are `pyjj`, same flags as jj. `-T` takes Jinja (`{{ change_id_short }}
{{ subject }}`), not jj's template language. Copy revsets exactly.

## The check: run it first and last

```
pyjj python "$(dirname "$(pyjj skill path pyjj-octopus)")/octopus.py" check
```

Lists topics (and which are stacked), then PROBLEM and NOTE lines, each with
the command that fixes it. Ends `OK` (exit 0) or `NOT OK` (exit 1). It also
predicts: topics that conflict with each other, and the commits a sync would
conflict at (fetch first). It writes nothing. `--json` for machine output.

A task is done when the check says `OK` and `@` holds only unfinished work.
NOTE lines never block `OK`; read them, act on the ones your task covers.

Before a rewrite, note `pyjj op log --no-graph --limit 1`; on any mess,
`pyjj op restore <id>` and start over. Most rewrites take `--dry-run`, which
reports `Would write N commits` and any new conflicts. A successful rewrite
prints nothing: run the check or `pyjj log -r 'trunk()::'` to see the result.

`pyjj diff -r octopus`, `pyjj show octopus` and `pyjj log --stat` wrongly list
the topics' files for a merge (a pyjj bug). To see whether the octopus is
empty, use the check or `pyjj log -r octopus`, which says `(empty)`.

## Recipes

X is the change id of the commit being moved; for the work commit it is `@`.

### A. Fixups to lines a topic already owns: absorb

```
pyjj absorb --into 'trunk()..octopus-'
```
Each hunk moves into the topic commit that last touched those lines. Hunks no
topic owns (new files, far-away lines) stay in `@`. The `--into` keeps
absorb out of the octopus. Without it, a line the octopus resolves would land
in the octopus.

### B. Squash changes into a topic's last commit

```
pyjj squash --from @ --into TOPIC PATH...     # only those paths
pyjj squash --from @ --into TOPIC             # everything in @
```
The octopus and `@` follow. `@` keeps what was not named.

### C. Move a finished commit onto a topic as its own commit

Describe it first if needed (`pyjj describe -r X -m "topic: what"`). Then:
```
pyjj rebase -r X -A TOPIC --dry-run   # 0. "New conflicts would appear" here = X depends on another topic: do H first
pyjj rebase -r X -A TOPIC        # 1. insert after the topic's tip; the octopus re-points to X
pyjj bookmark set TOPIC -r X     # 2. the bookmark does NOT follow by itself
pyjj new octopus                 # 3. only if X was @; otherwise @ never moved
```
Use the change id for X in every step, not `@`: after step 1, `@` is X only
by accident.

### D. Start a new topic from a finished commit

```
pyjj rebase -r X -d 'trunk()'                       # 1. onto trunk, beside the others
pyjj bookmark create NAME -r X                      # 2. name the topic
pyjj rebase -r octopus -d 'octopus-' -d NAME        # 3. add it to the merge, keeping the others
pyjj new octopus                                    # 4. only if X was @
```
Not `rebase -r X -A 'trunk()' -B octopus`: that slides X under every topic.

### E. Sync with upstream

```
pyjj git fetch --remote upstream                    # the remote trunk() names
pyjj rebase -b octopus -d 'trunk()' --skip-emptied  # every lane, the octopus and @ move together
```
Run the check after the fetch: it predicts the conflicts and the topics
upstream already has. Run it again after the rebase. `--skip-emptied` drops
commits upstream already has. `@` rides along with its unfinished work; an
empty `@` is replaced by a new one, which is expected. Conflicts: F. A topic
that landed: G.

### F. Resolve conflicts

A conflict spreads to every descendant. Fix only the oldest conflicted commit
of a lane; its descendants heal. Repeat until the check says OK:

```
pyjj log -r 'roots(conflicts())' --no-graph   # the commits to fix (the check names them too)
pyjj new <change id of one root>              # 1. a scratch commit on top of it (note W just before: a sync replaces an empty @)
# 2. edit each conflicted file in the working directory (below)
pyjj resolve --list                           # 3. "No conflicts found at this revision" (exit 1) = done
pyjj diff --git                               # 4. read it: only your resolution, no marker lines left
pyjj squash                                   # 5. fold the resolution into the conflicted commit
                                              # 6. back to W (see "Coming back"); squash left @ inside the lane
```

Editing a file: replace each block from `<<<<<<<` to `>>>>>>>` with the text
that should be there, and keep every line outside the blocks. Write the whole
corrected file with the file-editing tool; do not delete line ranges with
`sed`, which easily leaves half a block behind. A block in the default style:

```
<<<<<<< conflict 1 of 1
+++++++ <commit> "<subject>" (rebase destination)
<one side's text, as is>
%%%%%%% diff from: <commit> ...
\\\\\\\        to: <commit> ...
-<line the other side removed>
+<line the other side added>
>>>>>>> conflict 1 of 1 ends
```
Apply the `%%%%%%%` diff to the `+++++++` text and keep the result. Every one
of those lines, the `\\\\\\\` one too, goes. `pyjj file show` refuses a
conflicted file; read it from the working directory after step 1. The check
flags marker lines that a resolution left behind.

**Never `pyjj resolve --tool :ours` or `:theirs` during a sync.** They take
one side's whole file and drop upstream's other changes to it.

If the only conflicted commit is the octopus, two topics touch the same
lines: H.

### G. A topic landed upstream

After E with `--skip-emptied`, the landed topic's commits are gone and its
bookmark sits on trunk. The check reports it. Then:
```
pyjj simplify-parents -r octopus     # drop the parent that is now part of trunk
pyjj bookmark delete TOPIC
```
If upstream changed it before landing, leftovers may remain: inspect
`pyjj log -r 'trunk()..TOPIC'`, `pyjj abandon` what upstream already has, then
run the two commands above.

### H. Two topics touch the same lines

Signs: the check prints `topics A and B conflict with each other`, or the
octopus is the only conflicted commit, or moving a commit onto a topic would
conflict on that topic alone.

**The later work depends on the earlier topic: stack it.** This is the
default.
```
pyjj rebase -s 'roots(trunk()..LATER)' -d EARLIER   # LATER's lane now starts on EARLIER's tip
```
Resolve any conflict this leaves in LATER's lane (F), then continue the recipe
(for example C onto LATER). The octopus may keep EARLIER as a parent too. The
check prints `stacked on EARLIER`. Cost: LATER can go upstream only after
EARLIER, and every LATER commit gets a new commit id (a pushed LATER must be
force-pushed; ask the user).

**The topics are independent and only collide in text: integrate them.**
```
pyjj new A B -m "integrate: A + B"                    # 1. a merge of the two tips (note W first)
# 2. resolve the conflict in it (F, steps 2-4), no squash needed
pyjj bookmark create integ/A-B -r @
pyjj rebase -r octopus -d 'octopus- ~ A ~ B' -d integ/A-B   # 3. octopus merges the integration instead
# 4. back to W
```
A and B stay independent for upstream. The resolution lives in a named
commit, not in the octopus. Recipes C and B on A or B still work; after a
change to A or B, run the check.

Never resolve in the octopus itself: absorb and squash would then treat it as
a topic.

## Several agents at once

Not yet measured in the labs. What is known: every recipe rewrites the
octopus, which sits under every other workspace's `@`, so the others go
stale. A stale workspace runs `pyjj workspace update-stale`; jj can then
leave its unsaved edits in a divergent sibling of `@`. Until a lab proves
otherwise, let one agent at a time rewrite topics. The check lists other
workspaces' commits on the octopus as notes.

## After rewriting

`pyjj bookmark list` shows rewritten topics as ahead and behind their
`@origin` copy. That is expected until they are pushed. Pushing rewrites the
fork's published branches: ask the user first.
