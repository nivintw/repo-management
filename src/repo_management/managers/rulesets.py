# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for repository rulesets.

PyGithub has no ruleset support, so this manager drives the REST API directly through the
authenticated requester. Rulesets are matched against existing ones by ``name``. The list
endpoint omits rules/conditions, so each candidate match is fetched in full before diffing.

A declared ``rulesets`` section is authoritative: rulesets are created and updated to match
the config, and repo-level rulesets absent from the config are deleted. Listing passes
``includes_parents=false`` so inherited org/enterprise rulesets are never matched or
deleted through the repo.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from github import GithubException

from repo_management.changes import Action, Change

if TYPE_CHECKING:
    from github.Repository import Repository

    from repo_management.config import SharedConfig

# GitHub's list-rulesets page cap; requesting the max minimizes round-trips.
_PER_PAGE = 100


class RulesetsManager:
    """Create and update repository rulesets, matched by name."""

    domain = "rulesets"

    def plan(self, repo: Repository, desired: SharedConfig) -> list[Change]:
        """Return changes to create, update, and delete rulesets to match the config."""
        if desired.rulesets is None:
            return []

        existing = {item["name"]: item["id"] for item in self._list(repo)}
        resolve_slug = _BypassActorResolver(repo)
        changes: list[Change] = []
        for ruleset in desired.rulesets:
            body = ruleset.to_api(resolve_slug)
            ruleset_id = existing.get(ruleset.name)
            if ruleset_id is None:
                changes.append(self._create(repo, ruleset.name, body))
            else:
                current = self._get(repo, ruleset_id)
                if not _matches(body, current):
                    changes.append(self._update(repo, ruleset_id, ruleset.name, body, current))

        wanted = {ruleset.name for ruleset in desired.rulesets}
        changes.extend(
            self._delete(repo, ruleset_id, name)
            for name, ruleset_id in existing.items()
            if name not in wanted
        )
        return changes

    def _list(self, repo: Repository) -> list[dict[str, Any]]:
        # includes_parents=false: manage only this repo's own rulesets, not ones inherited
        # from the org/enterprise (which can't be edited or deleted through the repo).
        # Paginate: the endpoint caps a page at 100 (defaults to 30), so a repo owning more
        # than a page of rulesets would otherwise silently drop the overflow from the diff.
        rulesets: list[dict[str, Any]] = []
        page = 1
        while True:
            _, data = repo.requester.requestJsonAndCheck(
                "GET",
                f"{repo.url}/rulesets?includes_parents=false&per_page={_PER_PAGE}&page={page}",
            )
            if not data:
                break
            rulesets.extend(data)
            if len(data) < _PER_PAGE:
                break
            page += 1
        return rulesets

    def _get(self, repo: Repository, ruleset_id: int) -> dict[str, Any]:
        _, data = repo.requester.requestJsonAndCheck("GET", f"{repo.url}/rulesets/{ruleset_id}")
        return data

    def _create(self, repo: Repository, name: str, body: dict[str, Any]) -> Change:
        def apply() -> None:
            repo.requester.requestJsonAndCheck("POST", f"{repo.url}/rulesets", input=body)

        return Change(
            domain=self.domain,
            action=Action.CREATE,
            target=f"ruleset:{name}",
            before=None,
            after=_summary(body),
            apply=apply,
        )

    def _update(
        self,
        repo: Repository,
        ruleset_id: int,
        name: str,
        body: dict[str, Any],
        current: dict[str, Any],
    ) -> Change:
        url = f"{repo.url}/rulesets/{ruleset_id}"

        def apply() -> None:
            repo.requester.requestJsonAndCheck("PUT", url, input=body)

        return Change(
            domain=self.domain,
            action=Action.UPDATE,
            target=f"ruleset:{name}",
            before=_summary(current),
            after=_summary(body),
            apply=apply,
        )

    def _delete(self, repo: Repository, ruleset_id: int, name: str) -> Change:
        url = f"{repo.url}/rulesets/{ruleset_id}"

        def apply() -> None:
            repo.requester.requestJsonAndCheck("DELETE", url)

        return Change(
            domain=self.domain,
            action=Action.DELETE,
            target=f"ruleset:{name}",
            before=f"ruleset:{name}",
            after=None,
            apply=apply,
        )


