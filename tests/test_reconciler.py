# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the reconciliation engine."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import NoReturn
from unittest.mock import MagicMock

import pytest
from conftest import make_secret
from github import GithubException

from repo_management import reconciler
from repo_management.changes import Action, Change
from repo_management.config import Config, ConfigError, Secret, Settings, SharedConfig
from repo_management.managers import build_managers
from repo_management.reconciler import RepoPlan, apply_plan, plan_config, plan_repo


def test_build_managers_registers_every_domain() -> None:
    """Guard the registry: every manager domain must be present exactly once.

    A manager built but never appended to build_managers() would silently never run.
    """
    domains = [manager.domain for manager in build_managers()]
    assert len(domains) == len(set(domains))
    assert set(domains) == {
        "settings",
        "actions",
        "security",
        "rulesets",
        "labels",
        "collaborators",
        "teams",
        "codeowners",
        "webhooks",
        "deploy_keys",
        "autolinks",
        "pages",
        "secrets",
        "variables",
        "environments",
    }


def test_plan_repo_aggregates_managers(repo: MagicMock) -> None:
    """plan_repo collects changes from every manager that has work."""
    repo.description = "old"
    repo.get_topics.return_value = []
    desired = SharedConfig(settings=Settings(description="new", topics=["x"]))

    changes = plan_repo(repo, desired)

    targets = {c.target for c in changes}
    assert "settings" in targets
    assert "topics" in targets


def test_plan_repo_force_secrets_repushes(repo: MagicMock) -> None:
    """force_secrets threads through build_managers so existing secrets are re-pushed."""
    repo.get_secrets.return_value = [make_secret("EXISTING")]
    desired = SharedConfig(secrets=[Secret(name="EXISTING", value="v")])

    assert plan_repo(repo, desired) == []
    assert [c.action for c in plan_repo(repo, desired, force_secrets=True)] == [Action.UPDATE]


def test_plan_config_builds_a_plan_per_repo() -> None:
    """plan_config fetches each named repo and returns one RepoPlan apiece."""
    repo = MagicMock()
    repo.description = "match"
    client = MagicMock()
    client.get_repo.return_value = repo
    config = Config(repos=["o/r1", "o/r2"], settings=Settings(description="match"))

    plans = plan_config(client, config)

    assert [p.repo_name for p in plans] == ["o/r1", "o/r2"]
    assert all(p.in_sync for p in plans)
    assert client.get_repo.call_count == 2


def _capture_source_secrets(monkeypatch: pytest.MonkeyPatch, fetched: MagicMock) -> list[object]:
    """Wire plan_config's collaborators to a mock fetch and capture what plan_repo receives."""
    monkeypatch.setattr(reconciler, "source_secret_timestamps", fetched)
    monkeypatch.setattr(reconciler, "get_repo", lambda _client, name: name)
    seen: list[object] = []
    monkeypatch.setattr(
        reconciler,
        "plan_repo",
        lambda _repo, _cfg, *, source_secrets=None, **_: seen.append(source_secrets) or [],
    )
    return seen


def test_plan_config_threads_source_secret_timestamps(monkeypatch: pytest.MonkeyPatch) -> None:
    """plan_config reads source secret timestamps once and hands them to every repo's plan."""
    stamps = {"TOKEN_SRC": datetime(2026, 6, 1, tzinfo=UTC)}
    fetched = MagicMock(return_value=stamps)
    seen = _capture_source_secrets(monkeypatch, fetched)
    config = Config(repos=["o/r1", "o/r2"], secrets=[Secret(name="T", value_from_env="TOKEN_SRC")])

    plan_config(MagicMock(), config)

    fetched.assert_called_once()
    assert seen == [stamps, stamps]  # same map shared across both repos, fetched only once


