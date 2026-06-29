# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Regression tests over the real fleet configs in ``config/``.

Unlike test_config.py (synthetic configs exercising the merge *logic*), these load the
actual applied configs and assert invariants about what they resolve to — so a wrong
``extends:`` or a fat-fingered section can't silently change what an apply does to live
repos. The motivating cases:

- ddns (#22): it must inherit the standardised credentials from the package/base layers and
  prune the legacy pre-scaffold names.
- repo-management itself: as the fleet's secret source it must retain every ``value_from_env``
  secret any config injects, or an apply prunes the source out from under the fleet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_management.config import ConfigError, Secret, Variable, fleet_repos, load_config

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _names(items: list[Secret] | list[Variable] | None) -> set[str]:
    return {item.name for item in items or []}


def test_ddns_resolves_to_standardised_credentials() -> None:
    """The ddns config extends package.yaml: exactly the standard creds, pruning legacy ones.

    The exact-set assertions are authoritative — anything ddns carries that is NOT listed is
    pruned by an apply. That is precisely how this migration retires the pre-scaffold names:
    GIST_SECRET and CI_APP_SECRET (secrets) and CI_APP_APPID (variable).
    """
    config = load_config(CONFIG_DIR / "ddns.yml")

    assert config.repos == ["nivintw/ddns"]
    assert config.settings is not None
    assert config.settings.private is False

    # Authoritative sections must be declared (not the old `null` opt-out), or an apply
    # would leave the legacy credentials in place.
    assert config.secrets is not None
    assert config.variables is not None

    assert _names(config.secrets) == {
        "CI_APP_PRIVATE_KEY",
        "GIST_PAT",
        "TWINE_PYPI_UPLOAD_TOKEN",
        "TWINE_PYPI_TEST_UPLOAD_TOKEN",
    }
    assert _names(config.variables) == {"CI_CLIENT_ID"}


def test_repo_management_vault_holds_every_injected_secret() -> None:
    """The source repo's own config must retain every value_from_env secret any config injects.

    apply-config.yml injects each value_from_env secret from repo-management's own Actions
    secrets into the managed repos. repo-management is itself managed (authoritatively), so a
    secret its config omits is pruned from the source — breaking the fleet apply. base.yaml's
    two-secret authoritative set once did exactly that to the TWINE tokens; this locks it shut.
    """
    vault = load_config(CONFIG_DIR / "repo-management.yml")

    assert vault.repos == ["nivintw/repo-management"]
    assert vault.settings is not None
    assert vault.settings.private is True

    injected = {
        secret.name
        for path in CONFIG_DIR.glob("*.yml")
        for secret in load_config(path).secrets or []
        if secret.value_from_env is not None
    }
    missing = injected - _names(vault.secrets)
    assert missing == set(), f"vault is missing injected secrets: {missing}"


def test_fleet_repos_is_the_union_of_applied_configs() -> None:
    """fleet_repos returns exactly the union of every config/*.yml ``repos:`` list.

    This set is what the central Renovate runner autodiscovers, so it must equal what the
    apply pipeline reconciles — every applied config's repos, de-duplicated and sorted.
    """
    expected = sorted(
        {repo for path in CONFIG_DIR.glob("*.yml") for repo in load_config(path).repos}
    )

    result = fleet_repos(CONFIG_DIR)

    assert result == expected
    assert result == sorted(set(result)), "fleet must be sorted and de-duplicated"
    assert "nivintw/repo-management" in result, "the control-plane repo is part of the fleet"


def test_fleet_repos_excludes_commented_out_repos() -> None:
    """Repos commented out in a config (cxxserv/cxxtests) never reach the fleet."""
    result = fleet_repos(CONFIG_DIR)

    assert "nivintw/cxxserv" not in result
    assert "nivintw/cxxtests" not in result


def test_fleet_repos_errors_on_empty_dir(tmp_path: Path) -> None:
    """An empty config dir is an error, not a silently-empty (fleet-wiping) filter."""
    with pytest.raises(ConfigError, match="no applied config files"):
        fleet_repos(tmp_path)
