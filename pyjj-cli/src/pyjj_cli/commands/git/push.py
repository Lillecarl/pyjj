"""git subcommand: git_push."""
import fnmatch
import sys

import pyjj
from ..common import (
    _start_transaction,
    CommandError,
    _finish,
    _load,
)

#: The remote jj falls back to when nothing else names one.
_DEFAULT_REMOTE = "origin"

#: The local Git-tracking remote a colocated repository has. It is not a
#: remote anyone pushes to, so it never counts as "the only one".
_GIT_REMOTE = "git"

#: The name `--change` gives a bookmark it creates. jj builds it from
#: `templates.git_push_bookmark`, whose default is `"push-" ++
#: change_id.short()`. A template a user changed would need jj's
#: template language, which pyjj-cli renders with Jinja, so only the
#: default is supported.
_CHANGE_PREFIX = "push-"
_CHANGE_ID_LENGTH = 12


class _Refused(Exception):
    """One ref update jj will not make.

    A bookmark the user named is an error. One selected in bulk is a
    warning, and that bookmark alone is skipped.
    """


def git_push(args) -> int:
    """`jj git push` -- push bookmarks to a Git remote."""
    try:
        settings, ws, repo = _load(args)
        remote = _remote(args, repo, settings)
        updates, created = _updates(args, repo, settings, remote)
        if not updates:
            print("Nothing changed.")
            return 0
        print(f"Changes to push to {remote}:")
        for name, before, after in updates:
            print(f"  {_update_term(before, after)} bookmark {name}")
        if getattr(args, "dry_run", False):
            # jj stops before it writes anything, so a bookmark that
            # `--change` or `--named` would have created stays uncreated.
            print("Dry-run requested, not pushing.")
            return 0
        tx = _start_transaction(repo, settings)
        for name, target in created.items():
            tx.set_bookmark(name, target)
        stats = tx.git_push_updates(settings, remote, updates)
        rejected = list(stats["rejected"]) + list(stats["remote_rejected"])
        for name, reason in rejected:
            print(f"Error: {name} rejected: {reason or 'no reason given'}",
                  file=sys.stderr)
        if not stats["pushed"] and rejected:
            return 1
        _finish(tx, f"push to {remote}", settings, ws, repo)
        if rejected:
            print("Error: Failed to push some bookmarks", file=sys.stderr)
            return 1
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError, pyjj.JjError,
            CommandError) as e:
        print(f"Error: {getattr(e, 'message', e)}", file=sys.stderr)
        return 1
    return 0


def _remote(args, repo, settings) -> str:
    """`--remote`, else `git.push`, else the only remote, else origin."""
    named = getattr(args, "remote", None)
    if named:
        return named
    configured = settings.get_string("git.push")
    if configured:
        return configured
    remotes = [name for name in _remote_names(repo) if name != _GIT_REMOTE]
    if len(remotes) == 1:
        return remotes[0]
    return _DEFAULT_REMOTE


def _remote_names(repo) -> list:
    """Every remote the repository knows, whatever shape it reports."""
    try:
        remotes = repo.git_remotes()
    except Exception:
        return []
    return [r if isinstance(r, str) else r[0] for r in remotes]


def _update_term(before, after) -> str:
    if before is None:
        return "Add"
    if after is None:
        return "Delete"
    return "Move forward"


