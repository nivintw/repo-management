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
from github import BadCredentialsException, GithubException, RateLimitExceededException

from repo_management import reconciler
from repo_management.changes import Action, Change
from repo_management.config import Config, ConfigError, Secret, Settings, SharedConfig
from repo_management.managers import build_managers
from repo_management.reconciler import (
    RepoPlan,
    apply_plan,
    plan_config,
    plan_repo,
    preflight_plan,
)


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


class _NeverApply(BaseException):
    """Raised by a test diagnostic's apply. Deliberately NOT an ``Exception``.

    ``apply_plan`` isolates every ``Exception`` a change raises, which would quietly absorb an
    ``AssertionError`` guard and leave the "diagnostics are never applied" invariant untested.
    A ``BaseException`` escapes that isolation, so the guard still fails the run loudly.
    """


def _diagnostic(target: str) -> Change:
    def _raise() -> None:
        msg = "a diagnostic must never be applied"
        raise _NeverApply(msg)

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
    """apply_plan applies actionable changes and never invokes a diagnostic's apply.

    ``report.failed`` must stay empty: the diagnostic has to be *never attempted*, not
    attempted and swallowed by the per-change isolation.
    """
    calls: list[str] = []
    good = Change("x", Action.CREATE, "a", None, None, lambda: calls.append("a"))
    report = apply_plan(RepoPlan("o/r", [good, _diagnostic("variable:X")]))
    assert calls == ["a"]
    assert report.failed == []


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

    # The webhooks 403 says nothing about labels, so both label writes still ran.
    assert calls == ["a", "b"]
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


def test_preflight_isolates_a_non_config_error() -> None:
    """A preflight raising something other than ConfigError costs its repo, not the fleet.

    The pre-isolation code caught only ConfigError here. Anything else propagated out of the
    partition pass, past _api_errors (which knows four types, none of them ValueError), and
    killed the entire fleet apply before a single repo was written — the exact failure mode
    this change exists to remove, on the one path that used to be narrowest.
    """
    change = Change(
        "secrets",
        Action.CREATE,
        "secret:TOK",
        None,
        None,
        lambda: None,
        preflight=_raiser(ValueError("resolver blew up")),
    )

    reason = preflight_plan(RepoPlan("o/r", [change]))

    assert reason is not None
    assert "ValueError" in reason
    # An unanticipated type keeps its traceback on this path too, not just the plan path.
    assert "Traceback" in reason


def test_preflight_reports_an_expected_failure_without_a_traceback() -> None:
    """A missing env var is fully described by its message, so it stays a one-liner."""
    change = Change(
        "secrets",
        Action.CREATE,
        "secret:TOK",
        None,
        None,
        lambda: None,
        preflight=_raiser(ConfigError("environment variable 'TOK_SRC' is not set or is empty")),
    )

    reason = preflight_plan(RepoPlan("o/r", [change]))

    assert reason is not None
    assert "TOK_SRC" in reason
    assert "Traceback" not in reason


def test_preflight_holds_back_a_plan_carrying_problems() -> None:
    """A plan with any diagnostic is held back before its payloads are even resolved."""
    resolved: list[str] = []
    change = Change(
        "secrets",
        Action.CREATE,
        "secret:TOK",
        None,
        None,
        lambda: None,
        preflight=lambda: resolved.append("TOK"),
    )

    reason = preflight_plan(RepoPlan("o/r", [change, _diagnostic("variable:X")]))

    assert reason is not None
    assert "problem(s) in its plan" in reason
    assert resolved == []  # held back before any payload resolution


def test_preflight_clears_a_healthy_plan() -> None:
    """A plan whose payloads all resolve is cleared to write."""
    resolved: list[str] = []
    change = Change(
        "secrets",
        Action.CREATE,
        "secret:TOK",
        None,
        None,
        lambda: None,
        preflight=lambda: resolved.append("TOK"),
    )

    assert preflight_plan(RepoPlan("o/r", [change])) is None
    assert resolved == ["TOK"]


