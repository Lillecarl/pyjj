"""git subcommand: git_remote."""
import sys
from pathlib import Path

import pyjj
from ..common import (
    _start_transaction,
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
                tx = _start_transaction(repo, settings)
                remotes = tx.git_remotes()
            # jj prints the URL beside each name, and says so when the
            # fetch and push URLs differ.
            try:
                urls = {name: (fetch, push)
                        for name, fetch, push in repo.git_remote_urls()}
            except Exception:
                urls = {}
            for name in sorted(remotes):
                fetch, push = urls.get(name, ("", ""))
                if push and push != fetch:
                    print(f"{name} {fetch} (push: {push})")
                elif fetch:
                    print(f"{name} {fetch}")
                else:
                    print(name)
            return 0
        elif cmd == "add":
            tx = _start_transaction(repo, settings)
            try:
                tx.git_add_remote(args.name, args.url)
            except pyjj.JjError as e:
                print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
                return 1
            _finish(tx, f"add git remote {args.name}", settings, ws, repo)
            return 0
        elif cmd == "remove":
            tx = _start_transaction(repo, settings)
            try:
                tx.git_remove_remote(args.name)
            except pyjj.JjError as e:
                print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
                return 1
            _finish(tx, f"remove git remote {args.name}", settings, ws, repo)
            return 0
        elif cmd == "rename":
            tx = _start_transaction(repo, settings)
            try:
                tx.git_rename_remote(args.old, args.new)
            except pyjj.JjError as e:
                print(f"Error: {getattr(e, 'message', str(e))}", file=sys.stderr)
                return 1
            _finish(tx, f"rename git remote {args.old} to {args.new}", settings, ws, repo)
            return 0
        elif cmd == "set-url":
            tx = _start_transaction(repo, settings)
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
