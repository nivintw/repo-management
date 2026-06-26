# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the settings manager."""

from __future__ import annotations

from unittest.mock import MagicMock

from repo_management.changes import Action
from repo_management.config import RepoConfig, Settings
from repo_management.managers.settings import SettingsManager


def test_no_settings_is_noop(repo: MagicMock) -> None:
    """A repo config without a settings section yields no changes."""
    desired = RepoConfig(name="o/r")
    assert SettingsManager().plan(repo, desired) == []


def test_changed_field_produces_update(repo: MagicMock) -> None:
    """A differing scalar field yields one update change that calls repo.edit."""
    repo.description = "old"
    desired = RepoConfig(name="o/r", settings=Settings(description="new"))

    changes = SettingsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.UPDATE
    assert change.target == "description"
    assert (change.before, change.after) == ("old", "new")
    change.apply()
    repo.edit.assert_called_once_with(description="new")


def test_matching_field_is_skipped(repo: MagicMock) -> None:
    """A field already at the desired value produces no change."""
    repo.has_issues = True
    desired = RepoConfig(name="o/r", settings=Settings(has_issues=True))
    assert SettingsManager().plan(repo, desired) == []


def test_unset_field_is_unmanaged(repo: MagicMock) -> None:
    """Fields left None in config are ignored even if the repo differs."""
    repo.description = "anything"
    desired = RepoConfig(name="o/r", settings=Settings(private=True))
    repo.private = True
    assert SettingsManager().plan(repo, desired) == []


def test_topics_change(repo: MagicMock) -> None:
    """A differing topics list yields a sorted-comparison update."""
    repo.get_topics.return_value = ["b", "a"]
    desired = RepoConfig(name="o/r", settings=Settings(topics=["a", "b", "c"]))

    changes = SettingsManager().plan(repo, desired)

    assert len(changes) == 1
    assert changes[0].target == "topics"
    changes[0].apply()
    repo.replace_topics.assert_called_once_with(["a", "b", "c"])


def test_topics_unchanged_when_same_set(repo: MagicMock) -> None:
    """Topics differing only by order produce no change."""
    repo.get_topics.return_value = ["b", "a"]
    desired = RepoConfig(name="o/r", settings=Settings(topics=["a", "b"]))
    assert SettingsManager().plan(repo, desired) == []


def test_multiple_fields(repo: MagicMock) -> None:
    """Several differing fields each produce their own change."""
    repo.description = "old"
    repo.has_wiki = False
    repo.get_topics.return_value = []
    desired = RepoConfig(
        name="o/r",
        settings=Settings(description="new", has_wiki=True, topics=["x"]),
    )
    changes = SettingsManager().plan(repo, desired)
    assert {c.target for c in changes} == {"description", "has_wiki", "topics"}
