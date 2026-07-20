# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the rulesets manager."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from github import GithubException

from repo_management.changes import Action
from repo_management.config import SharedConfig
from repo_management.managers.rulesets import RulesetsManager, _BypassActorResolver, _satisfied
from repo_management.ruleset import Ruleset

URL = "https://api.github.com/repos/o/r"


def make_resolver_repo(routes: dict[str, Any], org: str = "o") -> MagicMock:
    """A mock repo whose requester answers ``_BypassActorResolver`` lookups by exact path.

    ``routes`` maps a request path (``/apps/x``, ``/orgs/o/teams/t``, …) to the JSON body to
    return; an unrouted path raises a 404 GithubException, mirroring the real API.
    """
    repo = MagicMock()
    repo.owner.login = org

    def request(verb: str, url: str, **_kwargs: object) -> tuple[dict, Any]:
        if verb == "GET" and url in routes:
            return ({}, routes[url])
        raise GithubException(404, {"message": "Not Found"}, None)

    repo.requester.requestJsonAndCheck.side_effect = request
    return repo


def make_repo(list_data: list[dict[str, Any]], get_data: dict[str, Any] | None = None) -> MagicMock:
    """Build a mock repo whose requester answers list/get and records writes."""
    repo = MagicMock()
    repo.url = URL

    def request(verb: str, url: str, **_kwargs: object) -> tuple[dict, Any]:
        if verb == "GET" and url.split("?", maxsplit=1)[0] == f"{URL}/rulesets":
            return ({}, list_data)
        if verb == "GET" and url.startswith(f"{URL}/rulesets/"):
            return ({}, get_data)
        return ({}, {})  # POST / PUT / DELETE

    repo.requester.requestJsonAndCheck.side_effect = request
    return repo


def ruleset(**overrides: object) -> Ruleset:
    """A simple desired ruleset for tests."""
    data: dict[str, Any] = {
        "name": "main",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [{"type": "required_linear_history"}],
    }
    data.update(overrides)
    return Ruleset.model_validate(data)


def test_no_rulesets_is_noop() -> None:
    """A config without a rulesets section yields no changes."""
    repo = make_repo([])
    assert RulesetsManager().plan(repo, SharedConfig()) == []
    repo.requester.requestJsonAndCheck.assert_not_called()


def test_new_ruleset_is_created() -> None:
    """A ruleset absent on the repo yields a CREATE that POSTs the body."""
    repo = make_repo([])
    desired = SharedConfig(rulesets=[ruleset()])

    changes = RulesetsManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.CREATE
    assert change.target == "ruleset:main"
    assert change.before is None
    change.apply()
    repo.requester.requestJsonAndCheck.assert_any_call(
        "POST",
        f"{URL}/rulesets",
        input=ruleset().to_api(),
    )


def test_matching_ruleset_is_skipped() -> None:
    """A live ruleset matching the desired spec yields no change."""
    desired = ruleset()
    current = {"id": 1, "source": "Repository", **desired.to_api()}
    repo = make_repo([{"id": 1, "name": "main"}], current)

    assert RulesetsManager().plan(repo, SharedConfig(rulesets=[desired])) == []


def test_param_order_does_not_cause_diff() -> None:
    """List ordering inside rule parameters doesn't spuriously trigger an update."""
    desired = ruleset(rules=[{"type": "required_status_checks", "required_checks": ["a", "b"]}])
    current_body = ruleset(
        rules=[{"type": "required_status_checks", "required_checks": ["b", "a"]}],
    ).to_api()
    repo = make_repo([{"id": 1, "name": "main"}], {"id": 1, **current_body})

    assert RulesetsManager().plan(repo, SharedConfig(rulesets=[desired])) == []


def test_differing_ruleset_is_updated() -> None:
    """A live ruleset differing from desired yields an UPDATE that PUTs to its id."""
    desired = ruleset(enforcement="active")
    current = {"id": 42, **ruleset(enforcement="disabled").to_api()}
    repo = make_repo([{"id": 42, "name": "main"}], current)

    changes = RulesetsManager().plan(repo, SharedConfig(rulesets=[desired]))

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.UPDATE
    change.apply()
    repo.requester.requestJsonAndCheck.assert_any_call(
        "PUT",
        f"{URL}/rulesets/42",
        input=desired.to_api(),
    )


