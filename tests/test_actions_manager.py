# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the Actions permissions manager."""

from __future__ import annotations

from unittest.mock import MagicMock

from repo_management.changes import Action
from repo_management.config import (
    ActionsConfig,
    ForkPrWorkflowsPrivateRepos,
    SelectedActions,
    SharedConfig,
)
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


def test_sha_pinning_required_change(repo: MagicMock) -> None:
    """sha_pinning_required is diffed on the shared permissions endpoint, preserving the pair."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = (
        {},
        {"enabled": True, "allowed_actions": "all", "sha_pinning_required": False},
    )
    desired = SharedConfig(actions=ActionsConfig(sha_pinning_required=True))

    changes = ActionsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.target == "permissions"
    assert change.after == {"sha_pinning_required": True}
    change.apply()
    repo.requester.requestJsonAndCheck.assert_called_with(
        "PUT",
        f"{URL}/actions/permissions",
        input={"enabled": True, "allowed_actions": "all", "sha_pinning_required": True},
    )


def test_access_level_change(repo: MagicMock) -> None:
    """access_level drives the /access endpoint."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = ({}, {"access_level": "none"})
    desired = SharedConfig(actions=ActionsConfig(access_level="organization"))

    changes = ActionsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.target == "external access"
    assert change.before == {"access_level": "none"}
    assert change.after == {"access_level": "organization"}
    change.apply()
    repo.requester.requestJsonAndCheck.assert_called_with(
        "PUT",
        f"{URL}/actions/permissions/access",
        input={"access_level": "organization"},
    )


def test_access_level_in_sync(repo: MagicMock) -> None:
    """A matching access_level produces no change."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = ({}, {"access_level": "organization"})
    desired = SharedConfig(actions=ActionsConfig(access_level="organization"))
    assert ActionsManager().plan(repo, desired) == []


def test_access_level_unset_is_unmanaged(repo: MagicMock) -> None:
    """Leaving access_level unset never touches its endpoint."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = ({}, {})
    desired = SharedConfig(actions=ActionsConfig(enabled=True))

    ActionsManager().plan(repo, desired)

    calls = [call.args[1] for call in repo.requester.requestJsonAndCheck.call_args_list]
    assert f"{URL}/actions/permissions/access" not in calls


def test_retention_days_change(repo: MagicMock) -> None:
    """artifact_and_log_retention_days maps to the endpoint's `days` field."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = ({}, {"days": 90})
    desired = SharedConfig(actions=ActionsConfig(artifact_and_log_retention_days=30))

    changes = ActionsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.target == "artifact and log retention"
    assert change.after == {"days": 30}
    change.apply()
    repo.requester.requestJsonAndCheck.assert_called_with(
        "PUT",
        f"{URL}/actions/permissions/artifact-and-log-retention",
        input={"days": 30},
    )


def test_retention_days_in_sync(repo: MagicMock) -> None:
    """A matching retention period produces no change."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = ({}, {"days": 30})
    desired = SharedConfig(actions=ActionsConfig(artifact_and_log_retention_days=30))
    assert ActionsManager().plan(repo, desired) == []


def test_retention_days_unset_is_unmanaged(repo: MagicMock) -> None:
    """Leaving artifact_and_log_retention_days unset never touches its endpoint."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = ({}, {})
    desired = SharedConfig(actions=ActionsConfig(enabled=True))

    ActionsManager().plan(repo, desired)

    calls = [call.args[1] for call in repo.requester.requestJsonAndCheck.call_args_list]
    assert f"{URL}/actions/permissions/artifact-and-log-retention" not in calls


def test_fork_pr_contributor_approval_change(repo: MagicMock) -> None:
    """fork_pr_contributor_approval maps to the endpoint's approval_policy field."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = (
        {},
        {"approval_policy": "first_time_contributors"},
    )
    desired = SharedConfig(
        actions=ActionsConfig(fork_pr_contributor_approval="all_external_contributors"),
    )

    changes = ActionsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.target == "fork PR contributor approval"
    assert change.after == {"approval_policy": "all_external_contributors"}
    change.apply()
    repo.requester.requestJsonAndCheck.assert_called_with(
        "PUT",
        f"{URL}/actions/permissions/fork-pr-contributor-approval",
        input={"approval_policy": "all_external_contributors"},
    )


def test_fork_pr_contributor_approval_in_sync(repo: MagicMock) -> None:
    """A matching contributor-approval policy produces no change."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = (
        {},
        {"approval_policy": "all_external_contributors"},
    )
    desired = SharedConfig(
        actions=ActionsConfig(fork_pr_contributor_approval="all_external_contributors"),
    )
    assert ActionsManager().plan(repo, desired) == []


def test_fork_pr_contributor_approval_unset_is_unmanaged(repo: MagicMock) -> None:
    """Leaving fork_pr_contributor_approval unset never touches its endpoint."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = ({}, {})
    desired = SharedConfig(actions=ActionsConfig(enabled=True))

    ActionsManager().plan(repo, desired)

    calls = [call.args[1] for call in repo.requester.requestJsonAndCheck.call_args_list]
    assert f"{URL}/actions/permissions/fork-pr-contributor-approval" not in calls


