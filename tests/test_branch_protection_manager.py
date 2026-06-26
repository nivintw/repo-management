# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the branch protection manager."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from github import GithubException

from repo_management.changes import Action
from repo_management.config import BranchProtection, RepoConfig
from repo_management.managers.branch_protection import BranchProtectionManager


def make_protection(
    *,
    enforce_admins: bool = False,
    required_linear_history: bool = False,
    allow_force_pushes: bool = False,
    allow_deletions: bool = False,
    required_conversation_resolution: bool = False,
    reviews: MagicMock | None = None,
    checks: MagicMock | None = None,
) -> MagicMock:
    """Build a mock PyGithub BranchProtection object."""
    protection = MagicMock(name="BranchProtection")
    protection.enforce_admins = enforce_admins
    protection.required_linear_history = required_linear_history
    protection.allow_force_pushes = allow_force_pushes
    protection.allow_deletions = allow_deletions
    protection.required_conversation_resolution = required_conversation_resolution
    protection.required_pull_request_reviews = reviews
    protection.required_status_checks = checks
    return protection


def test_no_branches_is_noop(repo: MagicMock) -> None:
    """An empty branch_protection map yields no changes and no API calls."""
    desired = RepoConfig(name="o/r")
    assert BranchProtectionManager().plan(repo, desired) == []
    repo.get_branch.assert_not_called()


def test_empty_rules_is_noop(repo: MagicMock) -> None:
    """A branch entry with no set fields produces no change."""
    desired = RepoConfig(name="o/r", branch_protection={"main": BranchProtection()})
    assert BranchProtectionManager().plan(repo, desired) == []
    repo.get_branch.assert_not_called()


def test_unprotected_branch_is_created(repo: MagicMock) -> None:
    """A 404 on get_protection means the branch is unprotected -> a CREATE change."""
    branch = repo.get_branch.return_value
    branch.get_protection.side_effect = GithubException(404, {}, None)
    desired = RepoConfig(
        name="o/r",
        branch_protection={
            "main": BranchProtection(enforce_admins=True, required_approving_review_count=2),
        },
    )

    changes = BranchProtectionManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.CREATE
    assert change.target == "branch:main"
    assert change.before is None
    change.apply()
    branch.edit_protection.assert_called_once_with(
        enforce_admins=True,
        required_approving_review_count=2,
    )


def test_matching_protection_is_skipped(repo: MagicMock) -> None:
    """Live protection matching the desired rules yields no change."""
    branch = repo.get_branch.return_value
    branch.get_protection.return_value = make_protection(enforce_admins=True)
    desired = RepoConfig(
        name="o/r",
        branch_protection={"main": BranchProtection(enforce_admins=True)},
    )
    assert BranchProtectionManager().plan(repo, desired) == []


def test_differing_protection_is_updated(repo: MagicMock) -> None:
    """A differing field on a protected branch yields an UPDATE that re-sends live state."""
    branch = repo.get_branch.return_value
    branch.get_protection.return_value = make_protection(enforce_admins=True)
    desired = RepoConfig(
        name="o/r",
        branch_protection={"main": BranchProtection(enforce_admins=False)},
    )

    changes = BranchProtectionManager().plan(repo, desired)

    assert len(changes) == 1
    assert changes[0].action is Action.UPDATE
    changes[0].apply()
    # edit_protection is a full replace, so all live modeled fields are re-sent with the
    # desired override applied (enforce_admins flipped to False).
    branch.edit_protection.assert_called_once_with(
        enforce_admins=False,
        required_linear_history=False,
        allow_force_pushes=False,
        allow_deletions=False,
        required_conversation_resolution=False,
    )


def test_unmanaged_protections_are_preserved(repo: MagicMock) -> None:
    """Regression: managing one field must not wipe other live protections."""
    reviews = MagicMock()
    reviews.required_approving_review_count = 2
    reviews.dismiss_stale_reviews = True
    reviews.require_code_owner_reviews = True
    branch = repo.get_branch.return_value
    branch.get_protection.return_value = make_protection(enforce_admins=True, reviews=reviews)
    # Config manages only required_linear_history.
    desired = RepoConfig(
        name="o/r",
        branch_protection={"main": BranchProtection(required_linear_history=True)},
    )

    changes = BranchProtectionManager().plan(repo, desired)

    assert len(changes) == 1
    changes[0].apply()
    branch.edit_protection.assert_called_once_with(
        enforce_admins=True,
        required_linear_history=True,
        allow_force_pushes=False,
        allow_deletions=False,
        required_conversation_resolution=False,
        required_approving_review_count=2,
        dismiss_stale_reviews=True,
        require_code_owner_reviews=True,
    )


def test_status_checks_and_reviews_match(repo: MagicMock) -> None:
    """Nested status checks and reviews are read and compared correctly."""
    reviews = MagicMock()
    reviews.required_approving_review_count = 1
    reviews.dismiss_stale_reviews = True
    reviews.require_code_owner_reviews = False
    checks = MagicMock()
    checks.strict = True
    checks.contexts = ["ci", "lint"]
    branch = repo.get_branch.return_value
    branch.get_protection.return_value = make_protection(reviews=reviews, checks=checks)
    desired = RepoConfig(
        name="o/r",
        branch_protection={
            "main": BranchProtection(
                required_approving_review_count=1,
                dismiss_stale_reviews=True,
                require_code_owner_reviews=False,
                required_status_checks=["lint", "ci"],
                strict_status_checks=True,
            ),
        },
    )
    assert BranchProtectionManager().plan(repo, desired) == []


def test_status_checks_differ_triggers_update(repo: MagicMock) -> None:
    """Different required status check contexts trigger an update mapping to edit kwargs."""
    checks = MagicMock()
    checks.strict = True
    checks.contexts = ["ci"]
    branch = repo.get_branch.return_value
    branch.get_protection.return_value = make_protection(checks=checks)
    desired = RepoConfig(
        name="o/r",
        branch_protection={
            "main": BranchProtection(
                required_status_checks=["ci", "lint"],
                strict_status_checks=True,
            ),
        },
    )

    changes = BranchProtectionManager().plan(repo, desired)

    assert len(changes) == 1
    changes[0].apply()
    branch.edit_protection.assert_called_once_with(
        enforce_admins=False,
        required_linear_history=False,
        allow_force_pushes=False,
        allow_deletions=False,
        required_conversation_resolution=False,
        contexts=["ci", "lint"],
        strict=True,
    )


def test_unexpected_github_error_propagates(repo: MagicMock) -> None:
    """A non-404 GithubException is not swallowed."""
    branch = repo.get_branch.return_value
    branch.get_protection.side_effect = GithubException(500, {}, None)
    desired = RepoConfig(
        name="o/r",
        branch_protection={"main": BranchProtection(enforce_admins=True)},
    )
    with pytest.raises(GithubException) as exc_info:
        BranchProtectionManager().plan(repo, desired)
    assert exc_info.value.status == 500
