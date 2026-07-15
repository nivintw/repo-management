# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for a GitHub Projects v2 board — the board itself, and its custom-field schema.

Projects v2 is GraphQL-only (PyGithub models the REST API only), so this manager drives it
through :class:`~repo_management.graphql.GraphQLClient` rather than a ``Repository``. It also
sits *outside* the per-repo reconciler: a board is a single owner-level entity, so the
``projects`` CLI commands call :meth:`plan` directly with a :class:`ProjectsConfig` instead
of the per-repo loop handing it a repository.

Scope is the board's **schema** — its custom fields and, for single-selects, their options.
A field declared in config is created if absent; a single-select's options are reconciled to
match (create / recolor / reorder / remove). A field already present with a *different* data
type can't be reconciled at all — GitHub exposes no field-type mutation — so it becomes an
unresolved-value **diagnostic** that blocks the run, rather than something skipped with a
warning while the CLI goes on to report "in sync" over a board that never converged. Board
membership and per-item field values are deliberately not managed here (see
``docs/projects.md``) — they belong to planning/automation tooling.

A ``title``-addressed board that doesn't exist yet is **created**, then its schema reconciled;
a ``number``-addressed one is only ever adopted (see
:class:`~repo_management.config.ProjectsConfig`).
Creation is one :class:`~repo_management.changes.Change` whose ``apply``
both creates the board and reconciles its fields, because the field mutations need a
``projectId`` that doesn't exist until the board does — the same create-then-populate shape
:class:`~repo_management.managers.environments.EnvironmentsManager` uses. That closure
re-reads the new board rather than blind-creating every declared field: GitHub seeds a fresh
board with its own ``Status`` single-select, so declaring ``Status`` must *reconcile* the
built-in one instead of colliding with it.

The built-in ``Status`` field is an ordinary single-select, so declaring a ``Status`` field
in config reconciles its options like any other — that's how the roadmap board carries one
status field (Todo / Ready / In Progress / In Review / Blocked / Done) instead of a built-in
field plus a drift-prone custom one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from github import GithubException

from repo_management.changes import Action, Change
from repo_management.config import ConfigError

if TYPE_CHECKING:
    from repo_management.config import ProjectField, ProjectsConfig
    from repo_management.graphql import GraphQL

# config data_type -> GraphQL ProjectV2CustomFieldType (create) / ProjectV2FieldType (read).
_FIELD_TYPE = {
    "single_select": "SINGLE_SELECT",
    "date": "DATE",
    "text": "TEXT",
    "number": "NUMBER",
}

_PROJECT_QUERY = """
query($owner:String!, $number:Int!){
  %(root)s(login:$owner){
    projectV2(number:$number){
      id
      fields(first:50){
        nodes{
          __typename
          ... on ProjectV2FieldCommon { id name dataType }
          ... on ProjectV2SingleSelectField {
            id name
            options{ id name color description }
          }
        }
      }
    }
  }
}
"""

_CREATE_FIELD = """
mutation($input: CreateProjectV2FieldInput!){
  createProjectV2Field(input:$input){
    projectV2Field{ ... on ProjectV2FieldCommon { id name } }
  }
}
"""

_UPDATE_FIELD = """
mutation($input: UpdateProjectV2FieldInput!){
  updateProjectV2Field(input:$input){
    projectV2Field{ ... on ProjectV2FieldCommon { id name } }
  }
}
"""

# `closed` is selected so a title lookup can ignore closed boards. Neither `user.projectsV2`
# nor `organization.projectsV2` takes a `filterBy` argument (only `query`, whose search
# semantics are fuzzy), so the filter is applied client-side against this field.
_LIST_PROJECTS_QUERY = """
query($owner:String!, $cursor:String){
  %(root)s(login:$owner){
    projectsV2(first:100, after:$cursor){
      nodes{ number title closed }
      pageInfo{ hasNextPage endCursor }
    }
  }
}
"""

_OWNER_ID_QUERY = """
query($owner:String!){
  %(root)s(login:$owner){ id }
}
"""

_CREATE_PROJECT = """
mutation($input: CreateProjectV2Input!){
  createProjectV2(input:$input){
    projectV2{ id number title }
  }
}
"""

_ACCESS_HINT = (
    "check owner/owner_type and that the token has Projects access (a user-owned board needs "
    "a classic PAT with the 'project' scope; a fine-grained PAT's Projects permission covers "
    "org-owned boards only)"
)


