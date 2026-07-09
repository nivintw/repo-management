# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Manager for a GitHub Projects v2 board's custom-field schema.

Projects v2 is GraphQL-only (PyGithub models the REST API only), so this manager drives it
through :class:`~repo_management.graphql.GraphQLClient` rather than a ``Repository``. It also
sits *outside* the per-repo reconciler: a board is a single owner-level entity, so the
``projects`` CLI commands call :meth:`plan` directly with a :class:`ProjectsConfig` instead
of the per-repo loop handing it a repository.

Scope is the board's **schema** — its custom fields and, for single-selects, their options.
A field declared in config is created if absent; a single-select's options are reconciled to
match (create / recolor / reorder / remove). A field already present with a *different* data
type is left alone with a warning, because GitHub exposes no field-type mutation. Board
membership and per-item field values are deliberately not managed here (see
``docs/config/projects.md``) — they belong to planning/automation tooling.

The built-in ``Status`` field is an ordinary single-select, so declaring a ``Status`` field
in config reconciles its options like any other — that's how the roadmap board carries one
status field (Todo / Ready / In progress / In review / Blocked / Done) instead of a built-in
field plus a drift-prone custom one.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

from repo_management.changes import Action, Change

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


def query_project(
    gql: GraphQL, config: ProjectsConfig, query: str, /, **variables: object
) -> dict[str, Any]:
    """Run a projectV2 query for the configured board and return its node.

    Resolves the query root from ``owner_type`` (``user`` vs ``organization``), always passes
    ``owner``/``number``, and forwards any extra ``variables`` (e.g. a pagination ``cursor``).
    Shared by the schema manager and the roadmap automations so the root selection and the
    not-found message live in one place.

    Raises:
        ProjectNotFoundError: If the board can't be read (bad coordinates, or a token without
            the ``project`` scope).
    """
    root = "user" if config.owner_type == "user" else "organization"
    data = gql.query(query % {"root": root}, owner=config.owner, number=config.number, **variables)
    project = (data.get(root) or {}).get("projectV2")
    if project is None:
        msg = (
            f"Projects v2 board {config.owner}/#{config.number} not found — check owner/number/"
            "owner_type and that the token has Projects access (a classic PAT's 'project' scope "
            "or a fine-grained PAT's 'Projects' permission)"
        )
        raise ProjectNotFoundError(msg)
    return project


class ProjectsManager:
    """Reconcile a Projects v2 board's custom fields and single-select options."""

    domain = "projects"

    def __init__(self, gql: GraphQL) -> None:
        """Build the manager on a GraphQL client scoped to the target board's owner."""
        self._gql = gql

    def plan(self, desired: ProjectsConfig) -> list[Change]:
        """Return the changes needed to bring the board's field schema into desired state."""
        project = self._fetch(desired)
        changes: list[Change] = []
        for field in desired.fields:
            current = project["fields"].get(field.name)
            if current is None:
                changes.append(self._create(project["id"], field))
            elif current["data_type"] != _FIELD_TYPE[field.data_type]:
                warnings.warn(
                    f"field {field.name!r} exists as {current['data_type']} but config "
                    f"declares {_FIELD_TYPE[field.data_type]}; GitHub has no field-type "
                    "mutation, so this field is left unmanaged (rename or recreate by hand)",
                    stacklevel=2,
                )
            elif field.data_type == "single_select":
                change = self._reconcile_options(current, field)
                if change is not None:
                    changes.append(change)
        return changes

    def _fetch(self, desired: ProjectsConfig) -> dict[str, Any]:
        project = query_project(self._gql, desired, _PROJECT_QUERY)
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
        after: dict[str, Any] = {"data_type": field.data_type}
        if field.data_type == "single_select":
            assert field.options is not None  # noqa: S101 — guaranteed by ProjectField validator
            field_input["singleSelectOptions"] = [
                {"name": o.name, "color": o.color, "description": o.description}
                for o in field.options
            ]
            after["options"] = [o.name for o in field.options]

        def apply() -> None:
            self._gql.query(_CREATE_FIELD, input=field_input)

        return Change(
            domain=self.domain,
            action=Action.CREATE,
            target=f"field:{field.name}",
            before=None,
            after=after,
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


class ProjectNotFoundError(Exception):
    """Raised when the configured Projects v2 board can't be read."""
