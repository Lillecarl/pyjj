"""git subcommand: git_remote."""
import sys
from pathlib import Path

import pyjj
from ..common import (
    CommandError,
    _finish,
    _load,
    _resolve_all,
    _resolve_one,
)

def git_remote(args) -> int:
    """`jj git remote` — manage Git remotes."""
    try:
        settings, ws, repo = _load(args)
        cmd = getattr(args, "remote_command", None)
        if cmd == "list":
            try:
                remotes = repo.git_remotes()  # type: ignore
            except Exception:
                tx = repo.start_transaction(settings)
                remotes = tx.git_remotes()
            for name in sorted(remotes):
                print(name)
            return 0
        elif cmd == "add":
            tx = repo.start_transaction(settings)
            try:
                tx.git_add_remote(args.name, args.url)
            except pyjj.JjError as e:
                print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
                return 1
            _finish(tx, f"add git remote {args.name}", settings, ws, repo)
            return 0
        elif cmd == "remove":
            tx = repo.start_transaction(settings)
            try:
                tx.git_remove_remote(args.name)
            except pyjj.JjError as e:
                print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
                return 1
            _finish(tx, f"remove git remote {args.name}", settings, ws, repo)
            return 0
        elif cmd == "rename":
            tx = repo.start_transaction(settings)
            try:
                tx.git_rename_remote(args.old, args.new)
            except pyjj.JjError as e:
                print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
                return 1
            _finish(tx, f"rename git remote {args.old} to {args.new}", settings, ws, repo)
            return 0
        elif cmd == "set-url":
            tx = repo.start_transaction(settings)
            url = getattr(args, "url", None)
            push_url = getattr(args, "push_url", None)
            if url is None and push_url is None:
                print("Error: --url or --push-url is required", file=sys.stderr)
                return 2
            try:
                tx.git_set_remote_urls(args.name, url=url, push_url=push_url)
            except pyjj.JjError as e:
                print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
                return 1
            _finish(tx, f"set git remote {args.name} URL", settings, ws, repo)
            return 0
        else:
            print("usage: pyjj git remote {add,list,remove,rename,set-url}", file=sys.stderr)
            return 2
    except (pyjj.WorkspaceLoadError, pyjj.RepoLoadError) as e:
        print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
        return 1