def test_differing_conditions_triggers_update() -> None:
    """Different ref-name conditions trigger an update."""
    desired = ruleset()
    other = ruleset(conditions={"ref_name": {"include": ["refs/heads/release/*"], "exclude": []}})
    repo = make_repo([{"id": 1, "name": "main"}], {"id": 1, **other.to_api()})

    changes = RulesetsManager().plan(repo, SharedConfig(rulesets=[desired]))

    assert len(changes) == 1
    assert changes[0].action is Action.UPDATE


def test_differing_bypass_actors_triggers_update() -> None:
    """Different bypass actors trigger an update."""
    desired = ruleset(bypass_actors=[{"actor_type": "OrganizationAdmin"}])
    current = {"id": 1, **ruleset().to_api()}  # no bypass actors
    repo = make_repo([{"id": 1, "name": "main"}], current)

    changes = RulesetsManager().plan(repo, SharedConfig(rulesets=[desired]))

    assert len(changes) == 1
    assert changes[0].action is Action.UPDATE


def test_rule_added_triggers_update() -> None:
    """Adding a rule type to the desired spec triggers an update."""
    desired = ruleset(rules=[{"type": "required_linear_history"}, {"type": "non_fast_forward"}])
    current = {"id": 1, **ruleset(rules=[{"type": "required_linear_history"}]).to_api()}
    repo = make_repo([{"id": 1, "name": "main"}], current)

    changes = RulesetsManager().plan(repo, SharedConfig(rulesets=[desired]))

    assert len(changes) == 1
    assert changes[0].action is Action.UPDATE


def test_extra_live_rule_triggers_update() -> None:
    """A rule present on the repo but absent from the config is drift that triggers update."""
    desired = ruleset(rules=[{"type": "required_linear_history"}])
    current = {
        "id": 1,
        **ruleset(
            rules=[{"type": "required_linear_history"}, {"type": "non_fast_forward"}],
        ).to_api(),
    }
    repo = make_repo([{"id": 1, "name": "main"}], current)

    changes = RulesetsManager().plan(repo, SharedConfig(rulesets=[desired]))

    assert len(changes) == 1
    assert changes[0].action is Action.UPDATE


def test_unlisted_ruleset_is_deleted() -> None:
    """A declared rulesets section is authoritative: a repo ruleset absent from it is deleted."""
    desired = ruleset()
    current = {"id": 1, **desired.to_api()}
    repo = make_repo([{"id": 1, "name": "main"}, {"id": 2, "name": "legacy"}], current)

    changes = RulesetsManager().plan(repo, SharedConfig(rulesets=[desired]))

    assert len(changes) == 1  # main is in sync; legacy is pruned
    change = changes[0]
    assert change.action is Action.DELETE
    assert change.target == "ruleset:legacy"
    assert change.after is None
    change.apply()
    repo.requester.requestJsonAndCheck.assert_any_call("DELETE", f"{URL}/rulesets/2")


def test_list_excludes_inherited_rulesets() -> None:
    """Listing passes includes_parents=false so inherited org rulesets aren't managed."""
    repo = make_repo([])

    RulesetsManager().plan(repo, SharedConfig(rulesets=[ruleset()]))

    repo.requester.requestJsonAndCheck.assert_any_call(
        "GET",
        f"{URL}/rulesets?includes_parents=false&per_page=100&page=1",
    )


def test_list_paginates_beyond_one_page() -> None:
    """A repo owning >100 rulesets is fully listed by walking pages (drift isn't dropped)."""
    page1 = [{"id": i, "name": f"rs-{i}"} for i in range(100)]
    page2 = [{"id": 100, "name": "rs-100"}]

    def request(verb: str, url: str, **_kwargs: object) -> tuple[dict, Any]:
        if verb == "GET" and url.split("?", maxsplit=1)[0] == f"{URL}/rulesets":
            return ({}, page2 if "page=2" in url else page1)
        return ({}, {})

    repo = MagicMock()
    repo.url = URL
    repo.requester.requestJsonAndCheck.side_effect = request

    # An authoritative empty config deletes every listed ruleset — one DELETE per ruleset
    # proves all 101 (across both pages) were seen, not just the first page's 100.
    changes = RulesetsManager().plan(repo, SharedConfig(rulesets=[]))
    assert len(changes) == 101
    assert all(change.action is Action.DELETE for change in changes)