def _updates(args, repo, settings, remote):
    """What to push, as `[(name, before, after)]`, and the bookmarks
    `--change` and `--named` have to create first.

    `before` is the commit the remote is expected to hold and `after`
    the one to put there, both as `CommitId` or `None`. This is jj's
    selection, which differs per flag in two ways: which names it looks
    at, and whether creating or deleting a remote ref is allowed.
    """
    local = {b.name: b for b in repo.bookmarks()}
    remotes = {b.name: b for b in repo.remote_bookmarks() if b.remote == remote}
    names = sorted(set(local) | set(remotes))
    deleted = getattr(args, "deleted", False)
    validator = _Validator(args, repo, settings, remote)
    created = {}
    updates = []
    seen = set()

    def take(name, allow_new, allow_delete, strict):
        """Classify one name, and keep it if there is anything to push.

        `strict` is whether the reader named this bookmark. jj refuses
        the whole command when a bookmark it was told to push cannot be,
        and warns and skips when it picked the bookmark itself.
        """
        if name in seen:
            return
        seen.add(name)
        try:
            update = _classify(name, remote, local.get(name),
                               remotes.get(name), allow_new, allow_delete)
            if update is not None:
                refusal = validator.refusal(update[2])
                if refusal is not None:
                    raise _Refused(refusal)
        except _Refused as refusal:
            if strict:
                raise CommandError(str(refusal)) from None
            print(f"Warning: {refusal}", file=sys.stderr)
            return
        if update is not None:
            updates.append(update)

    if getattr(args, "all_flag", False):
        for name in names:
            take(name, True, deleted, strict=False)
    elif getattr(args, "tracked", False):
        for name in names:
            if name in remotes and remotes[name].tracked:
                take(name, False, deleted, strict=False)
    elif deleted:
        for name in names:
            if name not in local:
                take(name, False, True, strict=False)
    else:
        created = _create_bookmarks(args, repo, settings, local, remotes)
        for name, target in created.items():
            local[name] = _Created(name, target)
            take(name, True, False, strict=True)
        patterns = list(getattr(args, "bookmarks", None) or [])
        for name in names:
            if not any(_matches(name, pattern) for pattern in patterns):
                continue
            # A name with no local bookmark and an untracked remote one
            # is not a deleted bookmark, so it is not pushed at all.
            if name not in local and not (name in remotes
                                          and remotes[name].tracked):
                continue
            take(name, not _has_tracked_remote(repo, name), True, strict=True)
        for name in _by_revisions(args, repo, settings, remote, local):
            take(name, False, False, strict=False)

    return updates, created


class _Created:
    """A local bookmark `--change` or `--named` is about to create. It
    does not exist in the repository yet, so classification reads it
    from here rather than from the view."""

    has_conflict = False
    removed_ids = ()

    def __init__(self, name, target):
        self.name = name
        self.target_ids = [target]


def _by_revisions(args, repo, settings, remote, local):
    """The bookmarks jj adds from `-r`, or from its default revset.

    The default is `remote_bookmarks(remote=<remote>)..@`, narrowed to
    the commits a bookmark or a tag points at: the work this workspace
    has built on top of what the remote already holds.
    """
    revisions = list(getattr(args, "revisions", None) or [])
    explicit = (revisions or getattr(args, "bookmarks", None)
                or getattr(args, "changes", None)
                or getattr(args, "named", None))
    if revisions:
        expressions = [f"({expr}) & (bookmarks() | tags())"
                       for expr in revisions]
    elif explicit:
        # `-b`, `--change` or `--named` named the bookmarks outright, so
        # the default revset does not run at all.
        return []
    else:
        expressions = [f'remote_bookmarks(remote=exact:"{remote}")..@'
                       " & (bookmarks() | tags())"]
    targets = set()
    for expression in expressions:
        for commit in repo.revset(settings, expression):
            targets.add(commit.id.hex())
    return [name for name, bookmark in sorted(local.items())
            if any(i.hex() in targets for i in bookmark.target_ids)]


def _create_bookmarks(args, repo, settings, local, remotes):
    """The bookmarks `--change` and `--named` create, name to target.

    Neither moves a bookmark that already exists: jj refuses rather
    than guessing which of the two the reader meant.
    """
    created = {}
    for expression in getattr(args, "changes", None) or []:
        for commit in repo.revset(settings, expression):
            name = (_CHANGE_PREFIX
                    + commit.change_id.reverse_hex()[:_CHANGE_ID_LENGTH])
            _ensure_new(name, commit.id, local, remotes, reuse=True)
            created[name] = commit.id
    for spec in getattr(args, "named", None) or []:
        name, target = _parse_named(spec, repo, settings)
        _ensure_new(name, target, local, remotes, reuse=False)
        created[name] = target
    return created


def _ensure_new(name, target, local, remotes, reuse: bool) -> None:
    """`reuse` is whether an existing bookmark already at `target` is
    allowed. `--change` names a revision, so a bookmark that already
    says the same thing is what it asked for; `--named` names the
    bookmark itself, so any existing one is a collision."""
    existing = local.get(name)
    if existing is not None:
        if reuse and [i.hex() for i in existing.target_ids] == [target.hex()]:
            return
        raise CommandError(f"Bookmark already exists: {name}")
    if name in remotes and remotes[name].tracked:
        raise CommandError(
            f"Tracked remote bookmarks exist for deleted bookmark: {name}")