def _field_summary(field: ProjectField) -> dict[str, Any]:
    """A field's desired state for display in a plan: its type, plus any option names."""
    summary: dict[str, Any] = {"data_type": field.data_type}
    if field.options is not None:
        summary["options"] = [option.name for option in field.options]
    return summary


def _query_owner(
    gql: GraphQL, config: ProjectsConfig, document: str, /, **variables: object
) -> dict[str, Any]:
    """Run an owner-rooted query and return the owner node — ``{}`` when it isn't readable.

    Every board query hangs off ``user(login:)`` or ``organization(login:)``, so this owns the
    three steps each of them would otherwise repeat: pick the root from ``owner_type``, render
    it into the document, and null-guard the owner before a caller reaches into it.
    """
    root = "user" if config.owner_type == "user" else "organization"
    data = gql.query(document % {"root": root}, owner=config.owner, **variables)
    return data.get(root) or {}


def resolve_number(gql: GraphQL, config: ProjectsConfig) -> int | None:
    """Return the board's number, or ``None`` when a ``title``-addressed board doesn't exist.

    A ``number``-addressed config resolves to itself without a lookup — the number *is* the
    address, and whether it names a live board is :func:`query_project`'s to discover. A
    ``title``-addressed one is searched for among the owner's **open** boards by exact title.

    Closed boards are invisible to that search, deliberately: adopting one would reconcile
    fields onto — and post status updates to — a board nobody is using, and an abandoned
    same-titled board would otherwise deadlock the config on ``AmbiguousProjectError``
    forever. A closed board can still be managed by addressing it with ``number``, which
    does no lookup at all.

    Raises:
        AmbiguousProjectError: If more than one open board carries the declared title — the
            config names two boards, so picking one would silently manage the wrong board.
        ProjectNotFoundError: If the owner's boards can't be listed at all.
    """
    if config.number is not None:
        return config.number

    matches: list[int] = []
    cursor: str | None = None
    while True:
        owner = _query_owner(gql, config, _LIST_PROJECTS_QUERY, cursor=cursor)
        connection = owner.get("projectsV2")
        if connection is None:
            msg = f"can't list Projects v2 boards for {config.owner!r} — {_ACCESS_HINT}"
            raise ProjectNotFoundError(msg)
        matches.extend(
            node["number"]
            for node in connection["nodes"]
            if node and not node["closed"] and node["title"] == config.title
        )
        page = connection["pageInfo"]
        if not page["hasNextPage"]:
            break
        cursor = page["endCursor"]

    if len(matches) > 1:
        listed = ", ".join(f"#{number}" for number in sorted(matches))
        msg = (
            f"{config.owner} has {len(matches)} Projects v2 boards titled {config.title!r} "
            f"({listed}) — address the intended one by 'number' instead of 'title'"
        )
        raise AmbiguousProjectError(msg)
    return matches[0] if matches else None


def require_number(gql: GraphQL, config: ProjectsConfig) -> int:
    """The board's number, for callers that can only read an existing board.

    Raises:
        ProjectNotFoundError: If a ``title``-addressed board doesn't exist. Only
            ``projects apply`` creates a board; every other caller reads one.
        AmbiguousProjectError: Propagated from :func:`resolve_number` when several open
            boards share the declared title.
    """
    number = resolve_number(gql, config)
    if number is None:
        msg = (
            f"Projects v2 board {config.label} not found — create it with 'projects apply', "
            "or address an existing board by 'number'"
        )
        raise ProjectNotFoundError(msg)
    return number


def query_project(
    gql: GraphQL, config: ProjectsConfig, query: str, number: int, /, **variables: object
) -> dict[str, Any]:
    """Run a projectV2 query against an already-resolved board number and return its node.

    Purely an executor: ``number`` is required precisely so resolving stays the caller's
    explicit step. Letting this resolve a missing one invites a caller to re-run the title
    lookup where it already knows the answer — once per page of a pagination loop, or right
    after a create that just returned the number.

    Raises:
        ProjectNotFoundError: If the board can't be read (bad coordinates, or a token without
            the ``project`` scope).
    """
    project = _query_owner(gql, config, query, number=number, **variables).get("projectV2")
    if project is None:
        # Name `number` in the hint: this message's likeliest cause is a wrong number in a
        # number-addressed config, which the shared owner-level hint doesn't mention.
        msg = (
            f"Projects v2 board {config.owner}/#{number} not found — check the number, and "
            f"{_ACCESS_HINT}"
        )
        raise ProjectNotFoundError(msg)
    return project


