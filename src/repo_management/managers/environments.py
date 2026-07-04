# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for deployment environments: protection rules plus scoped secrets/variables.

GitHub's ``create_environment`` endpoint is a PUT-upsert covering wait timer, reviewers,
self-review prevention, and branch policy in one call, so — like ``SettingsManager`` —
an unset ``Environment`` field is left unmanaged: its *current* live value is read back and
resent unchanged, since the API has no partial-update form.

A reviewer's ``login``/``slug`` is resolved to the numeric ID GitHub's API requires via the
same raw-REST route other managers use for endpoints PyGithub doesn't model (``repo.requester``
Requester also serves GitHub's global, non-repo-scoped endpoints — ``/users/{login}`` and
``/orgs/{org}/teams/{slug}`` — the same way PyGithub's own ``Github.get_user`` does).

Environment-scoped secrets/variables reuse :mod:`repo_management.managers._secret_variable`,
the same diff logic as the repo-scoped ``SecretsManager``/``VariablesManager``, since a
``Repository`` and an ``Environment`` expose identical secret/variable methods. For a brand
new environment there is nothing yet to diff its secrets/variables against, so its protection
rules and its secrets/variables are folded into one CREATE change whose ``apply`` creates the
environment first and then pushes each secret/variable against the now-real environment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from github.EnvironmentDeploymentBranchPolicy import EnvironmentDeploymentBranchPolicyParams
from github.EnvironmentProtectionRuleReviewer import ReviewerParams

from repo_management.changes import Action, Change
from repo_management.config import ConfigError
from repo_management.managers._secret_variable import plan_secrets, plan_variables

if TYPE_CHECKING:
    from github.Environment import Environment as GhEnvironment
    from github.Repository import Repository

    from repo_management.config import Environment, Reviewer, SharedConfig