def test_apply_plan_keeps_the_traceback_for_an_unanticipated_write_failure() -> None:
    """A change whose apply() raises an unexpected type keeps its traceback in the report.

    The write path deserves the same treatment as the plan path: a TypeError mid-apply is a bug
    in this tool, and flattening it to one line would cost the stack trace that explains it.
    """
    plan = RepoPlan(
        "o/r",
        [
            Change("labels", Action.CREATE, "label:a", None, None, _raiser(TypeError("nope"))),
            Change(
                "webhooks",
                Action.CREATE,
                "webhook:x",
                None,
                None,
                _raiser(GithubException(403, {"message": "Must have admin rights"})),
            ),
        ],
    )

    report = apply_plan(plan)

    errors = {change.target: error for change, error in report.failed}
    assert "Traceback" in errors["label:a"]  # unanticipated -> keeps the stack
    assert "Traceback" not in errors["webhook:x"]  # anticipated -> one line
    assert "Must have admin rights" in errors["webhook:x"]  # the API's own message, not the repr


def test_apply_plan_abandons_the_rest_of_a_domain_after_a_failure() -> None:
    """A failed write must not let its own domain's later changes run — they may undo it.

    Every authoritative manager emits creates/updates first and deletes last, so a rename is a
    CREATE of the new name followed by a DELETE of the old. If the CREATE is rejected and the
    DELETE runs anyway, the repository ends up WORSE than before the run: the old ruleset is
    gone and nothing replaced it. Guards against per-change isolation being restored here.
    """
    deleted: list[str] = []
    plan = RepoPlan(
        "o/r",
        [
            Change(
                "rulesets",
                Action.CREATE,
                "ruleset:new",
                None,
                None,
                _raiser(GithubException(422, {"message": "Upgrade to GitHub Team"})),
            ),
            Change(
                "rulesets",
                Action.DELETE,
                "ruleset:old",
                None,
                None,
                lambda: deleted.append("ruleset:old"),
            ),
        ],
    )

    report = apply_plan(plan)

    assert deleted == []  # the branch protection survives the failed replacement
    assert [change.target for change, _ in report.failed] == ["ruleset:new"]
    # Abandoned, not silently dropped — the operator is told it was never attempted.
    assert [change.target for change, _ in report.abandoned] == ["ruleset:old"]


def test_apply_plan_still_isolates_across_domains() -> None:
    """A failure in one domain must not stop a different one — that isolation is the point."""
    applied: list[str] = []
    plan = RepoPlan(
        "o/r",
        [
            Change(
                "webhooks",
                Action.CREATE,
                "webhook:x",
                None,
                None,
                _raiser(GithubException(403, {"message": "Must have admin rights"})),
            ),
            Change("labels", Action.CREATE, "label:a", None, None, lambda: applied.append("a")),
        ],
    )

    report = apply_plan(plan)

    assert applied == ["a"]  # a different domain is unaffected
    assert report.abandoned == []
    assert [change.target for change, _ in report.failed] == ["webhook:x"]


def test_apply_plan_lets_a_fleet_fatal_condition_escape() -> None:
    """A dead token mid-apply dooms the run, so it must not be isolated as a failed change.

    Isolating it would record the same problem once per change in every remaining repository,
    and — because PyGithub retries rate-limit responses with backoff — turn one fast failure
    into a long stall that deepens the secondary-rate-limit penalty.
    """
    plan = RepoPlan(
        "o/r",
        [
            Change(
                "labels",
                Action.CREATE,
                "label:a",
                None,
                None,
                _raiser(BadCredentialsException(401, {"message": "Bad credentials"})),
            )
        ],
    )

    with pytest.raises(BadCredentialsException):
        apply_plan(plan)


def test_plan_repo_lets_a_fleet_fatal_condition_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same contract on the plan side: a rate-limit wall is the run's problem, not a domain's."""
    broken = MagicMock(domain="rulesets")
    broken.plan.side_effect = RateLimitExceededException(403, {"message": "rate limit exceeded"})
    monkeypatch.setattr(reconciler, "build_managers", lambda **_kw: [broken])

    with pytest.raises(RateLimitExceededException):
        plan_repo(MagicMock(), SharedConfig())