def test_realistic_server_response_is_in_sync() -> None:
    """A realistic GET-by-id response with server-added keys yields no spurious diff.

    GitHub's response carries metadata the spec never sets (``id``, timestamps,
    ``integration_id``, bypass ``actor_id``, default parameters). The subset matcher must
    treat the live ruleset as already satisfying the desired spec — otherwise every plan
    would perpetually re-issue an update.
    """
    desired = Ruleset.model_validate(
        {
            "name": "main",
            "enforcement": "active",
            "bypass_actors": [{"actor_type": "OrganizationAdmin"}],
            "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
            "rules": [
                {"type": "required_status_checks", "required_checks": ["ci"]},
                {"type": "pull_request", "required_approving_review_count": 1},
                {"type": "non_fast_forward"},
            ],
        },
    )
    current = {
        "id": 7,
        "name": "main",
        "target": "branch",
        "enforcement": "active",
        "node_id": "RRS_lABC",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-02-01T00:00:00Z",
        "source_type": "Repository",
        "source": "o/r",
        "current_user_can_bypass": "always",
        "_links": {"self": {"href": f"{URL}/rulesets/7"}},
        "bypass_actors": [
            {"actor_id": 1, "actor_type": "OrganizationAdmin", "bypass_mode": "always"},
        ],
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [{"context": "ci", "integration_id": None}],
                    "strict_required_status_checks_policy": False,
                    "do_not_enforce_on_create": False,
                },
            },
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 1,
                    "dismiss_stale_reviews_on_push": False,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": False,
                },
            },
            {"type": "non_fast_forward"},
        ],
    }
    repo = make_repo([{"id": 7, "name": "main"}], current)

    assert RulesetsManager().plan(repo, SharedConfig(rulesets=[desired])) == []


def test_tag_targeted_ruleset_is_created() -> None:
    """A tag-targeted ruleset (e.g. protecting v* release tags) is created like any other."""
    desired = ruleset(
        name="protect release tags",
        target="tag",
        conditions={"ref_name": {"include": ["v*"], "exclude": []}},
        rules=[{"type": "creation"}, {"type": "update"}, {"type": "deletion"}],
        bypass_actors=[{"actor_type": "Integration", "actor_id": 998885}],
    )
    repo = make_repo([])

    changes = RulesetsManager().plan(repo, SharedConfig(rulesets=[desired]))

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.CREATE
    assert change.target == "ruleset:protect release tags"
    change.apply()
    repo.requester.requestJsonAndCheck.assert_any_call(
        "POST",
        f"{URL}/rulesets",
        input=desired.to_api(),
    )


def test_matching_tag_ruleset_is_skipped() -> None:
    """A live tag ruleset matching the desired spec yields no change."""
    desired = ruleset(
        name="protect release tags",
        target="tag",
        conditions={"ref_name": {"include": ["v*"], "exclude": []}},
        rules=[{"type": "creation"}, {"type": "update"}, {"type": "deletion"}],
        bypass_actors=[{"actor_type": "Integration", "actor_id": 998885}],
    )
    current = {"id": 1, "source": "Repository", **desired.to_api()}
    repo = make_repo([{"id": 1, "name": "protect release tags"}], current)

    assert RulesetsManager().plan(repo, SharedConfig(rulesets=[desired])) == []


def test_github_error_propagates() -> None:
    """An API error while listing rulesets surfaces rather than being swallowed."""
    repo = MagicMock()
    repo.url = URL
    repo.requester.requestJsonAndCheck.side_effect = GithubException(403, {}, None)

    with pytest.raises(GithubException):
        RulesetsManager().plan(repo, SharedConfig(rulesets=[ruleset()]))


def test_resolver_resolves_app_slug() -> None:
    """An Integration slug resolves via the public /apps/{slug} endpoint."""
    repo = make_resolver_repo({"/apps/my-ci-app": {"id": 12345, "slug": "my-ci-app"}})
    assert _BypassActorResolver(repo)("Integration", "my-ci-app") == 12345


def test_resolver_resolves_team_slug() -> None:
    """A Team slug resolves via /orgs/{org}/teams/{slug}, scoped to the repo's org."""
    repo = make_resolver_repo({"/orgs/o/teams/platform": {"id": 99, "slug": "platform"}})
    assert _BypassActorResolver(repo)("Team", "platform") == 99


def test_resolver_resolves_custom_repository_role_by_name() -> None:
    """A RepositoryRole slug matches a custom role by name, case-insensitively."""
    repo = make_resolver_repo(
        {"/orgs/o/custom-repository-roles": {"custom_roles": [{"id": 7, "name": "Security"}]}}
    )
    assert _BypassActorResolver(repo)("RepositoryRole", "security") == 7