class ProjectsManager:
    """Reconcile a Projects v2 board's custom fields and single-select options."""

    domain = "projects"

    def __init__(self, gql: GraphQL) -> None:
        """Build the manager on a GraphQL client scoped to the target board's owner."""
        self._gql = gql
        # The board number the last plan() resolved — None when a title-addressed board
        # doesn't exist yet. Read by the CLI so a plan can name the board it resolved to.
        self.number: int | None = None

    def plan(self, desired: ProjectsConfig) -> list[Change]:
        """Return the changes needed to bring the board into desired state.

        A ``title``-addressed board that doesn't exist yet plans as a single create; anything
        else plans per-field against the live board.
        """
        self.number = resolve_number(self._gql, desired)
        if self.number is None:
            return [self._create_board(desired)]
        return self._field_changes(self._fetch(desired, self.number), desired)

    def _field_changes(self, project: dict[str, Any], desired: ProjectsConfig) -> list[Change]:
        changes: list[Change] = []
        for field in desired.fields:
            current = project["fields"].get(field.name)
            if current is None:
                changes.append(self._create(project["id"], field))
            elif current["data_type"] != _FIELD_TYPE[field.data_type]:
                # A diagnostic, not a warning: GitHub has no field-type mutation, so this is a
                # declared value that can't be resolved — exactly what `!` lines are for. A
                # warning let `plan` go on to report "in sync" and `apply` to exit 0 over a
                # board that never reached desired state, which is the lie worth failing on.
                changes.append(
                    Change.diagnostic(
                        self.domain,
                        f"field:{field.name}",
                        f"exists as {current['data_type']} but config declares "
                        f"{_FIELD_TYPE[field.data_type]}; GitHub has no field-type mutation, "
                        "so rename or recreate the field by hand",
                    )
                )
            elif field.data_type == "single_select":
                change = self._reconcile_options(current, field)
                if change is not None:
                    changes.append(change)
        return changes

    def _create_board(self, desired: ProjectsConfig) -> Change:
        def apply() -> None:
            # Re-resolve before creating. The plan's "absent" is arbitrarily stale by the time
            # a human answers the confirm prompt, and GitHub does not enforce unique titles —
            # so a board that appeared in that window would get a duplicate, and two boards
            # sharing a title wedge *every* later run on AmbiguousProjectError. Adopt instead.
            number = resolve_number(self._gql, desired)
            if number is None:
                number = self._create_and_number(desired)
            # Re-read rather than create every declared field blind: GitHub seeds a new board
            # with its own Status single-select, so a declared Status must reconcile that one.
            # Address it by the number just resolved or returned — re-resolving by title here
            # would re-list every board the owner has to learn what we were just told.
            for change in self._field_changes(self._fetch(desired, number), desired):
                # A field GitHub seeds with an incompatible type (Labels, Assignees, …) only
                # becomes visible once the board exists, so this diagnostic can't surface at
                # plan time. A diagnostic's own apply() raises RuntimeError, which the CLI
                # doesn't map to a clean exit — surface it as ConfigError, as environments does.
                if change.unresolved:
                    msg = change.error or "unresolved field"
                    raise ConfigError(msg)
                try:
                    change.apply()
                except GithubException as exc:
                    # This closure is N+1 writes under one board-level target, so without
                    # this the CLI would report a failed *field* write as the board create
                    # failing — and never say the board now exists.
                    msg = (
                        f"created board #{number}, but applying {change.target} failed: "
                        f"{exc.data or exc} (re-run to finish reconciling it)"
                    )
                    raise ProjectSchemaError(msg) from exc

        return Change(
            domain=self.domain,
            action=Action.CREATE,
            target=f"board:{desired.title}",
            before=None,
            # Spell out every field the apply will write. A create folds the whole field
            # reconcile into this one Change, so its payload is the only preview a plan can
            # show — listing bare field names would undersell what an apply actually does.
            after={
                "owner": desired.owner,
                "title": desired.title,
                "fields": {field.name: _field_summary(field) for field in desired.fields},
            },
            apply=apply,
        )

    def _create_and_number(self, desired: ProjectsConfig) -> int:
        """Create the declared board and return the number GitHub assigned it."""
        owner = _query_owner(self._gql, desired, _OWNER_ID_QUERY)
        if not owner.get("id"):
            msg = f"can't resolve {desired.owner_type} {desired.owner!r} — {_ACCESS_HINT}"
            raise ProjectNotFoundError(msg)
        created = self._gql.query(
            _CREATE_PROJECT, input={"ownerId": owner["id"], "title": desired.title}
        )["createProjectV2"]["projectV2"]
        # Every later run finds this board by matching `title` exactly. If GitHub stored
        # something else, that lookup can never match and each run would create yet another
        # board — so fail here rather than silently building a pile of duplicates.
        if created["title"] != desired.title:
            msg = (
                f"created board #{created['number']} but GitHub stored its title as "
                f"{created['title']!r}, not the declared {desired.title!r} — a later run "
                "could not find it by title; rename it in GitHub or address it by 'number'"
            )
            raise ProjectSchemaError(msg)
        return int(created["number"])

    def _fetch(self, desired: ProjectsConfig, number: int) -> dict[str, Any]:
        project = query_project(self._gql, desired, _PROJECT_QUERY, number)
        fields: dict[str, dict[str, Any]] = {}
        for node in project["fields"]["nodes"]:
            if not node:  # non-field union members serialize as {}
                continue
            fields[node["name"]] = {
                "id": node["id"],
                "data_type": node["dataType"],
                "options": node.get("options"),
            }
        return {"id": project["id"], "fields": fields}

    def _create(self, project_id: str, field: ProjectField) -> Change:
        field_input: dict[str, Any] = {
            "projectId": project_id,
            "dataType": _FIELD_TYPE[field.data_type],
            "name": field.name,
        }
        if field.data_type == "single_select":
            assert field.options is not None  # noqa: S101 — guaranteed by ProjectField validator
            field_input["singleSelectOptions"] = [
                {"name": o.name, "color": o.color, "description": o.description}
                for o in field.options
            ]

        def apply() -> None:
            self._gql.query(_CREATE_FIELD, input=field_input)

        return Change(
            domain=self.domain,
            action=Action.CREATE,
            target=f"field:{field.name}",
            before=None,
            after=_field_summary(field),
            apply=apply,
        )

    def _reconcile_options(self, current: dict[str, Any], field: ProjectField) -> Change | None:
        assert field.options is not None  # noqa: S101 — guaranteed by ProjectField validator
        current_options = current["options"] or []
        by_name = {option["name"]: option for option in current_options}

        # Match desired options to live ones by name so a kept option keeps its id (and the
        # items assigned to it); an unmatched desired option is created; a live option with
        # no desired counterpart is dropped from the payload, which removes it.
        payload: list[dict[str, Any]] = []
        for option in field.options:
            entry = {"name": option.name, "color": option.color, "description": option.description}
            existing = by_name.get(option.name)
            if existing is not None:
                entry["id"] = existing["id"]
            payload.append(entry)

        desired_view = [
            {"name": e["name"], "color": e["color"], "description": e["description"]}
            for e in payload
        ]
        current_view = [
            {"name": o["name"], "color": o["color"], "description": o.get("description") or ""}
            for o in current_options
        ]
        if desired_view == current_view:
            return None

        desired_names = {option.name for option in field.options}
        removed = [
            option["name"] for option in current_options if option["name"] not in desired_names
        ]
        field_id = current["id"]

        def apply() -> None:
            self._gql.query(
                _UPDATE_FIELD, input={"fieldId": field_id, "singleSelectOptions": payload}
            )

        # Name the target so a removal (which drops the option from every item that had it)
        # is loud in the plan the CLI prints before it prompts to apply.
        target = f"field:{field.name}:options"
        if removed:
            target += f" (removes {', '.join(removed)})"
        return Change(
            domain=self.domain,
            action=Action.UPDATE,
            target=target,
            before=[option["name"] for option in current_options],
            after=[option.name for option in field.options],
            apply=apply,
        )


class ProjectError(Exception):
    """Base for the ways a configured Projects v2 board fails to resolve to exactly one board."""


class ProjectNotFoundError(ProjectError):
    """Raised when the configured Projects v2 board can't be read."""


class AmbiguousProjectError(ProjectError):
    """Raised when a ``title``-addressed config matches more than one board."""


class ProjectSchemaError(ProjectError):
    """Raised when a created board can't be addressed by the title that was declared for it."""
