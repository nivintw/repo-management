# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the Actions permissions manager."""

from __future__ import annotations

from unittest.mock import MagicMock

from repo_management.changes import Action
from repo_management.config import ActionsConfig, SelectedActions, SharedConfig
from repo_management.managers.actions import ActionsManager

URL = "https://api.github.com/repos/o/r"


def _responses(by_url: dict[str, dict]) -> object:
    """A requestJsonAndCheck side_effect returning a per-endpoint response by URL."""

    def side_effect(_verb: str, url: str, **_kwargs: object) -> tuple[dict, dict]:
        return ({}, by_url[url])

    return side_effect


def test_no_actions_is_noop(repo: MagicMock) -> None:
    """A repo config without an actions section yields no changes."""
    assert ActionsManager().plan(repo, SharedConfig()) == []
    repo.requester.requestJsonAndCheck.assert_not_called()


def test_permissions_unset_is_unmanaged(repo: MagicMock) -> None:
    """Leaving enabled/allowed_actions unset never touches the permissions endpoint."""
    repo.url = URL
    desired = SharedConfig(actions=ActionsConfig(can_approve_pull_request_reviews=True))
    repo.requester.requestJsonAndCheck.return_value = ({}, {})

    ActionsManager().plan(repo, desired)

    calls = [call.args[1] for call in repo.requester.requestJsonAndCheck.call_args_list]
    assert f"{URL}/actions/permissions" not in calls


def test_permissions_change(repo: MagicMock) -> None:
    """A differing enabled/allowed_actions field yields a change that PUTs both, preserved."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = (
        {},
        {"enabled": True, "allowed_actions": "all"},
    )
    desired = SharedConfig(actions=ActionsConfig(allowed_actions="selected"))

    changes = ActionsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.UPDATE
    assert change.target == "permissions"
    assert change.before == {"allowed_actions": "all"}
    assert change.after == {"allowed_actions": "selected"}
    change.apply()
    repo.requester.requestJsonAndCheck.assert_called_with(
        "PUT",
        f"{URL}/actions/permissions",
        input={"enabled": True, "allowed_actions": "selected"},
    )


def test_permissions_in_sync(repo: MagicMock) -> None:
    """A matching enabled/allowed_actions produces no change."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = (
        {},
        {"enabled": True, "allowed_actions": "all"},
    )
    desired = SharedConfig(actions=ActionsConfig(enabled=True, allowed_actions="all"))
    assert ActionsManager().plan(repo, desired) == []


def test_selected_actions_unset_is_unmanaged(repo: MagicMock) -> None:
    """Leaving selected_actions unset never touches its endpoint."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = ({}, {})
    desired = SharedConfig(actions=ActionsConfig(allowed_actions="selected"))

    ActionsManager().plan(repo, desired)

    calls = [call.args[1] for call in repo.requester.requestJsonAndCheck.call_args_list]
    assert f"{URL}/actions/permissions/selected-actions" not in calls


def test_selected_actions_change(repo: MagicMock) -> None:
    """A differing selected-actions config yields a change that PUTs the full body."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.side_effect = _responses(
        {
            f"{URL}/actions/permissions": {"enabled": True, "allowed_actions": "selected"},
            f"{URL}/actions/permissions/selected-actions": {
                "github_owned_allowed": True,
                "verified_allowed": False,
                "patterns_allowed": [],
            },
        },
    )
    desired = SharedConfig(
        actions=ActionsConfig(
            allowed_actions="selected",
            selected_actions=SelectedActions(verified_allowed=True, patterns_allowed=["a/b@*"]),
        ),
    )

    changes = ActionsManager().plan(repo, desired)

    assert len(changes) == 1
    selected = changes[0]
    assert selected.target == "selected actions"
    assert selected.action is Action.UPDATE
    selected.apply()
    repo.requester.requestJsonAndCheck.assert_called_with(
        "PUT",
        f"{URL}/actions/permissions/selected-actions",
        input={
            "github_owned_allowed": True,
            "verified_allowed": True,
            "patterns_allowed": ["a/b@*"],
        },
    )


