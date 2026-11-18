"""Octopus fork health check.

    pyjj python <this file> check [--octopus NAME] [--json]
    pyjj wf octopus check ...        # with this file in `pyjj.extensions`

Reads the fork and prints one line per finding, problems first, each
with the command that fixes it. Exit 1 when there is a problem, 0 when
there are only notes. Writes nothing to the operation log: the conflict
predictions rebase and merge inside a transaction that is never
committed. That transaction may leave unreferenced objects in the store,
as any trial rewrite does; `pyjj util gc` collects them.

Predictions use the trunk() the repository has now. Fetch first
(`pyjj git fetch`) to predict a sync against upstream's latest.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

import pyjj

if TYPE_CHECKING:
    from pyjj_bindings import Commit


@dataclass
class Finding:
    level: str  # "problem" | "note"
    what: str
    fix: str = ""


@dataclass
class Topic:
    tip: str
    commits: int
    stacked_on: list[str] = field(default_factory=list)
    merges: list[str] = field(default_factory=list)


@dataclass
class Report:
    trunk: str = ""
    octopus: str = ""
    topics: dict[str, Topic] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)

    def problem(self, what: str, fix: str = "") -> None:
        self.findings.append(Finding("problem", what, fix))

    def note(self, what: str, fix: str = "") -> None:
        self.findings.append(Finding("note", what, fix))

    @property
    def ok(self) -> bool:
        return not any(f.level == "problem" for f in self.findings)


# Seven-character openers of jj's conflict-marker lines, all three styles.
# Not `=======` or `-------`: Markdown underlines headings with them.
_MARKERS = {m * 7 for m in (b"<", b">", b"%", b"+", b"|", b"\\")}


def _short(c: Commit) -> str:
    return c.change_id.reverse_hex()[:8]


def _label(c: Commit) -> str:
    subject = (c.description.splitlines() or ["(no description set)"])[0]
    return f"{_short(c)} {subject}"


def check(repo: pyjj.Repo, octopus: str = "octopus") -> Report:
    report = Report()
    raw = repo._repo
    settings = repo.settings

    trunk = repo.resolve("trunk()")
    report.trunk = _label(trunk)
    try:
        octo = repo.resolve(f'bookmarks(exact:"{octopus}")')
    except pyjj.JjError:
        report.problem(
            f"no bookmark {octopus!r}",
            f"pyjj bookmark create {octopus} -r <the merge of all topic tips>",
        )
        return report
    report.octopus = _label(octo)

    names: dict[str, list[str]] = {}
    for b in raw.bookmarks():
        if b.target_ids and not b.has_conflict:
            names.setdefault(b.target_ids[0].hex(), []).append(b.name)

    if not octo.is_empty(raw):
        report.problem(
            f"the octopus {_short(octo)} holds changes of its own",
            f"move them into a topic: pyjj squash --from {octopus} --into TOPIC",
        )

    parents = [raw.get_commit(p) for p in octo.parent_ids]
    trunk_hex = trunk.id.hex()
    tips: dict[str, Commit] = {}
    for p in parents:
        own = [n for n in names.get(p.id.hex(), []) if n != octopus]
        if p.id.hex() == trunk_hex:
            report.problem(
                "trunk() itself is an octopus parent (a landed topic?)",
                f"pyjj simplify-parents -r {octopus}",
            )
            continue
        if not own:
            below = next(
                (
                    names[c.id.hex()]
                    for c in repo.revset(f"::{p.id.hex()} ~ ::trunk()")
                    if c.id.hex() in names
                ),
                None,
            )
            fix = (
                f"pyjj bookmark set {below[0]} -r {_short(p)}"
                if below
                else f"pyjj bookmark create NAME -r {_short(p)}"
            )
            report.problem(
                f"octopus parent {_label(p)} has no bookmark"
                + (f"; {below[0]} sits below it in the same lane" if below else ""),
                fix,
            )
            tips[_short(p)] = p
        else:
            for n in own:
                tips[n] = p

    behind = []
    for name, tip in tips.items():
        lane = repo.revset(f"::{tip.id.hex()} ~ ::trunk()")
        roots = repo.revset(f"roots(::{tip.id.hex()} ~ ::trunk())")
        info = Topic(tip=_label(tip), commits=len(lane))
        if len(tip.parent_ids) > 1:
            info.merges = [
                names.get(p.hex(), [raw.get_commit(p).change_id.reverse_hex()[:8]])[0]
                for p in tip.parent_ids
            ]
        for root in roots:
            if (
                any(
                    p.hex() != trunk_hex and repo.revset(f"{p.hex()} & ::trunk()")
                    for p in root.parent_ids
                )
                and name not in behind
            ):
                behind.append(name)
        # Another topic's bookmark inside this lane: stacked on it. A
        # merge tip's parents are what it integrates, not a stack.
        below = repo.revset(
            f"(::{tip.id.hex()} ~ ::trunk()) ~ {tip.id.hex()}"
            + "".join(
                f" ~ {p.hex()}" for p in tip.parent_ids if len(tip.parent_ids) > 1
            )
        )
        stacked_on = [
            n for c in below for n in names.get(c.id.hex(), []) if n != octopus
        ]
        if stacked_on:
            info.stacked_on = stacked_on
            own = repo.revset(
                f"(::{tip.id.hex()} ~ ::trunk())"
                + "".join(f" ~ ::{c.id.hex()}" for c in below if names.get(c.id.hex()))
            )
            info.commits = len(own)
        if not lane:
            report.problem(
                f"topic {name} has no commits above trunk (landed?)",
                f"pyjj simplify-parents -r {octopus}; pyjj bookmark delete {name}",
            )
        report.topics[name] = info
    if behind:
        report.note(
            f"behind trunk(): {', '.join(behind)}",
            f"sync: pyjj rebase -b {octopus} -d 'trunk()' --skip-emptied",
        )

    # Maybe a topic made but never merged, maybe an archive or WIP
    # bookmark: only the user knows, so a note.
    outside = repo.revset(f"bookmarks() & mutable() ~ ::{octopus} ~ {octopus}::")
    for c in outside:
        for n in names.get(c.id.hex(), []):
            report.note(
                f"bookmark {n} is not in the octopus",
                f"if {n} is a topic: pyjj rebase -r {octopus} -d '{octopus}-' -d {n}",
            )

    conflicted = repo.revset(f"conflicts() & ::{octopus}+")
    if conflicted:
        roots = repo.revset(f"roots(conflicts() & ::{octopus}+)")
        for r in roots:
            if r.id.hex() == octo.id.hex():
                report.problem(
                    "the octopus is conflicted, its topics are not: two topics "
                    "touch the same lines (see the pairs below)",
                    "stack the dependent topic on the other, or add an "
                    "integration merge (skill section H)",
                )
            else:
                report.problem(
                    f"conflict starts at {_label(r)}",
                    f"pyjj new {_short(r)}; edit the files; pyjj squash; "
                    f"pyjj new {octopus}",
                )

    # A hand resolution that kept part of a marker block: jj no longer
    # parses it as a conflict, so conflicts() is empty and only the text
    # shows it.
    for c in repo.revset(f"::{octopus}+ ~ ::trunk()"):
        entries = [e.path for e in c.diff_from_parents(raw)]
        if not entries:
            continue
        before = c.parent_contents(raw, entries)
        for path in entries:
            if c.file_kind(path) != "file":
                continue
            old = {
                line
                for line in (before.get(path) or b"").splitlines()
                if line[:7] in _MARKERS
            }
            stray = [
                line
                for line in c.read_file(path).splitlines()
                if line[:7] in _MARKERS and line not in old
            ]
            if stray:
                report.problem(
                    f"{_label(c)} leaves conflict-marker lines in {path}: "
                    f"{stray[0].decode(errors='replace')!r}",
                    f"pyjj new {_short(c)}; delete them; pyjj squash; pyjj new {octopus}",
                )

    # Trial merges and a trial sync, each in a transaction that is
    # dropped uncommitted.
    pairs = raw.start_transaction(settings)
    for (a, ca), (b, cb) in itertools.combinations(tips.items(), 2):
        if ca.has_conflict or cb.has_conflict:
            continue  # inherited, not a collision between the two
        if repo.revset(
            f"({ca.id.hex()} & ::{cb.id.hex()}) | ({cb.id.hex()} & ::{ca.id.hex()})"
        ):
            continue
        merged = pairs.new_commit(settings, [ca.id, cb.id]).write(raw)
        if merged.has_conflict:
            files = [
                f
                for f in merged.list_files()
                if merged.file_kind(f).endswith("conflict")
            ]
            report.note(
                f"topics {a} and {b} conflict with each other in {', '.join(files)}",
                "stack one on the other, or merge them in an integration commit (skill H)",
            )
    del pairs

    roots = repo.revset(f"roots(::{octopus} ~ ::trunk())")
    movable = [r.id for r in roots if [p.hex() for p in r.parent_ids] != [trunk_hex]]
    if movable:
        sync = raw.start_transaction(settings)
        before = {c.hex() for c in sync.revset(settings, "conflicts()")}
        sync.move_commits(
            target_commit_ids=[],
            target_root_ids=movable,
            new_parent_ids=[trunk.id],
            new_child_ids=[],
            skip_emptied=True,
        )
        sync.rebase_descendants()
        new = {
            c.hex() for c in sync.revset(settings, f"roots(conflicts()) & ::{octopus}")
        } - before
        hit = sorted(_label(raw.get_commit(pyjj.CommitId(h))) for h in new)
        if hit:
            report.note(
                "a sync would start conflicts at: " + "; ".join(hit),
                "sync anyway, then resolve each (skill F)",
            )
        landed = [
            name
            for name in tips
            if sync.revset(settings, f'bookmarks(exact:"{name}") & ::trunk()')
        ]
        if landed:
            report.note(
                f"upstream already has {', '.join(landed)}: a sync empties "
                "and drops those lanes",
                "after the sync: skill G",
            )
        del sync

    # Work left on the octopus by no workspace: a recipe that ended with
    # `pyjj new octopus` while @ still held unfinished work.
    stranded = repo.revset(f"{octopus}+ ~ working_copies() ~ empty()")
    wc = repo.resolve("@")
    if [p.hex() for p in wc.parent_ids] != [octo.id.hex()]:
        fix = (
            f"pyjj edit {_short(stranded[0])}"
            if len(stranded) == 1
            else f"pyjj new {octopus}"
        )
        report.problem("@ is not a child of the octopus", fix)
    else:
        if not wc.is_empty(raw):
            files = [e.path for e in wc.diff_from_parents(raw)]
            report.note(f"@ holds unfinished work: {', '.join(files)}")
        for c in stranded:
            # A stale workspace's unsaved edits land in a divergent
            # sibling, whose change id no longer names one commit.
            ref = c.id.hex()[:12] if c.is_divergent(raw) else _short(c)
            report.problem(
                f"unfinished work left on the octopus, outside @: {_label(c)}",
                f"pyjj squash --from {ref} --into @",
            )
    for c in repo.revset(f"{octopus}+ & working_copies() ~ @"):
        report.note(f"another workspace works on the octopus: {_label(c)}")

    # A fork's own remote often has a stale main too; trunk() must be
    # the project's, not the fork's.
    if repo.revset('remote_bookmarks(remote=exact:"upstream")') and not repo.revset(
        'trunk() & remote_bookmarks(remote=exact:"upstream")'
    ):
        report.problem(
            "trunk() is not on the upstream remote",
            "pyjj config set --repo 'revset-aliases.\"trunk()\"' 'main@upstream'",
        )
    return report


def render(report: Report) -> str:
    lines = [f"trunk    {report.trunk}", f"octopus  {report.octopus}"]
    for name, info in report.topics.items():
        extra = ""
        if info.stacked_on:
            extra += f"  stacked on {', '.join(info.stacked_on)}"
        if info.merges:
            extra += f"  merges {', '.join(info.merges)}"
        lines.append(
            f"topic    {name}: {info.commits} commit(s), tip {info.tip}{extra}"
        )
    for f in sorted(report.findings, key=lambda f: f.level != "problem"):
        lines.append(f"{f.level.upper():8} {f.what}")
        if f.fix:
            lines.append(f"         fix: {f.fix}")
    lines.append("OK" if report.ok else "NOT OK")
    return "\n".join(lines)


def run(repo: pyjj.Repo, args: argparse.Namespace) -> int:
    report = check(repo.snapshot(), args.octopus)
    if args.json:
        print(json.dumps({**asdict(report), "ok": report.ok}, indent=2))
    else:
        print(render(report))
    return 0 if report.ok else 1


def add_arguments(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="verb", required=True)
    c = sub.add_parser("check", help="Verify the fork and predict conflicts")
    c.add_argument("--octopus", default="octopus", metavar="BOOKMARK")
    c.add_argument("--json", action="store_true")


class Octopus(pyjj.Workflow):
    name = "octopus"
    help = "Check an octopus fork: topics, conflicts, sync preview"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        add_arguments(parser)

    def run(self, repo: pyjj.Repo, args: argparse.Namespace) -> int:
        return run(repo, args)


if __name__ == "__main__":
    _parser = argparse.ArgumentParser(prog="octopus.py")
    add_arguments(_parser)
    _args = _parser.parse_args()
    _repo = globals().get("repo")  # bound by `pyjj python`
    if not isinstance(_repo, pyjj.Repo):
        print("Error: run inside a repository, via `pyjj python`", file=sys.stderr)
        sys.exit(2)
    sys.exit(run(_repo, _args))
