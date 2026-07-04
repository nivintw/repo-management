# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the security posture manager."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from github import GithubException

from repo_management.changes import Action
from repo_management.config import Security, SharedConfig
from repo_management.managers.security import SecurityManager

URL = "https://api.github.com/repos/o/r"


def _feature(status: str) -> MagicMock:
    feature = MagicMock(name=f"SecurityAndAnalysisFeature({status})")
    feature.status = status
    return feature


def _analysis(*, secret_scanning: str, push_protection: str) -> MagicMock:
    analysis = MagicMock(name="SecurityAndAnalysis")
    analysis.secret_scanning = _feature(secret_scanning)
    analysis.secret_scanning_push_protection = _feature(push_protection)
    return analysis


def test_no_security_is_noop(repo: MagicMock) -> None:
    """A repo config without a security section yields no changes."""
    assert SecurityManager().plan(repo, SharedConfig()) == []


def test_secret_scanning_change(repo: MagicMock) -> None:
    """A differing secret_scanning field yields a batched security_and_analysis change."""
    repo.security_and_analysis = _analysis(secret_scanning="disabled", push_protection="enabled")
    desired = SharedConfig(security=Security(secret_scanning=True))

    changes = SecurityManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.UPDATE
    assert change.target == "security_and_analysis"
    assert change.before == {"secret_scanning": "disabled"}
    assert change.after == {"secret_scanning": "enabled"}
    change.apply()
    repo.edit.assert_called_once_with(
        security_and_analysis={"secret_scanning": {"status": "enabled"}}
    )


def test_secret_scanning_in_sync(repo: MagicMock) -> None:
    """A matching secret_scanning field produces no change."""
    repo.security_and_analysis = _analysis(secret_scanning="enabled", push_protection="enabled")
    desired = SharedConfig(security=Security(secret_scanning=True))
    assert SecurityManager().plan(repo, desired) == []


def test_secret_scanning_and_push_protection_batched(repo: MagicMock) -> None:
    """Both fields differing yields one change covering both, in a single repo.edit call."""
    repo.security_and_analysis = _analysis(secret_scanning="disabled", push_protection="disabled")
    desired = SharedConfig(
        security=Security(secret_scanning=True, secret_scanning_push_protection=True)
    )

    changes = SecurityManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.before == {
        "secret_scanning": "disabled",
        "secret_scanning_push_protection": "disabled",
    }
    assert change.after == {
        "secret_scanning": "enabled",
        "secret_scanning_push_protection": "enabled",
    }
    change.apply()
    repo.edit.assert_called_once_with(
        security_and_analysis={
            "secret_scanning": {"status": "enabled"},
            "secret_scanning_push_protection": {"status": "enabled"},
        }
    )


def test_secret_scanning_only_differing_field_is_sent(repo: MagicMock) -> None:
    """Declaring both fields but only one differing sends and shows only that one.

    secret_scanning and secret_scanning_push_protection are independently settable on
    GitHub's API -- an already-matching field must not be resent, and must not appear in
    the user-facing diff as if it were changing.
    """
    repo.security_and_analysis = _analysis(secret_scanning="disabled", push_protection="enabled")
    desired = SharedConfig(
        security=Security(secret_scanning=True, secret_scanning_push_protection=True)
    )

    changes = SecurityManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.before == {"secret_scanning": "disabled"}
    assert change.after == {"secret_scanning": "enabled"}
    change.apply()
    repo.edit.assert_called_once_with(
        security_and_analysis={"secret_scanning": {"status": "enabled"}}
    )


def test_push_protection_unset_is_unmanaged(repo: MagicMock) -> None:
    """Leaving secret_scanning_push_protection unset never includes it in the payload."""
    repo.security_and_analysis = _analysis(secret_scanning="disabled", push_protection="disabled")
    desired = SharedConfig(security=Security(secret_scanning=True))

    changes = SecurityManager().plan(repo, desired)

    assert len(changes) == 1
    assert changes[0].after == {"secret_scanning": "enabled"}


def test_vulnerability_alerts_change(repo: MagicMock) -> None:
    """A differing vulnerability_alerts flag yields an enable/disable change."""
    repo.get_vulnerability_alert.return_value = False
    desired = SharedConfig(security=Security(vulnerability_alerts=True))

    changes = SecurityManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.target == "vulnerability_alerts"
    assert (change.before, change.after) == (False, True)
    change.apply()
    repo.enable_vulnerability_alert.assert_called_once_with()
    repo.disable_vulnerability_alert.assert_not_called()


def test_vulnerability_alerts_disable(repo: MagicMock) -> None:
    """A desired-false vulnerability_alerts calls disable, not enable."""
    repo.get_vulnerability_alert.return_value = True
    desired = SharedConfig(security=Security(vulnerability_alerts=False))

    changes = SecurityManager().plan(repo, desired)

    changes[0].apply()
    repo.disable_vulnerability_alert.assert_called_once_with()
    repo.enable_vulnerability_alert.assert_not_called()


def test_vulnerability_alerts_unset_is_unmanaged(repo: MagicMock) -> None:
    """Leaving vulnerability_alerts unset never calls get_vulnerability_alert."""
    desired = SharedConfig(security=Security(secret_scanning=None))
    SecurityManager().plan(repo, desired)
    repo.get_vulnerability_alert.assert_not_called()


def test_vulnerability_alerts_in_sync(repo: MagicMock) -> None:
    """A matching vulnerability_alerts flag produces no change."""
    repo.get_vulnerability_alert.return_value = True
    desired = SharedConfig(security=Security(vulnerability_alerts=True))
    assert SecurityManager().plan(repo, desired) == []


