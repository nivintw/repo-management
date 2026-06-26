# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for per-branch protection rules."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from github import GithubException

from repo_management.changes import Action, Change

if TYPE_CHECKING:
    from github.Branch import Branch
    from github.BranchProtection import BranchProtection as GhBranchProtection
    from github.Repository import Repository

    from repo_management.config import BranchProtection, RepoConfig

_NOT_FOUND = 404


class BranchProtectionManager:
    """Reconcile branch protection rules for each configured branch."""

    domain = "branch_protection"

    def plan(self, repo: Repository, desired: RepoConfig) -> list[Change]:
        """Return one change per branch whose protection differs from desired."""
        if desired.branch_protection is None:
            return []
        changes: list[Change] = []
        for branch_name, rules in desired.branch_protection.items():
            change = self._branch_change(repo, branch_name, rules)
            if change is not None:
                changes.append(change)
        return changes

    def _branch_change(
        self,
        repo: Repository,
        branch_name: str,
        rules: BranchProtection,
    ) -> Change | None:
        want = _desired_state(rules)
        if not want:
            return None

        branch = repo.get_branch(branch_name)
        current = _current_state(branch)
        if current is not None and all(current.get(key) == value for key, value in want.items()):
            return None

        # edit_protection is a full replace (omitted fields are reset by the API), so the
        # apply must re-send the live modeled state with the desired fields overlaid —
        # otherwise managed-by-omission protections (e.g. enforce_admins) would be wiped.
        kwargs = _edit_kwargs({**(current or {}), **want})

        def apply() -> None:
            branch.edit_protection(**kwargs)

        action = Action.CREATE if current is None else Action.UPDATE
        before = None if current is None else {k: current.get(k) for k in want}
        return Change(
            domain=self.domain,
            action=action,
            target=f"branch:{branch_name}",
            before=before,
            after=want,
            apply=apply,
        )


def _desired_state(rules: BranchProtection) -> dict[str, Any]:
    """Normalize the desired rules into a comparable dict, dropping unset fields."""
    state: dict[str, Any] = rules.model_dump(exclude_none=True)
    if "required_status_checks" in state:
        state["required_status_checks"] = sorted(state["required_status_checks"])
    return state


def _current_state(branch: Branch) -> dict[str, Any] | None:
    """Read the live protection into the same shape as :func:`_desired_state`.

    Returns ``None`` when the branch has no protection.
    """
    try:
        protection = branch.get_protection()
    except GithubException as exc:
        if exc.status == _NOT_FOUND:
            return None
        raise
    return _read_protection(protection)


def _read_protection(protection: GhBranchProtection) -> dict[str, Any]:
    state: dict[str, Any] = {
        "enforce_admins": protection.enforce_admins,
        "required_linear_history": protection.required_linear_history,
        "allow_force_pushes": protection.allow_force_pushes,
        "allow_deletions": protection.allow_deletions,
        "required_conversation_resolution": protection.required_conversation_resolution,
    }
    reviews = protection.required_pull_request_reviews
    if reviews is not None:
        state["required_approving_review_count"] = reviews.required_approving_review_count
        state["dismiss_stale_reviews"] = reviews.dismiss_stale_reviews
        state["require_code_owner_reviews"] = reviews.require_code_owner_reviews
    checks = protection.required_status_checks
    if checks is not None:
        state["strict_status_checks"] = checks.strict
        state["required_status_checks"] = sorted(checks.contexts)
    return state


# Config field names that differ from edit_protection's kwarg names.
_EDIT_RENAME = {"required_status_checks": "contexts", "strict_status_checks": "strict"}


def _edit_kwargs(state: dict[str, Any]) -> dict[str, Any]:
    """Map a config-field-space state dict onto ``edit_protection`` kwargs."""
    return {_EDIT_RENAME.get(key, key): value for key, value in state.items()}
