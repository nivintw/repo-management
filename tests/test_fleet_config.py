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

from repo_management.config import (
    ConfigError,
    Secret,
    Variable,
    fleet_repo_names,
    fleet_repos,
    load_config,
)

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _names(items: list[Secret] | list[Variable] | None) -> set[str]:
    return {item.name for item in items or []}


def test_ddns_resolves_to_standardised_credentials() -> None:
    """package.yml manages ddns directly: exactly the standard creds, pruning legacy ones.

    The exact-set assertions are authoritative — anything ddns carries that is NOT listed is
    pruned by an apply. That is precisely how this migration retires the pre-scaffold names:
    GIST_SECRET and CI_APP_SECRET (secrets) and CI_APP_APPID (variable).
    """
    config = load_config(CONFIG_DIR / "package.yml")

    assert config.repos == ["nivintw/ddns"]
    assert config.settings is not None
    assert config.settings.private is False

    # Authoritative sections must be declared (not the old `null` opt-out), or an apply
    # would leave the legacy credentials in place.
    assert config.secrets is not None
    assert config.variables is not None

    assert _names(config.secrets) == {"CI_APP_PRIVATE_KEY", "GIST_PAT"}
    assert _names(config.variables) == {"CI_CLIENT_ID", "CI_APP_SLUG"}


def test_repo_management_vault_holds_every_injected_secret() -> None:
    """The source repo's own config must retain every value_from_env secret any config injects.

    apply-config.yml injects each value_from_env secret from repo-management's own Actions
    secrets into the managed repos. repo-management is itself managed (authoritatively), so a
    secret its config omits is pruned from the source — breaking the fleet apply. A narrower
    authoritative secrets set on the source once did exactly that to a vaulted token; this
    locks it shut by deriving the expected set from every config rather than hard-coding it.
    """
    vault = load_config(CONFIG_DIR / "repo-management.yml")

    assert vault.repos == ["nivintw/repo-management"]
    assert vault.settings is not None
    # Public since the package went to PyPI: the project links and the Pages docs site
    # depend on it, and an apply enforces whatever this says — `true` here would flip the
    # live repo private and 404 every public URL.
    assert vault.settings.private is False

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

    # expected is itself sorted+de-duplicated, so this asserts fleet_repos is too.
    assert result == expected
    assert "nivintw/repo-management" in result, "the control-plane repo is part of the fleet"


def test_fleet_repos_excludes_commented_out_repos() -> None:
    """Repos commented out in a config (cxxserv/cxxtests) never reach the fleet."""
    result = fleet_repos(CONFIG_DIR)

    assert "nivintw/cxxserv" not in result
    assert "nivintw/cxxtests" not in result


def test_security_floor_resolves_fleet_wide_from_base() -> None:
    """The Dependabot security floor (#144) reaches EVERY applied config via base.yaml.

    The floor lives in base.yaml, so every applied config (each ``config/*.yml`` — the exact set
    the apply workflow reconciles; base.yaml and projects.yaml carry the ``.yaml`` extension and
    are not applied) must resolve to Dependabot alerts + automated security fixes ON. Iterate the
    whole set rather than spot-checking one, so a config that drops its ``extends:`` or overrides
    ``security`` to opt out can't silently punch a hole in the fleet-wide floor and go unnoticed.

    Equally load-bearing: the *other* security fields must stay ``None`` (unmanaged) on every
    config. Only the two Dependabot toggles were declared on purpose — if secret scanning or
    private vulnerability reporting flipped to managed, an apply would start reconciling them on
    every repo too.
    """
    applied = sorted(
        CONFIG_DIR.glob("*.yml")
    )  # every applied config; base.yaml/projects.yaml are .yaml
    assert applied, "no applied configs matched config/*.yml — the glob found nothing"

    for cfg in applied:
        config = load_config(cfg)
        assert config.security is not None, cfg.name
        assert config.security.vulnerability_alerts is True, cfg.name
        assert config.security.automated_security_fixes is True, cfg.name
        # The floor manages ONLY the two Dependabot toggles; everything else stays unmanaged.
        assert config.security.secret_scanning is None, cfg.name
        assert config.security.secret_scanning_push_protection is None, cfg.name
        assert config.security.private_vulnerability_reporting is None, cfg.name


def test_fleet_repos_errors_on_empty_dir(tmp_path: Path) -> None:
    """An empty config dir is an error, not a silently-empty (fleet-wiping) filter."""
    with pytest.raises(ConfigError, match="no applied config files"):
        fleet_repos(tmp_path)


def test_fleet_repo_names_strips_owner_for_a_single_owner_fleet() -> None:
    """fleet_repo_names returns the fleet as bare, owner-stripped names (token scope)."""
    full = fleet_repos(CONFIG_DIR)
    names = fleet_repo_names(CONFIG_DIR)

    assert "repo-management" in names
    assert all("/" not in name for name in names), names
    # Same membership as fleet_repos, just owner-stripped.
    assert names == [repo.split("/", 1)[1] for repo in full]


def test_fleet_repo_names_rejects_multi_owner_fleet(tmp_path: Path) -> None:
    """A multi-owner fleet can't scope a per-owner App token — fail loud, never scope it wrong."""
    (tmp_path / "a.yml").write_text("repos:\n  - alice/svc\n", encoding="utf-8")
    (tmp_path / "b.yml").write_text("repos:\n  - bob/svc\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="single-owner fleet"):
        fleet_repo_names(tmp_path)