class _BypassActorResolver:
    """Resolve a bypass actor's ``actor_slug`` to the numeric ``actor_id`` GitHub expects.

    Humans configure bypass actors by a name they know — an App slug, a team slug, a custom
    repository-role name — never the opaque numeric id GitHub stores. This looks that id up via
    the API at plan time. Results are cached per ``(actor_type, slug)`` so a slug repeated across
    rulesets costs a single request, and the org's custom-role list is fetched at most once no
    matter how many role slugs a plan references. A slug that doesn't resolve raises loudly
    rather than silently dropping the bypass entry.
    """

    def __init__(self, repo: Repository) -> None:
        self._repo = repo
        self._cache: dict[tuple[str, str], int] = {}
        # The org's custom repository roles (name -> id), fetched lazily and memoized: one list
        # request answers every RepositoryRole slug in a plan.
        self._custom_roles: dict[str, int] | None = None

    def __call__(self, actor_type: str, slug: str) -> int:
        key = (actor_type, slug)
        if key not in self._cache:
            self._cache[key] = self._resolve(actor_type, slug)
        return self._cache[key]

    def _resolve(self, actor_type: str, slug: str) -> int:
        if actor_type == "Integration":
            # Public App metadata; the slug is the one in the App's public URL.
            return self._lookup_id(
                f"/apps/{_seg(slug)}", missing=f"no GitHub App found for slug {slug!r}"
            )
        if actor_type == "Team":
            return self._lookup_id(
                f"/orgs/{_seg(self._org)}/teams/{_seg(slug)}",
                missing=f"no team {slug!r} in organization {self._org!r}",
            )
        if actor_type == "RepositoryRole":
            return self._role_id(slug)
        # Only the id-requiring types reach here (BypassActor validation forbids a slug on
        # OrganizationAdmin/DeployKey), so an unknown type is a programming error, not user input.
        msg = f"bypass actor_type {actor_type!r} does not support slug resolution"
        raise ValueError(msg)

    @property
    def _org(self) -> str:
        return self._repo.owner.login

    def _lookup_id(self, path: str, *, missing: str) -> int:
        """GET a single object by its slug endpoint and return its numeric ``id``."""
        return _require_id(self._get(path, missing=missing), context=path)

    def _role_id(self, slug: str) -> int:
        # Only custom repository roles are addressable by name via the API; GitHub's built-in
        # base roles (read/triage/write/maintain/admin) have no name→id endpoint, so those must
        # still be given as a literal actor_id.
        if self._custom_roles is None:
            data = self._get(
                f"/orgs/{_seg(self._org)}/custom-repository-roles",
                missing=f"cannot list custom repository roles for organization {self._org!r}",
            )
            if "custom_roles" not in data:
                # An absent key is a shape problem, not "the org has zero roles" — don't let it
                # masquerade as a "role not found" that tells the operator to delete good config.
                msg = (
                    f"unexpected custom-repository-roles response for organization "
                    f"{self._org!r}: missing 'custom_roles'"
                )
                raise ValueError(msg)
            self._custom_roles = {
                _require_name(role): _require_id(role, context="custom role")
                for role in data["custom_roles"]
            }
        # Match case-insensitively, but a slug matching more than one role by case is ambiguous —
        # binding a bypass grant to an arbitrary one silently would defeat the point of the guard.
        wanted = slug.lower()
        matches = [
            role_id for name, role_id in self._custom_roles.items() if name.lower() == wanted
        ]
        if len(matches) > 1:
            msg = (
                f"custom repository role slug {slug!r} is ambiguous in organization "
                f"{self._org!r} — more than one role matches case-insensitively"
            )
            raise ValueError(msg)
        if matches:
            return matches[0]
        msg = (
            f"no custom repository role named {slug!r} in organization {self._org!r} "
            f"(found: {sorted(self._custom_roles)}). "
            "Built-in base roles have no slug — use a numeric actor_id."
        )
        raise ValueError(msg)

    def _get(self, path: str, *, missing: str) -> dict[str, Any]:
        try:
            _, data = self._repo.requester.requestJsonAndCheck("GET", path)
        except GithubException as exc:
            if exc.status == HTTPStatus.NOT_FOUND:
                raise ValueError(missing) from exc
            raise
        return data