def _parse_named(spec, repo, settings):
    """`--named NAME=REVISION`, split at the first `=`."""
    name, sep, revision = spec.partition("=")
    if not sep or not name or not revision:
        raise CommandError(
            f"Argument '{spec}' must have the form NAME=REVISION, with both "
            "NAME and REVISION non-empty")
    commits = repo.revset(settings, revision)
    if len(commits) != 1:
        raise CommandError(
            f"Revset '{revision}' resolved to {len(commits)} revisions")
    return name, commits[0].id


def _matches(name: str, pattern: str) -> bool:
    """jj's string patterns, as far as a bookmark name needs them: a
    bare pattern is a glob, and the three prefixes name the rest."""
    for prefix, test in (
        ("exact:", lambda n, p: n == p),
        ("glob:", fnmatch.fnmatchcase),
        ("substring:", lambda n, p: p in n),
    ):
        if pattern.startswith(prefix):
            return test(name, _unquote(pattern[len(prefix):]))
    return fnmatch.fnmatchcase(name, pattern)


def _unquote(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _has_tracked_remote(repo, name) -> bool:
    """Whether a real remote tracks this bookmark. jj uses it to decide
    that a `-b` the reader typed may create a remote ref.

    The local Git-tracking remote does not count. Every exported
    bookmark has a `name@git`, so counting it would mean jj never
    created a remote bookmark from `-b`.
    """
    return any(b.name == name and b.tracked and b.remote != _GIT_REMOTE
               for b in repo.remote_bookmarks())


def _classify(name, remote, local, remote_ref, allow_new, allow_delete):
    """jj's `classify_ref_push_action`, plus the two refusals around it.

    Returns `(name, before, after)`, or `None` when the remote already
    holds what the local bookmark holds.
    """
    tracked = remote_ref is not None and remote_ref.tracked
    local_target = _target(local)
    remote_target = _target(remote_ref) if tracked else ((), ())
    if local_target == remote_target:
        return None
    if local is not None and local.has_conflict:
        raise _Refused(f"Bookmark {name} is conflicted")
    if tracked and remote_ref.has_conflict:
        raise _Refused(f"Bookmark {name}@{remote} is conflicted")
    if remote_ref is not None and not tracked:
        raise _Refused(f"Non-tracking remote bookmark {name}@{remote} exists")
    before = remote_ref.target_ids[0] if tracked else None
    after = local.target_ids[0] if local is not None else None
    if before is None and not allow_new:
        raise _Refused(f"Refusing to create new remote bookmark {name}@{remote}")
    if after is None and not allow_delete:
        raise _Refused(f"Refusing to push deleted bookmark {name}")
    return (name, before, after)


def _target(ref):
    """A ref's whole target, comparable: what it points at and, for a
    conflicted one, what it moved away from."""
    if ref is None:
        return ((), ())
    return (tuple(i.hex() for i in ref.target_ids),
            tuple(i.hex() for i in getattr(ref, "removed_ids", ())))


class _Validator:
    """jj's guard on what a push may put on the remote.

    It walks every commit an update would newly send -- everything the
    remote and the immutable set do not already reach -- and names the
    first one jj will not send. Each accepted update extends what the
    remote is known to reach, so a later update in the same push does
    not walk the same commits again.
    """

    def __init__(self, args, repo, settings, remote):
        self.repo = repo
        self.settings = settings
        self.allow_empty = getattr(args, "allow_empty", False)
        self.private = ("" if getattr(args, "allow_private", False)
                        else settings.get_string("git.private-commits") or "")
        self.known = [i.hex() for b in repo.remote_bookmarks()
                      if b.remote == remote for i in b.target_ids]

    def refusal(self, after):
        """Why this update cannot be pushed, or `None`."""
        if after is None:
            return None
        reached = " | ".join(self.known + ["immutable_heads()"])
        expression = f"({reached})..({after.hex()})"
        private_ids = set()
        if self.private and self.private != "none()":
            private_ids = {c.id.hex() for c in self.repo.revset(
                self.settings, f"({expression}) & ({self.private})")}
        for commit in self.repo.revset(self.settings, expression):
            reasons = []
            if not commit.description and not self.allow_empty:
                reasons.append("has no description")
            if (not commit.author.name or not commit.author.email
                    or not commit.committer.name
                    or not commit.committer.email):
                reasons.append("has no author and/or committer set")
            if commit.has_conflict:
                reasons.append("has conflicts")
            if commit.id.hex() in private_ids:
                reasons.append("is private")
            if reasons:
                return (f"Won't push commit {commit.id.hex()[:12]} since it "
                        + " and ".join(reasons))
        self.known.append(after.hex())
        return None