def test_resolver_unknown_role_raises_with_available_names() -> None:
    """A RepositoryRole slug that matches no custom role fails loudly, listing what exists."""
    repo = make_resolver_repo(
        {"/orgs/o/custom-repository-roles": {"custom_roles": [{"id": 7, "name": "Security"}]}}
    )
    with pytest.raises(ValueError, match=r"no custom repository role named 'writer'.*Security"):
        _BypassActorResolver(repo)("RepositoryRole", "writer")


def test_resolver_missing_app_raises_clear_error() -> None:
    """A 404 (unknown slug) becomes a clear ValueError, never a swallowed/dropped bypass."""
    repo = make_resolver_repo({})  # every path 404s
    with pytest.raises(ValueError, match="no GitHub App found for slug 'ghost'"):
        _BypassActorResolver(repo)("Integration", "ghost")


def test_resolver_fetches_custom_role_list_once_for_distinct_slugs() -> None:
    """Two distinct RepositoryRole slugs share a single custom-roles list request."""
    repo = make_resolver_repo(
        {
            "/orgs/o/custom-repository-roles": {
                "custom_roles": [{"id": 7, "name": "Security"}, {"id": 8, "name": "Release"}]
            }
        }
    )
    resolve = _BypassActorResolver(repo)
    assert resolve("RepositoryRole", "Security") == 7
    assert resolve("RepositoryRole", "Release") == 8
    assert repo.requester.requestJsonAndCheck.call_count == 1


def test_resolver_caches_repeated_lookups() -> None:
    """The same (actor_type, slug) is resolved once, then served from cache."""
    repo = make_resolver_repo({"/apps/app": {"id": 1}})
    resolve = _BypassActorResolver(repo)
    assert resolve("Integration", "app") == 1
    assert resolve("Integration", "app") == 1
    assert repo.requester.requestJsonAndCheck.call_count == 1


def test_resolver_non_404_error_propagates() -> None:
    """A non-404 API error is not masked as a resolution failure."""
    repo = MagicMock()
    repo.owner.login = "o"
    repo.requester.requestJsonAndCheck.side_effect = GithubException(500, {}, None)
    with pytest.raises(GithubException):
        _BypassActorResolver(repo)("Team", "platform")


def test_plan_resolves_bypass_actor_slug_into_body() -> None:
    """End-to-end: a desired ruleset's actor_slug is resolved into the created ruleset body."""
    desired = ruleset(bypass_actors=[{"actor_type": "Integration", "actor_slug": "my-ci-app"}])
    repo = make_repo([])  # no existing rulesets -> a CREATE
    repo.owner.login = "o"
    routes = {"/apps/my-ci-app": {"id": 456}}

    def request(verb: str, url: str, **_kwargs: object) -> tuple[dict, Any]:
        if verb == "GET" and url in routes:
            return ({}, routes[url])
        if verb == "GET" and url.split("?", maxsplit=1)[0] == f"{URL}/rulesets":
            return ({}, [])
        return ({}, {})

    repo.requester.requestJsonAndCheck.side_effect = request

    changes = RulesetsManager().plan(repo, SharedConfig(rulesets=[desired]))
    changes[0].apply()

    posted = next(
        call.kwargs["input"]
        for call in repo.requester.requestJsonAndCheck.call_args_list
        if call.args[0] == "POST"
    )
    assert posted["bypass_actors"] == [
        {"actor_type": "Integration", "bypass_mode": "always", "actor_id": 456}
    ]


def test_satisfied_branches() -> None:
    """The matcher: dicts by subset, lists by exact (length-equal) order-insensitive match."""
    assert _satisfied({"a": 1}, {"a": 1, "b": 2}) is True  # extra current dict keys ignored
    assert _satisfied({"a": 1}, {"b": 2}) is False  # missing key
    assert _satisfied({"a": 1}, "not-a-dict") is False  # dict vs scalar
    assert _satisfied([1, 2], [2, 1]) is True  # order-insensitive, same length
    assert _satisfied([1, 2], [2, 1, 3]) is False  # extra live item is drift
    assert _satisfied([1, 2], [1]) is False  # missing item
    assert _satisfied([1], "not-a-list") is False  # list vs scalar
    assert _satisfied("x", "y") is False  # scalar inequality