class EnvironmentsManager:
    """Reconcile deployment environments: a declared section is authoritative and complete."""

    domain = "environments"

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return changes to create, update, and delete environments to match the config."""
        if desired.environments is None:
            return []

        existing = {env.name: env for env in repo.get_environments()}
        changes: list[Change] = []
        for item in desired.environments:
            changes.extend(self._plan_environment(repo, item, existing.get(item.name)))

        wanted_names = {item.name for item in desired.environments}
        changes.extend(self._delete(repo, name) for name in existing if name not in wanted_names)
        return changes

    def _plan_environment(
        self, repo: Repository, item: Environment, current: GhEnvironment | None
    ) -> list[Change]:
        reviewers = self._resolve_reviewers(repo, item.reviewers)
        if current is None:
            return [self._create(repo, item, reviewers)]

        changes: list[Change] = []
        rule_change = self._rule_change(repo, item, current, reviewers)
        if rule_change is not None:
            changes.append(rule_change)

        prefix = f"environment:{item.name}:"
        if item.secrets is not None:
            changes.extend(
                plan_secrets(current, item.secrets, domain=self.domain, target_prefix=prefix)
            )
        if item.variables is not None:
            changes.extend(
                plan_variables(current, item.variables, domain=self.domain, target_prefix=prefix)
            )
        return changes

    def _resolve_reviewers(
        self, repo: Repository, reviewers: list[Reviewer] | None
    ) -> list[dict[str, Any]] | None:
        if reviewers is None:
            return None
        return [self._resolve_reviewer(repo, reviewer) for reviewer in reviewers]

    def _resolve_reviewer(self, repo: Repository, reviewer: Reviewer) -> dict[str, Any]:
        if reviewer.type == "User":
            _, data = repo.requester.requestJsonAndCheck("GET", f"/users/{reviewer.login}")
            return {"type": "User", "id": data["id"]}

        org = repo.organization
        if org is None:
            msg = (
                f"environment reviewer of type 'Team' (slug={reviewer.slug!r}) requires an "
                "org-owned repository"
            )
            raise ConfigError(msg)
        _, data = repo.requester.requestJsonAndCheck(
            "GET", f"/orgs/{org.login}/teams/{reviewer.slug}"
        )
        return {"type": "Team", "id": data["id"]}

    def _rule_change(
        self,
        repo: Repository,
        item: Environment,
        current: GhEnvironment,
        reviewers: list[dict[str, Any]] | None,
    ) -> Change | None:
        before = _current_rules(current)
        after = dict(before)
        if item.wait_timer is not None:
            after["wait_timer"] = item.wait_timer
        if reviewers is not None:
            after["reviewers"] = reviewers
        if item.prevent_self_review is not None:
            after["prevent_self_review"] = item.prevent_self_review
        if item.deployment_branch_policy is not None:
            after["deployment_branch_policy"] = {
                "protected_branches": item.deployment_branch_policy.protected_branches,
                "custom_branch_policies": item.deployment_branch_policy.custom_branch_policies,
            }
        if _normalize(after) == _normalize(before):
            return None

        def apply() -> None:
            repo.create_environment(item.name, **_create_environment_kwargs(after))

        return Change(
            domain=self.domain,
            action=Action.UPDATE,
            target=f"environment:{item.name}",
            before=before,
            after=after,
            apply=apply,
        )

    def _create(
        self, repo: Repository, item: Environment, reviewers: list[dict[str, Any]] | None
    ) -> Change:
        rules = {
            "wait_timer": item.wait_timer or 0,
            "reviewers": reviewers or [],
            "prevent_self_review": item.prevent_self_review or False,
            "deployment_branch_policy": (
                {
                    "protected_branches": item.deployment_branch_policy.protected_branches,
                    "custom_branch_policies": item.deployment_branch_policy.custom_branch_policies,
                }
                if item.deployment_branch_policy is not None
                else None
            ),
        }

        def apply() -> None:
            env = repo.create_environment(item.name, **_create_environment_kwargs(rules))
            if item.secrets is not None:
                for change in plan_secrets(env, item.secrets, domain=self.domain):
                    change.apply()
            if item.variables is not None:
                for change in plan_variables(env, item.variables, domain=self.domain):
                    change.apply()

        after: dict[str, Any] = dict(rules)
        if item.secrets is not None:
            after["secrets"] = sorted(secret.name for secret in item.secrets)
        if item.variables is not None:
            after["variables"] = {variable.name: variable.resolve() for variable in item.variables}

        return Change(
            domain=self.domain,
            action=Action.CREATE,
            target=f"environment:{item.name}",
            before=None,
            after=after,
            apply=apply,
        )

    def _delete(self, repo: Repository, name: str) -> Change:
        def apply() -> None:
            repo.delete_environment(name)

        return Change(
            domain=self.domain,
            action=Action.DELETE,
            target=f"environment:{name}",
            before=f"environment:{name}",
            after=None,
            apply=apply,
        )


def _current_rules(current: GhEnvironment) -> dict[str, Any]:
    wait_timer = 0
    reviewers: list[dict[str, Any]] = []
    prevent_self_review = False
    for rule in current.protection_rules or []:
        if rule.type == "wait_timer":
            wait_timer = rule.wait_timer or 0
        elif rule.type == "required_reviewers":
            prevent_self_review = bool(rule.prevent_self_review)
            reviewers = [
                {"type": reviewer.type, "id": reviewer.reviewer.id}
                for reviewer in (rule.reviewers or [])
            ]

    policy = current.deployment_branch_policy
    branch_policy = (
        {
            "protected_branches": policy.protected_branches,
            "custom_branch_policies": policy.custom_branch_policies,
        }
        if policy is not None
        else None
    )
    return {
        "wait_timer": wait_timer,
        "reviewers": reviewers,
        "prevent_self_review": prevent_self_review,
        "deployment_branch_policy": branch_policy,
    }


def _normalize(rules: dict[str, Any]) -> dict[str, Any]:
    """An order-insensitive view of ``rules``, for equality comparison."""
    normalized = dict(rules)
    normalized["reviewers"] = sorted(
        (reviewer["type"], reviewer["id"]) for reviewer in rules["reviewers"]
    )
    return normalized


def _create_environment_kwargs(rules: dict[str, Any]) -> dict[str, Any]:
    policy = rules["deployment_branch_policy"]
    return {
        "wait_timer": rules["wait_timer"],
        "reviewers": [
            ReviewerParams(type_=reviewer["type"], id_=reviewer["id"])
            for reviewer in rules["reviewers"]
        ],
        "prevent_self_review": rules["prevent_self_review"],
        "deployment_branch_policy": (
            EnvironmentDeploymentBranchPolicyParams(**policy) if policy is not None else None
        ),
    }