def test_fork_pr_private_repos_writes_back_unmanaged_fields(repo: MagicMock) -> None:
    """Declaring one fork-PR field writes the others back with their live values.

    In particular the API-required run_workflows_from_fork_pull_requests, left unmanaged, is
    preserved from the GET rather than dropped — so the PUT never omits it.
    """
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = (
        {},
        {
            "run_workflows_from_fork_pull_requests": True,
            "send_write_tokens_to_workflows": False,
            "send_secrets_and_variables": False,
            "require_approval_for_fork_pr_workflows": False,
        },
    )
    desired = SharedConfig(
        actions=ActionsConfig(
            fork_pr_workflows_private_repos=ForkPrWorkflowsPrivateRepos(
                require_approval_for_fork_pr_workflows=True,
            ),
        ),
    )

    changes = ActionsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.target == "fork PR workflows (private repos)"
    assert change.before == {"require_approval_for_fork_pr_workflows": False}
    assert change.after == {"require_approval_for_fork_pr_workflows": True}
    change.apply()
    repo.requester.requestJsonAndCheck.assert_called_with(
        "PUT",
        f"{URL}/actions/permissions/fork-pr-workflows-private-repos",
        input={
            "run_workflows_from_fork_pull_requests": True,
            "send_write_tokens_to_workflows": False,
            "send_secrets_and_variables": False,
            "require_approval_for_fork_pr_workflows": True,
        },
    )


def test_fork_pr_private_repos_in_sync(repo: MagicMock) -> None:
    """A matching fork-PR private-repos config produces no change."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = (
        {},
        {
            "run_workflows_from_fork_pull_requests": True,
            "send_write_tokens_to_workflows": False,
            "send_secrets_and_variables": False,
            "require_approval_for_fork_pr_workflows": True,
        },
    )
    desired = SharedConfig(
        actions=ActionsConfig(
            fork_pr_workflows_private_repos=ForkPrWorkflowsPrivateRepos(
                require_approval_for_fork_pr_workflows=True,
            ),
        ),
    )
    assert ActionsManager().plan(repo, desired) == []


def test_fork_pr_private_repos_unset_is_unmanaged(repo: MagicMock) -> None:
    """Leaving fork_pr_workflows_private_repos unset never touches its endpoint."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = ({}, {})
    desired = SharedConfig(actions=ActionsConfig(enabled=True))

    ActionsManager().plan(repo, desired)

    calls = [call.args[1] for call in repo.requester.requestJsonAndCheck.call_args_list]
    assert f"{URL}/actions/permissions/fork-pr-workflows-private-repos" not in calls


def test_every_actions_field_produces_a_change(repo: MagicMock) -> None:
    """Guard: every ActionsConfig field must be diffed by one of the sub-changes.

    A field added to ActionsConfig without a plan() handler would silently become
    unmanaged. Config field names diverge from the API payload keys for a few endpoints,
    so map each such change back to the field it manages by its change target.
    """
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = ({}, {})
    desired = ActionsConfig(
        enabled=True,
        allowed_actions="selected",
        sha_pinning_required=True,
        selected_actions=SelectedActions(verified_allowed=True, patterns_allowed=["a/b@*"]),
        default_workflow_permissions="write",
        can_approve_pull_request_reviews=True,
        access_level="organization",
        artifact_and_log_retention_days=30,
        fork_pr_contributor_approval="all_external_contributors",
        fork_pr_workflows_private_repos=ForkPrWorkflowsPrivateRepos(
            run_workflows_from_fork_pull_requests=True,
        ),
    )

    changes = ActionsManager().plan(repo, SharedConfig(actions=desired))

    # Targets whose payload keys don't match the config field name they manage. Endpoints
    # whose payload key equals the field name (e.g. access_level) are recorded by the else
    # branch below and need no entry here.
    target_field = {
        "selected actions": "selected_actions",
        "artifact and log retention": "artifact_and_log_retention_days",
        "fork PR contributor approval": "fork_pr_contributor_approval",
        "fork PR workflows (private repos)": "fork_pr_workflows_private_repos",
    }
    managed: set[str] = set()
    for change in changes:
        if change.target in target_field:
            managed.add(target_field[change.target])
        else:
            assert isinstance(change.after, dict)
            managed.update(str(key) for key in change.after)
    assert managed == set(ActionsConfig.model_fields)
