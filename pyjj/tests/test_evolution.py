"""Tests for ReadonlyRepo.evolution_log() -- `jj evolog`'s history.

Evolution is found by walking the *operation* log, not the commit graph,
so it surfaces versions of a change that no longer exist as visible
commits.
"""

import pytest

import pyjj


@pytest.fixture
def rewritten(repo, settings, wc_commit):
    """One change described three times, so it has three versions."""
    tx = repo.start_transaction(settings)
    b = tx.new_commit(settings, [wc_commit.id])
    b.set_description("first")
    original = b.write(repo)
    tx.set_wc_commit("default", original.id)
    tx.rebase_descendants()
    repo = tx.commit("create")

    versions = [original.id]
    for message in ("second", "third"):
        tx = repo.start_transaction(settings)
        current = repo.get_commit(versions[-1])
        builder = tx.rewrite_commit(settings, current)
        builder.set_description(message)
        rewritten = builder.write(repo)
        tx.rebase_descendants()
        repo = tx.commit(f"describe {message}")
        versions.append(rewritten.id)

    return repo, versions


def test_evolution_log_lists_every_version(rewritten):
    repo, versions = rewritten
    entries = repo.evolution_log([versions[-1]])

    # Newest first, and every version of the change appears.
    hexes = [e.commit.id.hex() for e in entries]
    assert hexes[0] == versions[-1].hex()
    for version in versions:
        assert version.hex() in hexes, hexes

    descriptions = [
        e.commit.description.strip() for e in entries if e.commit.description
    ]
    assert descriptions[:3] == ["third", "second", "first"]


def test_evolution_entries_link_to_predecessors(rewritten):
    repo, versions = rewritten
    entries = repo.evolution_log([versions[-1]])
    by_hex = {e.commit.id.hex(): e for e in entries}

    newest = by_hex[versions[-1].hex()]
    assert [i.hex() for i in newest.predecessor_ids] == [versions[-2].hex()]

    # The first version was created, not rewritten from anything.
    oldest = by_hex[versions[0].hex()]
    assert oldest.predecessor_ids == []


def test_evolution_entries_carry_their_operation(rewritten):
    repo, versions = rewritten
    entries = repo.evolution_log([versions[-1]])
    ops = [e.operation for e in entries if e.operation is not None]
    assert ops, "no entry recorded its operation"
    for op in ops:
        assert op.id
        assert all(c in "0123456789abcdef" for c in op.id), op.id
    # Each rewrite happened in its own operation.
    assert len({op.id for op in ops}) == len(ops)


def test_evolution_log_limit(rewritten):
    repo, versions = rewritten
    assert len(repo.evolution_log([versions[-1]], limit=2)) == 2
    assert len(repo.evolution_log([versions[-1]], limit=1)) == 1


def test_evolution_log_of_a_fresh_commit_is_itself(repo, settings, wc_commit):
    entries = repo.evolution_log([wc_commit.id])
    assert [e.commit.id.hex() for e in entries] == [wc_commit.id.hex()]
    assert entries[0].predecessor_ids == []


def test_evolution_log_empty_start(repo):
    assert repo.evolution_log([]) == []
