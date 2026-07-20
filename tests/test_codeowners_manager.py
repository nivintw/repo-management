# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the CODEOWNERS manager."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from github import GithubException

from repo_management.changes import Action
from repo_management.config import CodeownersEntry, SharedConfig
from repo_management.managers.codeowners import _PATH, CodeownersManager

_HEADER = "# managed by nivintw/repo-management; use caution before editing manually"


def _content_file(text: str, sha: str = "abc123") -> MagicMock:
    content = MagicMock(name="ContentFile")
    content.decoded_content = text.encode("utf-8")
    content.sha = sha
    return content


def test_no_codeowners_is_noop(repo: MagicMock) -> None:
    """A config without a codeowners section yields no changes."""
    assert CodeownersManager().plan(repo, SharedConfig()) == []
    repo.get_contents.assert_not_called()


def test_absent_file_is_created(repo: MagicMock) -> None:
    """Declared entries with no live file yield a CREATE via the Contents API."""
    repo.get_contents.side_effect = GithubException(404, {"message": "Not Found"})
    desired = SharedConfig(codeowners=[CodeownersEntry(pattern="*", owners=["@a", "@b"])])

    changes = CodeownersManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.CREATE
    assert change.target == _PATH
    assert change.after == f"{_HEADER}\n* @a @b\n"
    change.apply()
    repo.create_file.assert_called_once()
    args = repo.create_file.call_args.args
    assert args[0] == _PATH
    assert args[2] == f"{_HEADER}\n* @a @b\n"


def test_custom_header_is_rendered(repo: MagicMock) -> None:
    """A configured codeowners_header replaces the default, rendered as a '# '-prefixed line."""
    repo.get_contents.side_effect = GithubException(404, {"message": "Not Found"})
    desired = SharedConfig(
        codeowners=[CodeownersEntry(pattern="*", owners=["@a"])],
        codeowners_header="owned by platform-team; edit via config",
    )

    changes = CodeownersManager().plan(repo, desired)

    assert len(changes) == 1
    assert changes[0].after == "# owned by platform-team; edit via config\n* @a\n"


def test_custom_header_change_updates_existing_file(repo: MagicMock) -> None:
    """Changing only the header (entries unchanged) is drift that yields an UPDATE."""
    repo.get_contents.return_value = _content_file(f"{_HEADER}\n* @a\n", sha="sha-h")
    desired = SharedConfig(
        codeowners=[CodeownersEntry(pattern="*", owners=["@a"])],
        codeowners_header="new header text",
    )

    changes = CodeownersManager().plan(repo, desired)

    assert len(changes) == 1
    assert changes[0].action is Action.UPDATE
    changes[0].apply()
    assert repo.update_file.call_args.args[2] == "# new header text\n* @a\n"


def test_empty_string_header_is_honored_not_defaulted(repo: MagicMock) -> None:
    """An explicit empty header renders a bare '#' line rather than falling back to the default."""
    repo.get_contents.side_effect = GithubException(404, {"message": "Not Found"})
    desired = SharedConfig(
        codeowners=[CodeownersEntry(pattern="*", owners=["@a"])],
        codeowners_header="",
    )

    changes = CodeownersManager().plan(repo, desired)

    assert changes[0].after == "# \n* @a\n"


def test_matching_file_is_noop(repo: MagicMock) -> None:
    """A live file already matching the rendered content yields no change."""
    repo.get_contents.return_value = _content_file(f"{_HEADER}\n*.py @team\n")
    desired = SharedConfig(codeowners=[CodeownersEntry(pattern="*.py", owners=["@team"])])
    assert CodeownersManager().plan(repo, desired) == []


def test_differing_file_is_updated(repo: MagicMock) -> None:
    """A live file that differs yields an UPDATE carrying the existing blob sha."""
    repo.get_contents.return_value = _content_file(f"{_HEADER}\n* @old\n", sha="sha-1")
    desired = SharedConfig(codeowners=[CodeownersEntry(pattern="*", owners=["@new"])])

    changes = CodeownersManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.UPDATE
    change.apply()
    args = repo.update_file.call_args.args
    assert args[0] == _PATH
    assert args[2] == f"{_HEADER}\n* @new\n"
    assert args[3] == "sha-1"


def test_empty_list_deletes_existing_file(repo: MagicMock) -> None:
    """An authoritative-empty (codeowners: []) with a live file deletes it."""
    repo.get_contents.return_value = _content_file(f"{_HEADER}\n* @a\n", sha="sha-9")
    desired = SharedConfig(codeowners=[])

    changes = CodeownersManager().plan(repo, desired)

    assert len(changes) == 1
    change = changes[0]
    assert change.action is Action.DELETE
    change.apply()
    args = repo.delete_file.call_args.args
    assert args[0] == _PATH
    assert args[2] == "sha-9"


def test_empty_list_absent_file_is_noop(repo: MagicMock) -> None:
    """Authoritative-empty with no live file is already in the desired state."""
    repo.get_contents.side_effect = GithubException(404, {"message": "Not Found"})
    assert CodeownersManager().plan(repo, SharedConfig(codeowners=[])) == []


def test_non_404_error_propagates(repo: MagicMock) -> None:
    """A non-404 read error is not swallowed."""
    repo.get_contents.side_effect = GithubException(500, {"message": "boom"})
    desired = SharedConfig(codeowners=[CodeownersEntry(pattern="*", owners=["@a"])])
    with pytest.raises(GithubException):
        CodeownersManager().plan(repo, desired)


def test_directory_path_is_rejected(repo: MagicMock) -> None:
    """If the path resolves to a directory (a list), that's a clear error, not a crash."""
    repo.get_contents.return_value = [MagicMock(), MagicMock()]
    desired = SharedConfig(codeowners=[CodeownersEntry(pattern="*", owners=["@a"])])
    with pytest.raises(TypeError, match="file"):
        CodeownersManager().plan(repo, desired)