def test_automated_security_fixes_change(repo: MagicMock) -> None:
    """A differing automated_security_fixes flag yields an enable/disable change."""
    repo.get_automated_security_fixes.return_value = {"enabled": False, "paused": False}
    desired = SharedConfig(security=Security(automated_security_fixes=True))

    changes = SecurityManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.target == "automated_security_fixes"
    assert (change.before, change.after) == (False, True)
    change.apply()
    repo.enable_automated_security_fixes.assert_called_once_with()


def test_automated_security_fixes_disable(repo: MagicMock) -> None:
    """A desired-false automated_security_fixes calls disable, not enable."""
    repo.get_automated_security_fixes.return_value = {"enabled": True, "paused": False}
    desired = SharedConfig(security=Security(automated_security_fixes=False))

    changes = SecurityManager().plan(repo, desired)

    changes[0].apply()
    repo.disable_automated_security_fixes.assert_called_once_with()
    repo.enable_automated_security_fixes.assert_not_called()


def test_automated_security_fixes_in_sync(repo: MagicMock) -> None:
    """A matching automated_security_fixes flag produces no change."""
    repo.get_automated_security_fixes.return_value = {"enabled": True, "paused": False}
    desired = SharedConfig(security=Security(automated_security_fixes=True))
    assert SecurityManager().plan(repo, desired) == []


def test_private_vulnerability_reporting_change(repo: MagicMock) -> None:
    """A differing PVR flag yields a change that PUTs to enable."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = ({}, {"enabled": False})
    desired = SharedConfig(security=Security(private_vulnerability_reporting=True))

    changes = SecurityManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.target == "private_vulnerability_reporting"
    assert (change.before, change.after) == (False, True)
    change.apply()
    repo.requester.requestJsonAndCheck.assert_called_with(
        "PUT", f"{URL}/private-vulnerability-reporting"
    )


def test_private_vulnerability_reporting_disable(repo: MagicMock) -> None:
    """A desired-false PVR flag issues a DELETE to disable."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = ({}, {"enabled": True})
    desired = SharedConfig(security=Security(private_vulnerability_reporting=False))

    changes = SecurityManager().plan(repo, desired)

    changes[0].apply()
    repo.requester.requestJsonAndCheck.assert_called_with(
        "DELETE", f"{URL}/private-vulnerability-reporting"
    )


def test_private_vulnerability_reporting_unset_is_unmanaged(repo: MagicMock) -> None:
    """Leaving private_vulnerability_reporting unset never hits its endpoint."""
    desired = SharedConfig(security=Security(secret_scanning=None))
    SecurityManager().plan(repo, desired)
    repo.requester.requestJsonAndCheck.assert_not_called()


def test_private_vulnerability_reporting_in_sync(repo: MagicMock) -> None:
    """A matching PVR flag produces no change."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = ({}, {"enabled": True})
    desired = SharedConfig(security=Security(private_vulnerability_reporting=True))
    assert SecurityManager().plan(repo, desired) == []


def test_private_vulnerability_reporting_404_is_treated_as_disabled(repo: MagicMock) -> None:
    """A 404 from the PVR endpoint means 'not configured', mirroring PagesManager."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.side_effect = GithubException(404, {})
    desired = SharedConfig(security=Security(private_vulnerability_reporting=True))

    changes = SecurityManager().plan(repo, desired)

    assert len(changes) == 1
    assert (changes[0].before, changes[0].after) == (False, True)


def test_private_vulnerability_reporting_404_and_desired_false_is_noop(repo: MagicMock) -> None:
    """A 404 (already off) with a desired-false value produces no change."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.side_effect = GithubException(404, {})
    desired = SharedConfig(security=Security(private_vulnerability_reporting=False))
    assert SecurityManager().plan(repo, desired) == []


def test_private_vulnerability_reporting_non_404_propagates(repo: MagicMock) -> None:
    """A non-404 error from the GET is not swallowed as 'disabled'."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.side_effect = GithubException(500, {})
    desired = SharedConfig(security=Security(private_vulnerability_reporting=True))

    with pytest.raises(GithubException):
        SecurityManager().plan(repo, desired)


def test_secret_scanning_feature_absent_is_treated_as_differing(repo: MagicMock) -> None:
    """A feature GitHub omits (e.g. unsupported on this repo) doesn't crash the diff."""
    analysis = MagicMock(name="SecurityAndAnalysis")
    analysis.secret_scanning = None
    repo.security_and_analysis = analysis
    desired = SharedConfig(security=Security(secret_scanning=True))

    changes = SecurityManager().plan(repo, desired)

    assert len(changes) == 1
    assert changes[0].before == {"secret_scanning": None}


def test_every_security_field_produces_a_change(repo: MagicMock) -> None:
    """Guard: every Security field must be diffed by one of the four sub-changes.

    A field added to Security without a plan() handler would silently become unmanaged.
    """
    repo.url = URL
    repo.security_and_analysis = _analysis(secret_scanning="disabled", push_protection="disabled")
    repo.get_vulnerability_alert.return_value = False
    repo.get_automated_security_fixes.return_value = {"enabled": False}
    repo.requester.requestJsonAndCheck.return_value = ({}, {"enabled": False})
    desired = Security(
        secret_scanning=True,
        secret_scanning_push_protection=True,
        vulnerability_alerts=True,
        automated_security_fixes=True,
        private_vulnerability_reporting=True,
    )

    changes = SecurityManager().plan(repo, SharedConfig(security=desired))

    managed: set[str] = set()
    for change in changes:
        if change.target == "security_and_analysis":
            assert isinstance(change.after, dict)
            managed.update(str(key) for key in change.after)
        else:
            managed.add(change.target)
    assert managed == set(Security.model_fields)
