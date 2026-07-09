# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""A thin GraphQL client for the GitHub endpoints PyGithub doesn't model.

PyGithub models the REST API only; GitHub **Projects v2** is GraphQL-only, so
:class:`~repo_management.managers.projects.ProjectsManager` and the roadmap automations
(``projects status`` / ``insights`` / ``reconcile``) drive it through GraphQL instead. This
wraps the authenticated requester PyGithub already holds — the same auth as every REST
manager, so there's no second token path and no ``gh`` subprocess dependency at runtime.

``PyGithub``'s ``Requester.graphql_query`` returns ``(response_headers, full_response)`` and
raises :class:`github.GithubException` when the response carries ``errors``; this exposes
just the ``data`` payload, letting callers write queries/mutations and read results directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from github import Github


class GraphQL(Protocol):
    """The GraphQL capability :class:`ProjectsManager` and the automations depend on.

    Depending on this structural type rather than the concrete :class:`GraphQLClient` keeps
    the board logic testable with a fake and documents that it needs only ``query``.
    """

    def query(self, document: str, /, **variables: object) -> dict[str, Any]:
        """Execute a GraphQL document and return its ``data`` payload."""
        ...


class GraphQLClient:
    """Issue GraphQL queries and mutations through an authenticated PyGithub client."""

    def __init__(self, github: Github) -> None:
        """Wrap an authenticated PyGithub client's GraphQL-capable requester."""
        self._requester = github.requester

    def query(self, document: str, /, **variables: object) -> dict[str, Any]:
        """Execute a GraphQL query or mutation and return its ``data`` payload.

        Args:
            document: The GraphQL query or mutation document.
            **variables: Values for the document's declared variables.

        Returns:
            The ``data`` object of the response (the mapping under the top-level ``data`` key).

        Raises:
            github.GithubException: If the response carries GraphQL ``errors`` (raised by the
                underlying requester, so a failed mutation never looks like a silent no-op).
        """
        _, response = self._requester.graphql_query(document, variables)
        return response["data"]
