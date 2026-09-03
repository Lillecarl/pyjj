"""command: metaedit — change a revision's metadata, not its content."""
import sys

import pyjj

from ..common import (
    CommandError,
    _finish,
    _load,
    _resolve_all,
    complete_newline,
)


def metaedit(args) -> int:
    """`jj metaedit`: rewrite metadata, leaving every tree untouched.

    Author name and email move together, and separately from the author
    timestamp: `--author` and `--update-author` keep the existing date,
    `--update-author-timestamp` keeps the existing name.
    """
    edits = _requested_edits(args)
    if not edits:
        print("Error: No changes requested", file=sys.stderr)
        return 2

    try:
        settings, ws, repo = _load(args)
        revisions = (list(getattr(args, "revisions", None) or [])
                     + list(getattr(args, "revisions_pos", None) or []))
        targets = _resolve_all(repo, settings, revisions or ["@"])
        if not targets:
            print("Nothing changed.")
            return 0

        tx = repo.start_transaction(settings)
        modified = 0
        for commit in targets:
            description = None
            if args.message is not None:
                candidate = complete_newline(args.message)
                if candidate != commit.description:
                    description = candidate
            author = _new_author(settings, commit, args)
            new_change_id = getattr(args, "update_change_id", False)
            if description is None and author is None and not new_change_id:
                # Asking for metadata a commit already has changes
                # nothing, and rewriting it anyway would move its commit
                # id for no reason.
                continue

            builder = tx.rewrite_commit(settings, commit)
            if description is not None:
                builder.set_description(description)
            if author is not None:
                builder.set_author(author)
            if new_change_id:
                builder.generate_new_change_id()
            builder.write(repo)
            modified += 1

        if not modified:
            print("Nothing changed.")
            return 0
        _finish(tx, f"metaedit {modified} commits", settings, ws, repo)
        print(f"Modified {modified} commits")
        return 0
    except (pyjj.JjError, CommandError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1


def _requested_edits(args) -> bool:
    return any((
        args.message is not None,
        args.author is not None,
        getattr(args, "update_author", False),
        getattr(args, "update_author_timestamp", False),
        getattr(args, "update_change_id", False),
    ))


def _new_author(settings, commit, args):
    """The commit's new author signature, or `None` to leave it alone."""
    old = commit.author
    name, email, timestamp = old.name, old.email, old.timestamp
    changed = False
    if args.author is not None:
        name, email = _parse_author(args.author)
        changed = True
    elif getattr(args, "update_author", False):
        name, email = settings.user_name, settings.user_email
        changed = True
    if getattr(args, "update_author_timestamp", False):
        # `settings.signature()` carries the same "now" jj would stamp,
        # including the pinned value when `JJ_TIMESTAMP` is set.
        timestamp = settings.signature().timestamp
        changed = True
    if not changed:
        return None
    author = pyjj.Signature(name, email, timestamp)
    return author if author != old else None


def _parse_author(text: str):
    """`"Name <email>"` -> `("Name", "email")`."""
    name, sep, rest = text.partition("<")
    if not sep or not rest.endswith(">"):
        raise CommandError(f'Invalid author "{text}"; expected "Name <email>"')
    return name.strip(), rest[:-1].strip()
