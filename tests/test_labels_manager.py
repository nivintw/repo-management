# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the LabelsManager."""

from __future__ import annotations

from unittest.mock import MagicMock

from conftest import make_label
from github import GithubObject

from repo_management.changes import Action
from repo_management.config import Label, Labels, RepoConfig
from repo_management.managers.labels import LabelsManager


def test_no_labels_is_noop(repo: MagicMock) -> None:
    """A repo config without a labels section yields no changes."""
    desired = RepoConfig(name="o/r")
    assert LabelsManager().plan(repo, desired) == []


def test_new_label_creates_change(repo: MagicMock) -> None:
    """A label in config not present on repo yields one CREATE change."""
    desired = RepoConfig(
        name="o/r",
        labels=Labels(items=[Label(name="bug", color="d73a49", description="Something is broken")]),
    )
    repo.get_labels.return_value = []

    changes = LabelsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.CREATE
    assert change.target == "label:bug"
    assert change.before is None
    assert change.after == {"color": "d73a49", "description": "Something is broken"}
    change.apply()
    repo.create_label.assert_called_once_with("bug", "d73a49", description="Something is broken")


def test_new_label_without_description(repo: MagicMock) -> None:
    """Create with description None passes NotSet so the field is left unset."""
    desired = RepoConfig(name="o/r", labels=Labels(items=[Label(name="bug", color="d73a49")]))
    repo.get_labels.return_value = []

    changes = LabelsManager().plan(repo, desired)

    changes[0].apply()
    repo.create_label.assert_called_once_with("bug", "d73a49", description=GithubObject.NotSet)


def test_existing_label_updates_change(repo: MagicMock) -> None:
    """An existing label whose color or description differs yields one UPDATE change."""
    existing = make_label(name="bug", color="ffffff", description="old")
    desired = RepoConfig(
        name="o/r",
        labels=Labels(items=[Label(name="bug", color="d73a49", description="new")]),
    )
    repo.get_labels.return_value = [existing]

    changes = LabelsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.UPDATE
    assert change.before == {"color": "ffffff", "description": "old"}
    assert change.after == {"color": "d73a49", "description": "new"}
    change.apply()
    existing.edit.assert_called_once_with("bug", "d73a49", description="new")


def test_existing_label_matches_exactly(repo: MagicMock) -> None:
    """An existing label that matches exactly yields no change."""
    existing = make_label(name="bug", color="d73a49", description="same")
    desired = RepoConfig(
        name="o/r",
        labels=Labels(items=[Label(name="bug", color="d73a49", description="same")]),
    )
    repo.get_labels.return_value = [existing]

    assert LabelsManager().plan(repo, desired) == []


def test_prune_deletes_extra_label(repo: MagicMock) -> None:
    """Prune=True deletes an existing label absent from desired items."""
    existing = make_label(name="stale", color="d73a49", description=None)
    desired = RepoConfig(name="o/r", labels=Labels(prune=True, items=[]))
    repo.get_labels.return_value = [existing]

    changes = LabelsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.DELETE
    assert change.target == "label:stale"
    assert change.after is None
    change.apply()
    existing.delete.assert_called_once_with()


def test_no_prune_keeps_extra_labels(repo: MagicMock) -> None:
    """Prune=False leaves extra existing labels untouched."""
    existing = make_label(name="stale", color="d73a49", description=None)
    desired = RepoConfig(name="o/r", labels=Labels(prune=False, items=[]))
    repo.get_labels.return_value = [existing]

    assert LabelsManager().plan(repo, desired) == []
