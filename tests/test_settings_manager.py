# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the settings manager."""

from __future__ import annotations

import typing
from unittest.mock import MagicMock

from repo_management.changes import Action
from repo_management.config import Settings, SharedConfig
from repo_management.managers.settings import _SPECIAL_FIELDS, SettingsManager


def _sample_value(annotation: object) -> object:
    """A value distinct from any field's default, valid for its annotation."""
    for arg in typing.get_args(annotation):
        if typing.get_origin(arg) is typing.Literal:
            return typing.get_args(arg)[0]
    if annotation == (list[str] | None):
        return ["changed"]
    if annotation == (bool | None):
        return True
    return "changed"


def test_no_settings_is_noop(repo: MagicMock) -> None:
    """A repo config without a settings section yields no changes."""
    desired = SharedConfig()
    assert SettingsManager().plan(repo, desired) == []


def test_changed_field_produces_update(repo: MagicMock) -> None:
    """A differing scalar field yields one batched settings change calling repo.edit."""
    repo.description = "old"
    desired = SharedConfig(settings=Settings(description="new"))

    changes = SettingsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.UPDATE
    assert change.target == "settings"
    assert change.before == {"description": "old"}
    assert change.after == {"description": "new"}
    change.apply()
    repo.edit.assert_called_once_with(description="new")


def test_matching_field_is_skipped(repo: MagicMock) -> None:
    """A field already at the desired value produces no change."""
    repo.has_issues = True
    desired = SharedConfig(settings=Settings(has_issues=True))
    assert SettingsManager().plan(repo, desired) == []


def test_unset_field_is_unmanaged(repo: MagicMock) -> None:
    """Fields left None in config are ignored even if the repo differs."""
    repo.description = "anything"
    desired = SharedConfig(settings=Settings(private=True))
    repo.private = True
    assert SettingsManager().plan(repo, desired) == []


def test_topics_change(repo: MagicMock) -> None:
    """A differing topics list yields a sorted-comparison update."""
    repo.get_topics.return_value = ["b", "a"]
    desired = SharedConfig(settings=Settings(topics=["a", "b", "c"]))

    changes = SettingsManager().plan(repo, desired)

    assert len(changes) == 1
    assert changes[0].target == "topics"
    changes[0].apply()
    repo.replace_topics.assert_called_once_with(["a", "b", "c"])


def test_topics_unchanged_when_same_set(repo: MagicMock) -> None:
    """Topics differing only by order produce no change."""
    repo.get_topics.return_value = ["b", "a"]
    desired = SharedConfig(settings=Settings(topics=["a", "b"]))
    assert SettingsManager().plan(repo, desired) == []


def test_every_settings_field_produces_a_change(repo: MagicMock) -> None:
    """Guard the _SPECIAL_FIELDS seam: every Settings field must be diffed somewhere.

    A field added to _SPECIAL_FIELDS without a plan() handler would silently become
    unmanaged. Set every Settings field to a value the fake repo can't already have
    and require a change to account for each one.
    """
    values: dict[str, object] = {
        name: _sample_value(field.annotation) for name, field in Settings.model_fields.items()
    }
    repo.configure_mock(**dict.fromkeys(set(values) - _SPECIAL_FIELDS))
    repo.get_topics.return_value = []
    repo.requester.requestJsonAndCheck.return_value = ({}, {})

    changes = SettingsManager().plan(repo, SharedConfig(settings=Settings.model_validate(values)))

    managed: set[str] = set()
    for change in changes:
        if change.target == "topics":
            managed.add("topics")
        else:
            assert isinstance(change.after, dict)
            managed.update(str(key) for key in change.after)
    assert managed == set(Settings.model_fields)


def test_paired_title_backfilled_when_only_message_differs(repo: MagicMock) -> None:
    """GitHub requires *_title in the same PATCH whenever its *_message pair is present.

    If the title's desired value already matches the repo (so the plain diff would drop
    it), the PATCH must still include it whenever the paired message field is being sent.
    """
    repo.squash_merge_commit_title = "PR_TITLE"
    repo.squash_merge_commit_message = "COMMIT_MESSAGES"
    desired = SharedConfig(
        settings=Settings(squash_merge_commit_title="PR_TITLE", squash_merge_commit_message="BLANK")
    )

    changes = SettingsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    # The user-facing summary stays a minimal, honest diff -- title isn't "changing".
    assert change.after == {"squash_merge_commit_message": "BLANK"}
    change.apply()
    repo.edit.assert_called_once_with(
        squash_merge_commit_message="BLANK", squash_merge_commit_title="PR_TITLE"
    )


def test_multiple_fields(repo: MagicMock) -> None:
    """Several differing scalar fields batch into one settings change; topics is separate."""
    repo.description = "old"
    repo.has_wiki = False
    repo.get_topics.return_value = []
    desired = SharedConfig(
        settings=Settings(description="new", has_wiki=True, topics=["x"]),
    )

    changes = SettingsManager().plan(repo, desired)

    assert {c.target for c in changes} == {"settings", "topics"}
    settings_change = next(c for c in changes if c.target == "settings")
    assert settings_change.after == {"description": "new", "has_wiki": True}
    settings_change.apply()
    repo.edit.assert_called_once_with(description="new", has_wiki=True)
