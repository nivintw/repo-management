# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the webhooks manager."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from conftest import make_hook

from repo_management.changes import Action
from repo_management.config import RepoConfig, Webhook
from repo_management.managers.webhooks import WebhooksManager


def test_no_webhooks_is_noop(repo: MagicMock) -> None:
    """A repo config without webhooks yields no changes."""
    desired = RepoConfig(name="o/r")
    assert WebhooksManager().plan(repo, desired) == []


def test_new_webhook_produces_create(repo: MagicMock) -> None:
    """A new webhook URL not present among existing hooks yields a CREATE change."""
    repo.get_hooks.return_value = []
    desired = RepoConfig(
        name="o/r",
        webhooks=[Webhook(url="https://example.com", events=["push"], active=True)],
    )

    changes = WebhooksManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.CREATE
    assert change.target == "webhook:https://example.com"
    assert change.before is None
    assert change.after == {
        "events": ["push"],
        "active": True,
        "content_type": "json",
        "insecure_ssl": False,
    }
    change.apply()
    repo.create_hook.assert_called_once_with(
        "web",
        {"url": "https://example.com", "content_type": "json", "insecure_ssl": "0"},
        events=["push"],
        active=True,
    )


def test_matching_webhook_is_skipped(repo: MagicMock) -> None:
    """An existing webhook with the same configuration produces no change."""
    repo.get_hooks.return_value = [make_hook("https://example.com", ["push"], active=True)]
    desired = RepoConfig(
        name="o/r",
        webhooks=[Webhook(url="https://example.com", events=["push"], active=True)],
    )
    assert WebhooksManager().plan(repo, desired) == []


def test_different_events_produces_update(repo: MagicMock) -> None:
    """An existing webhook with different events yields an UPDATE change."""
    existing = make_hook("https://example.com", ["push"], active=True)
    repo.get_hooks.return_value = [existing]
    desired = RepoConfig(
        name="o/r",
        webhooks=[Webhook(url="https://example.com", events=["pull_request"], active=True)],
    )

    changes = WebhooksManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.UPDATE
    assert change.before == {
        "events": ["push"],
        "active": True,
        "content_type": "json",
        "insecure_ssl": False,
    }
    assert change.after == {
        "events": ["pull_request"],
        "active": True,
        "content_type": "json",
        "insecure_ssl": False,
    }
    change.apply()
    existing.edit.assert_called_once_with(
        "web",
        {"url": "https://example.com", "content_type": "json", "insecure_ssl": "0"},
        events=["pull_request"],
        active=True,
    )


def test_webhook_with_secret_includes_secret_in_config(
    repo: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A webhook with secret_from_env includes the resolved secret in the hook config."""
    repo.get_hooks.return_value = []
    monkeypatch.setenv("WEBHOOK_SECRET", "supersecret")
    desired = RepoConfig(
        name="o/r",
        webhooks=[
            Webhook(
                url="https://example.com",
                events=["push"],
                active=True,
                secret_from_env="WEBHOOK_SECRET",
            ),
        ],
    )

    changes = WebhooksManager().plan(repo, desired)

    changes[0].apply()
    repo.create_hook.assert_called_once_with(
        "web",
        {
            "url": "https://example.com",
            "content_type": "json",
            "insecure_ssl": "0",
            "secret": "supersecret",
        },
        events=["push"],
        active=True,
    )


def test_secret_rotation_always_updates(repo: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: a configured secret forces an update even when nothing else changed."""
    existing = make_hook("https://example.com", ["push"], active=True)
    repo.get_hooks.return_value = [existing]
    monkeypatch.setenv("WEBHOOK_SECRET", "rotated")
    desired = RepoConfig(
        name="o/r",
        webhooks=[
            Webhook(
                url="https://example.com",
                events=["push"],
                active=True,
                secret_from_env="WEBHOOK_SECRET",
            ),
        ],
    )

    changes = WebhooksManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert "(set)" in change.describe()  # secret marker visible in the plan, value redacted
    change.apply()
    sent_config = existing.edit.call_args.args[1]
    assert isinstance(sent_config, dict)
    assert sent_config["secret"] == "rotated"


@pytest.mark.parametrize(
    "existing",
    [
        make_hook("https://example.com", ["push"], active=False),
        make_hook("https://example.com", ["push"], active=True, content_type="form"),
        make_hook("https://example.com", ["push"], active=True, insecure_ssl="1"),
    ],
)
def test_each_field_difference_triggers_update(repo: MagicMock, existing: MagicMock) -> None:
    """Each of active/content_type/insecure_ssl independently triggers an update.

    The desired webhook uses all defaults (active=True, content_type=json, insecure_ssl=0),
    so each existing hook above differs in exactly one field.
    """
    repo.get_hooks.return_value = [existing]
    desired = RepoConfig(
        name="o/r",
        webhooks=[Webhook(url="https://example.com", events=["push"])],
    )

    changes = WebhooksManager().plan(repo, desired)

    assert len(changes) == 1
    assert changes[0].action is Action.UPDATE


def test_matches_correct_hook_among_many(repo: MagicMock) -> None:
    """With several existing hooks, the one matching the URL is updated, others untouched."""
    other = make_hook("https://other.example/hook", ["push"], active=True)
    target = make_hook("https://example.com/hook", ["push"], active=True)
    repo.get_hooks.return_value = [other, target]
    desired = RepoConfig(
        name="o/r",
        webhooks=[Webhook(url="https://example.com/hook", events=["pull_request"], active=True)],
    )

    changes = WebhooksManager().plan(repo, desired)

    assert len(changes) == 1
    changes[0].apply()
    target.edit.assert_called_once()
    other.edit.assert_not_called()
