# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository security posture toggles.

Each of the five ``Security`` fields is an independent GitHub endpoint, so — unlike
``SettingsManager``'s single batched ``repo.edit`` — this manager may return up to three
changes: one combined change for the ``security_and_analysis`` sub-object (secret scanning +
push protection, since GitHub's PATCH takes both together), one for vulnerability alerts, one
for automated security fixes, and one for private vulnerability reporting (the last has no
PyGithub support, so it's driven directly through the authenticated requester, the same way
``RulesetsManager``/``ActionsManager`` handle endpoints PyGithub doesn't model). A 404 from
that endpoint is treated as "currently disabled" rather than an error, the same convention
``PagesManager`` uses for a feature that isn't configured yet.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from github import GithubException

from repo_management.changes import Action, Change

if TYPE_CHECKING:
    from github.Repository import Repository

    from repo_management.config import Security, SharedConfig


class SecurityManager:
    """Reconcile secret scanning, vulnerability alerts, security fixes, and PVR."""

    domain = "security"

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return changes for each independently-differing security toggle."""
        security = desired.security
        if security is None:
            return []

        candidates = [
            self._security_and_analysis_change(repo, security),
            self._vulnerability_alerts_change(repo, want=security.vulnerability_alerts),
            self._automated_security_fixes_change(repo, want=security.automated_security_fixes),
            self._private_vulnerability_reporting_change(
                repo, want=security.private_vulnerability_reporting
            ),
        ]
        return [change for change in candidates if change is not None]

    def _security_and_analysis_change(self, repo: Repository, security: Security) -> Change | None:
        wanted = {
            "secret_scanning": security.secret_scanning,
            "secret_scanning_push_protection": security.secret_scanning_push_protection,
        }
        if all(want is None for want in wanted.values()):
            return None

        current = repo.security_and_analysis
        before: dict[str, str | None] = {}
        payload: dict[str, dict[str, str]] = {}
        for field, want in wanted.items():
            if want is None:
                continue
            want_status = "enabled" if want else "disabled"
            # A feature can be absent (None) on a repo it doesn't apply to (e.g. secret
            # scanning push protection on a repo without secret scanning enabled) -- treat
            # that the same as "differs from any desired state" rather than crashing.
            current_status = getattr(getattr(current, field, None), "status", None)
            payload[field] = {"status": want_status}
            if current_status != want_status:
                before[field] = current_status
        if not before:
            return None

        def apply() -> None:
            repo.edit(security_and_analysis=payload)

        return Change(
            domain=self.domain,
            action=Action.UPDATE,
            target="security_and_analysis",
            before=before,
            after={field: value["status"] for field, value in payload.items()},
            apply=apply,
        )

    def _vulnerability_alerts_change(self, repo: Repository, *, want: bool | None) -> Change | None:
        if want is None:
            return None
        current = repo.get_vulnerability_alert()
        if current == want:
            return None

        def apply() -> None:
            repo.enable_vulnerability_alert() if want else repo.disable_vulnerability_alert()

        return Change(
            domain=self.domain,
            action=Action.UPDATE,
            target="vulnerability_alerts",
            before=current,
            after=want,
            apply=apply,
        )

    def _automated_security_fixes_change(
        self, repo: Repository, *, want: bool | None
    ) -> Change | None:
        if want is None:
            return None
        current = repo.get_automated_security_fixes()["enabled"]
        if current == want:
            return None

        def apply() -> None:
            if want:
                repo.enable_automated_security_fixes()
            else:
                repo.disable_automated_security_fixes()

        return Change(
            domain=self.domain,
            action=Action.UPDATE,
            target="automated_security_fixes",
            before=current,
            after=want,
            apply=apply,
        )

    def _private_vulnerability_reporting_change(
        self, repo: Repository, *, want: bool | None
    ) -> Change | None:
        if want is None:
            return None
        url = f"{repo.url}/private-vulnerability-reporting"
        try:
            _, data = repo.requester.requestJsonAndCheck("GET", url)
        except GithubException as exc:
            if exc.status != HTTPStatus.NOT_FOUND:
                raise
            current = False
        else:
            current = data["enabled"]
        if current == want:
            return None

        def apply() -> None:
            repo.requester.requestJsonAndCheck("PUT" if want else "DELETE", url)

        return Change(
            domain=self.domain,
            action=Action.UPDATE,
            target="private_vulnerability_reporting",
            before=current,
            after=want,
            apply=apply,
        )