def _seg(value: str) -> str:
    """URL-encode a single path segment so a slug can't inject extra path or query structure.

    ``quote(..., safe="")`` percent-encodes ``/``, ``?``, ``#`` and the like — a defensive layer
    on top of BypassActor's slug validation, since these values interpolate straight into a REST
    path. The host is never derived from a slug, so this is about path integrity, not SSRF.
    """
    return quote(value, safe="")


def _require_id(data: dict[str, Any], *, context: str) -> int:
    """Return the integer ``id`` from an API object, or raise if it's absent or non-numeric.

    A resolved bypass actor with no usable id is a hard error, not something to paper over with a
    default that would silently drop the bypass grant.
    """
    raw = data.get("id")
    if raw is None:
        msg = f"expected an 'id' in the {context} response, got none"
        raise ValueError(msg)
    return int(raw)


def _require_name(role: dict[str, Any]) -> str:
    """Return a custom role's ``name``, or raise if it's missing — the key we index roles by."""
    name = role.get("name")
    if name is None:
        msg = "custom repository role is missing its 'name'"
        raise ValueError(msg)
    return name


def _summary(api: dict[str, Any]) -> dict[str, Any]:
    """A concise, readable view of a ruleset for plan output."""
    rules = api.get("rules") or []
    return {
        "target": api.get("target"),
        "enforcement": api.get("enforcement"),
        "rules": sorted(rule["type"] for rule in rules),
    }


_UNMATCHED = object()


def _matches(desired: dict[str, Any], current: dict[str, Any]) -> bool:
    """Whether the live ruleset already matches the desired spec.

    A declared ruleset is authoritative, so its declared *lists* (rules, bypass actors,
    ref-name patterns) must match the live ones exactly — an extra or missing item is drift
    that triggers an update. *Dict* fields are matched as a subset, ignoring keys the spec
    never sets (server-supplied metadata like ``integration_id``, timestamps, and node ids),
    which we can't control and which would otherwise cause perpetual churn. Lists are compared
    order-insensitively.

    ``actor_id`` is subset-matched like any other key, so it cuts both ways: an actor the spec
    pins by id (literally, or resolved from an ``actor_slug`` before this compares) must match
    the live actor's id, while an actor that sets no id (``OrganizationAdmin``) ignores whatever
    id the server attached — which is exactly why a slug resolving to the live id is a NOOP.
    """
    return _satisfied(desired, current)


def _satisfied(desired: object, current: object) -> bool:
    """Whether ``current`` matches ``desired``: dicts by subset, lists exactly."""
    if isinstance(desired, dict):
        if not isinstance(current, dict):
            return False
        current_map: dict[Any, Any] = current
        return all(
            key in current_map and _satisfied(value, current_map[key])
            for key, value in desired.items()
        )
    if isinstance(desired, list):
        if not isinstance(current, list) or len(current) != len(desired):
            return False
        # Order-insensitive: pair each desired item with a distinct live item it matches.
        remaining: list[Any] = list(current)
        for item in desired:
            match = next((c for c in remaining if _satisfied(item, c)), _UNMATCHED)
            if match is _UNMATCHED:
                return False
            remaining.remove(match)
        return True
    return desired == current