def test_selected_actions_in_sync(repo: MagicMock) -> None:
    """A matching selected-actions config produces no selected-actions change."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.side_effect = _responses(
        {
            f"{URL}/actions/permissions": {"enabled": True, "allowed_actions": "selected"},
            f"{URL}/actions/permissions/selected-actions": {
                "github_owned_allowed": True,
                "verified_allowed": False,
                "patterns_allowed": [],
            },
        },
    )
    desired = SharedConfig(
        actions=ActionsConfig(
            allowed_actions="selected",
            selected_actions=SelectedActions(),
        ),
    )

    assert ActionsManager().plan(repo, desired) == []


def test_workflow_permissions_unset_is_unmanaged(repo: MagicMock) -> None:
    """Leaving both workflow-permission fields unset never touches that endpoint."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = ({}, {})
    desired = SharedConfig(actions=ActionsConfig(enabled=True))

    ActionsManager().plan(repo, desired)

    calls = [call.args[1] for call in repo.requester.requestJsonAndCheck.call_args_list]
    assert f"{URL}/actions/permissions/workflow" not in calls


def test_workflow_permissions_change(repo: MagicMock) -> None:
    """A differing workflow-permissions toggle yields a change that PUTs both, preserved."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = (
        {},
        {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False},
    )
    desired = SharedConfig(actions=ActionsConfig(can_approve_pull_request_reviews=True))

    changes = ActionsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.UPDATE
    assert change.target == "workflow permissions"
    assert change.before == {"can_approve_pull_request_reviews": False}
    assert change.after == {"can_approve_pull_request_reviews": True}
    change.apply()
    repo.requester.requestJsonAndCheck.assert_called_with(
        "PUT",
        f"{URL}/actions/permissions/workflow",
        input={
            "default_workflow_permissions": "read",
            "can_approve_pull_request_reviews": True,
        },
    )


def test_workflow_permissions_write_back_omits_missing_key(repo: MagicMock) -> None:
    """An unmanaged field the GET omits is dropped from the PUT, not sent as null."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = (
        {},
        {"can_approve_pull_request_reviews": False},
    )
    desired = SharedConfig(actions=ActionsConfig(can_approve_pull_request_reviews=True))

    changes = ActionsManager().plan(repo, desired)

    assert len(changes) == 1
    changes[0].apply()
    repo.requester.requestJsonAndCheck.assert_called_with(
        "PUT",
        f"{URL}/actions/permissions/workflow",
        input={"can_approve_pull_request_reviews": True},
    )


def test_workflow_permissions_in_sync(repo: MagicMock) -> None:
    """A matching workflow-permissions toggle produces no change."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = (
        {},
        {"can_approve_pull_request_reviews": True},
    )
    desired = SharedConfig(actions=ActionsConfig(can_approve_pull_request_reviews=True))
    assert ActionsManager().plan(repo, desired) == []


def test_every_actions_field_produces_a_change(repo: MagicMock) -> None:
    """Guard: every ActionsConfig field must be diffed by one of the three sub-changes.

    A field added to ActionsConfig without a plan() handler would silently become
    unmanaged.
    """
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = ({}, {})
    desired = ActionsConfig(
        enabled=True,
        allowed_actions="selected",
        selected_actions=SelectedActions(verified_allowed=True, patterns_allowed=["a/b@*"]),
        default_workflow_permissions="write",
        can_approve_pull_request_reviews=True,
    )

    changes = ActionsManager().plan(repo, SharedConfig(actions=desired))

    managed: set[str] = set()
    for change in changes:
        if change.target == "selected actions":
            managed.add("selected_actions")
        else:
            assert isinstance(change.after, dict)
            managed.update(str(key) for key in change.after)
    assert managed == set(ActionsConfig.model_fields)
