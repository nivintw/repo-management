# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the GitHub Pages manager."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from github import GithubException

from repo_management.changes import Action
from repo_management.config import Pages, PagesSource, SharedConfig
from repo_management.managers.pages import PagesManager

URL = "https://api.github.com/repos/o/r"


def _not_found(verb: str, _url: str, **_kwargs: object) -> tuple[dict, dict]:
    """GET 404s (Pages absent); any write (POST/PUT/DELETE) succeeds, mirroring GitHub."""
    if verb == "GET":
        raise GithubException(404, {"message": "Not Found"})
    return ({}, {})


def test_no_pages_is_noop(repo: MagicMock) -> None:
    """A repo config without a pages section yields no changes."""
    assert PagesManager().plan(repo, SharedConfig()) == []
    repo.requester.requestJsonAndCheck.assert_not_called()


def test_disabled_and_absent_is_noop(repo: MagicMock) -> None:
    """enabled: false with Pages already off (404) produces no change."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.side_effect = _not_found
    desired = SharedConfig(pages=Pages(enabled=False))
    assert PagesManager().plan(repo, desired) == []


def test_absent_and_enabled_creates(repo: MagicMock) -> None:
    """Pages absent (404) and enabled: true yields a CREATE with build_type + source."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.side_effect = _not_found
    desired = SharedConfig(
        pages=Pages(build_type="legacy", source=PagesSource(branch="main", path="/docs"))
    )

    changes = PagesManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.CREATE
    assert change.target == "pages"
    assert change.after == {"build_type": "legacy", "source": {"branch": "main", "path": "/docs"}}
    change.apply()
    repo.requester.requestJsonAndCheck.assert_any_call(
        "POST",
        f"{URL}/pages",
        input={"build_type": "legacy", "source": {"branch": "main", "path": "/docs"}},
    )


def test_create_with_cname_follows_up_with_put(repo: MagicMock) -> None:
    """Creating with cname/https_enforced set POSTs then immediately PUTs those fields."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.side_effect = _not_found
    desired = SharedConfig(
        pages=Pages(build_type="workflow", cname="example.com", https_enforced=True)
    )

    changes = PagesManager().plan(repo, desired)

    assert len(changes) == 1
    changes[0].apply()
    calls = repo.requester.requestJsonAndCheck.call_args_list
    post_calls = [c for c in calls if c.args[0] == "POST"]
    put_calls = [c for c in calls if c.args[0] == "PUT"]
    assert post_calls[0].kwargs["input"] == {"build_type": "workflow"}
    assert put_calls[0].kwargs["input"] == {"cname": "example.com", "https_enforced": True}


def test_existing_matching_is_noop(repo: MagicMock) -> None:
    """A live Pages config that already matches produces no change."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = (
        {},
        {"build_type": "workflow", "source": None, "cname": None, "https_enforced": True},
    )
    desired = SharedConfig(pages=Pages(build_type="workflow", https_enforced=True))
    assert PagesManager().plan(repo, desired) == []


def test_existing_differing_updates(repo: MagicMock) -> None:
    """A live Pages config that differs yields an UPDATE with a single PUT."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = (
        {},
        {"build_type": "legacy", "source": {"branch": "main", "path": "/"}, "cname": None},
    )
    desired = SharedConfig(
        pages=Pages(build_type="legacy", source=PagesSource(branch="gh-pages", path="/"))
    )

    changes = PagesManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.UPDATE
    assert change.before == {"build_type": "legacy", "source": {"branch": "main", "path": "/"}}
    assert change.after == {"build_type": "legacy", "source": {"branch": "gh-pages", "path": "/"}}
    change.apply()
    repo.requester.requestJsonAndCheck.assert_called_with(
        "PUT",
        f"{URL}/pages",
        input={"build_type": "legacy", "source": {"branch": "gh-pages", "path": "/"}},
    )


def test_enabled_false_disables_existing(repo: MagicMock) -> None:
    """enabled: false with Pages currently on yields a DELETE."""
    repo.url = URL
    repo.requester.requestJsonAndCheck.return_value = (
        {},
        {"build_type": "workflow", "source": None, "cname": None, "https_enforced": None},
    )
    desired = SharedConfig(pages=Pages(enabled=False))

    changes = PagesManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.DELETE
    change.apply()
    repo.requester.requestJsonAndCheck.assert_called_with("DELETE", f"{URL}/pages")


def test_non_404_error_propagates(repo: MagicMock) -> None:
    """A non-404 error from the GET is not swallowed as 'absent'."""
    repo.url = URL

    def _server_error(_verb: str, _url: str, **_kwargs: object) -> tuple[dict, dict]:
        raise GithubException(500, {"message": "boom"})

    repo.requester.requestJsonAndCheck.side_effect = _server_error
    desired = SharedConfig(pages=Pages(build_type="workflow"))

    with pytest.raises(GithubException):
        PagesManager().plan(repo, desired)
