# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the thin GraphQL client."""

from __future__ import annotations

from unittest.mock import MagicMock

from repo_management.graphql import GraphQLClient


def test_query_returns_data_payload() -> None:
    """The client unwraps the response's `data` object and passes variables through."""
    github = MagicMock()
    github.requester.graphql_query.return_value = ({"h": "1"}, {"data": {"viewer": {"login": "x"}}})

    client = GraphQLClient(github)
    result = client.query("query($n:Int!){ viewer{ login } }", n=1)

    assert result == {"viewer": {"login": "x"}}
    github.requester.graphql_query.assert_called_once_with(
        "query($n:Int!){ viewer{ login } }", {"n": 1}
    )