def test_plan_config_skips_source_read_when_nothing_would_use_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No env-sourced secret, or --force-secrets, means no wasted source-timestamp read."""
    fetched = MagicMock(return_value={})
    seen = _capture_source_secrets(monkeypatch, fetched)

    # Inline-value-only secrets: nothing is timestamp-compared, so don't read.
    inline = Config(repos=["o/r1"], secrets=[Secret(name="T", value="literal")])
    plan_config(MagicMock(), inline)
    # value_from_env present, but --force-secrets re-pushes everything regardless.
    env_sourced = Config(repos=["o/r1"], secrets=[Secret(name="T", value_from_env="TOKEN_SRC")])
    plan_config(MagicMock(), env_sourced, force_secrets=True)

    fetched.assert_not_called()
    assert seen == [{}, {}]


def test_repo_plan_in_sync() -> None:
    """RepoPlan.in_sync reflects whether there are changes."""
    assert RepoPlan("o/r").in_sync
    change = Change("x", Action.CREATE, "t", None, None, lambda: None)
    assert not RepoPlan("o/r", [change]).in_sync


def test_apply_plan_invokes_each_change() -> None:
    """apply_plan calls apply() on every change in order."""
    calls: list[str] = []
    plan = RepoPlan(
        "o/r",
        [
            Change("x", Action.CREATE, "a", None, None, lambda: calls.append("a")),
            Change("x", Action.UPDATE, "b", None, None, lambda: calls.append("b")),
        ],
    )
    apply_plan(plan)
    assert calls == ["a", "b"]


def _diagnostic(target: str) -> Change:
    def _raise() -> None:
        msg = "a diagnostic must never be applied"
        raise AssertionError(msg)

    return Change("variables", Action.UPDATE, target, None, None, _raise, error="value unset")


def test_repo_plan_partitions_actionable_and_problems() -> None:
    """actionable/problems split real changes from unresolved-value diagnostics."""
    good = Change("settings", Action.UPDATE, "description", "old", "new", lambda: None)
    bad = _diagnostic("variable:REGION")
    plan = RepoPlan("o/r", [good, bad])

    assert plan.actionable == [good]
    assert plan.problems == [bad]
    assert not plan.in_sync  # a plan carrying a diagnostic is not "in sync"


def test_apply_plan_skips_diagnostics() -> None:
    """apply_plan applies actionable changes and never invokes a diagnostic's apply."""
    calls: list[str] = []
    good = Change("x", Action.CREATE, "a", None, None, lambda: calls.append("a"))
    apply_plan(RepoPlan("o/r", [good, _diagnostic("variable:X")]))
    assert calls == ["a"]


def _raiser(exc: Exception) -> Callable[..., NoReturn]:
    """A callable that raises ``exc`` whatever it's handed."""

    def _raise(*_args: object, **_kwargs: object) -> NoReturn:
        raise exc

    return _raise


def test_plan_repo_isolates_a_failing_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """One manager's plan() blowing up costs its own domain, not the other managers'."""
    ok = MagicMock(domain="labels")
    ok.plan.return_value = [Change("labels", Action.CREATE, "label:bug", None, "bug", lambda: None)]
    broken = MagicMock(domain="rulesets")
    broken.plan.side_effect = GithubException(403, {"message": "Upgrade required"})
    monkeypatch.setattr(reconciler, "build_managers", lambda **_kw: [broken, ok])

    changes = plan_repo(MagicMock(), SharedConfig())

    # The healthy domain still planned...
    assert [change.target for change in changes if not change.unresolved] == ["label:bug"]
    # ...and the broken one degraded to a diagnostic naming its own domain and its type.
    (problem,) = [change for change in changes if change.unresolved]
    assert problem.domain == "rulesets"
    assert "GithubException" in str(problem.error)


