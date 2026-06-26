# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository webhooks.

Webhooks are matched against existing hooks by their delivery URL. This manager is
additive: it creates and updates hooks but does not delete hooks absent from the config.
A webhook secret is write-only in the API and cannot be read back, so a change to *only*
the secret is not detected; the secret is (re)sent whenever the hook is otherwise updated.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from repo_management.changes import Action, Change

if TYPE_CHECKING:
    from github.Hook import Hook
    from github.Repository import Repository

    from repo_management.config import SharedConfig, Webhook

_HOOK_NAME = "web"


class WebhooksManager:
    """Create and update webhooks, matched by delivery URL."""

    domain = "webhooks"

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return changes to create or update each configured webhook."""
        if desired.webhooks is None:
            return []

        existing = {hook.config.get("url"): hook for hook in repo.get_hooks()}
        changes: list[Change] = []
        for webhook in desired.webhooks:
            current = existing.get(webhook.url)
            if current is None:
                changes.append(self._create(repo, webhook))
            elif _differs(current, webhook):
                changes.append(self._update(current, webhook))
        return changes

    def _create(self, repo: Repository, webhook: Webhook) -> Change:
        config = _config(webhook)
        events = list(webhook.events)
        active = webhook.active

        def apply() -> None:
            repo.create_hook(_HOOK_NAME, config, events=events, active=active)

        return Change(
            domain=self.domain,
            action=Action.CREATE,
            target=f"webhook:{webhook.url}",
            before=None,
            after=_display(webhook),
            apply=apply,
        )

    def _update(self, current: Hook, webhook: Webhook) -> Change:
        config = _config(webhook)
        events = list(webhook.events)
        active = webhook.active

        def apply() -> None:
            current.edit(_HOOK_NAME, config, events=events, active=active)

        return Change(
            domain=self.domain,
            action=Action.UPDATE,
            target=f"webhook:{webhook.url}",
            before=_display_hook(current),
            after=_display(webhook),
            apply=apply,
        )


def _config(webhook: Webhook) -> dict[str, str]:
    config = {
        "url": webhook.url,
        "content_type": webhook.content_type,
        "insecure_ssl": "1" if webhook.insecure_ssl else "0",
    }
    secret = webhook.resolve_secret()
    if secret is not None:
        config["secret"] = secret
    return config


def _differs(current: Hook, webhook: Webhook) -> bool:
    # A configured secret is write-only and can't be diffed, so (like Actions secrets) we
    # always re-send it — otherwise a secret rotation would be silently skipped.
    if webhook.secret_from_env is not None:
        return True
    return (
        sorted(current.events) != sorted(webhook.events)
        or current.active != webhook.active
        or current.config.get("content_type") != webhook.content_type
        or current.config.get("insecure_ssl") != ("1" if webhook.insecure_ssl else "0")
    )


def _display(webhook: Webhook) -> dict[str, Any]:
    display: dict[str, Any] = {
        "events": sorted(webhook.events),
        "active": webhook.active,
        "content_type": webhook.content_type,
        "insecure_ssl": webhook.insecure_ssl,
    }
    if webhook.secret_from_env is not None:
        display["secret"] = "(set)"  # noqa: S105 — redaction marker, not a secret value
    return display


def _display_hook(hook: Hook) -> dict[str, Any]:
    return {
        "events": sorted(hook.events),
        "active": hook.active,
        "content_type": hook.config.get("content_type"),
        "insecure_ssl": hook.config.get("insecure_ssl") == "1",
    }