def test_plan_repo_isolates_an_unexpected_exception_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """A type _api_errors never caught (ValueError, reachable via rulesets) is isolated too.

    These tracebacked before fault isolation existed, so covering an unanticipated type is the
    point rather than an edge case.
    """
    broken = MagicMock(domain="rulesets")
    broken.plan.side_effect = ValueError("no bypass actor 'platform'")
    monkeypatch.setattr(reconciler, "build_managers", lambda **_kw: [broken])

    (problem,) = plan_repo(MagicMock(), SharedConfig())

    assert problem.unresolved
    assert "ValueError" in str(problem.error)
    # An unanticipated type keeps its traceback: flattening a bug in this tool to one line would
    # trade a stack trace for a sentence nobody can act on.
    assert "Traceback" in str(problem.error)


def test_plan_repo_keeps_an_expected_failure_to_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """An anticipated failure is fully described by its message, so it carries no traceback."""
    broken = MagicMock(domain="pages")
    broken.plan.side_effect = ConfigError("cannot access repository 'o/gone'")
    monkeypatch.setattr(reconciler, "build_managers", lambda **_kw: [broken])

    (problem,) = plan_repo(MagicMock(), SharedConfig())

    assert "ConfigError" in str(problem.error)
    assert "Traceback" not in str(problem.error)


def test_plan_config_isolates_a_failing_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """A repo that can't be fetched costs its own plan; every other repo still plans."""
    monkeypatch.setattr(
        reconciler,
        "get_repo",
        lambda _client, name: (
            _raiser(ConfigError(f"cannot access repository {name!r}"))()
            if name == "o/gone"
            else name
        ),
    )
    monkeypatch.setattr(reconciler, "plan_repo", lambda *_a, **_kw: [])

    plans = plan_config(MagicMock(), Config(repos=["o/first", "o/gone", "o/last"]))

    assert [plan.repo_name for plan in plans] == ["o/first", "o/gone", "o/last"]
    assert [not plan.problems for plan in plans] == [True, False, True]
    (problem,) = plans[1].problems
    assert problem.domain == "repo"
    assert "o/gone" in str(problem.error)


def test_plan_config_isolates_a_repo_failing_late(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fleet survives a mid-run failure, and the repos after it still plan.

    Guards the original bug directly: a failure on a middle repo used to discard every plan
    already computed, leaving the operator with one error line and no diff at all.
    """
    monkeypatch.setattr(reconciler, "get_repo", lambda _client, name: name)
    monkeypatch.setattr(
        reconciler,
        "plan_repo",
        lambda repo, *_a, **_kw: _raiser(TypeError("expected a file"))() if repo == "o/b" else [],
    )

    plans = plan_config(MagicMock(), Config(repos=["o/a", "o/b", "o/c"]))

    assert [not plan.problems for plan in plans] == [True, False, True]
    assert "TypeError" in str(plans[1].problems[0].error)


def test_apply_plan_isolates_a_failing_change() -> None:
    """A failed write costs its own change; the repo's remaining changes still apply."""
    calls: list[str] = []
    plan = RepoPlan(
        "o/r",
        [
            Change("labels", Action.CREATE, "label:a", None, None, lambda: calls.append("a")),
            Change(
                "webhooks",
                Action.CREATE,
                "webhook:x",
                None,
                None,
                _raiser(GithubException(403, {"message": "Must have admin rights"})),
            ),
            Change("labels", Action.CREATE, "label:b", None, None, lambda: calls.append("b")),
        ],
    )

    report = apply_plan(plan)

    assert calls == ["a", "b"]  # the 403 did not abandon the change after it
    assert report.failed
    assert [change.target for change in report.applied] == ["label:a", "label:b"]
    (failed, error) = report.failed[0]
    assert failed.target == "webhook:x"
    assert "GithubException" in error


def test_apply_plan_reports_a_clean_run() -> None:
    """Every change applying cleanly reports ok with each change recorded."""
    plan = RepoPlan("o/r", [Change("labels", Action.CREATE, "label:a", None, None, lambda: None)])

    report = apply_plan(plan)

    assert report.failed == []
    assert report.repo_name == "o/r"
    assert [change.target for change in report.applied] == ["label:a"]
