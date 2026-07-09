# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Tests for the Projects v2 board config schema and loader."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from repo_management.config import (
    ConfigError,
    ProjectField,
    ProjectsConfig,
    load_projects_config,
)

_VALID = """
owner: nivintw
number: 2
fields:
  - name: Status
    data_type: single_select
    options:
      - {name: Todo, color: GRAY}
      - {name: Done, color: GREEN, description: Completed}
  - name: Target
    data_type: date
"""


def test_valid_config_loads(tmp_path: Path) -> None:
    """A well-formed board config loads with its fields, options, and defaults."""
    path = tmp_path / "projects.yaml"
    path.write_text(_VALID, encoding="utf-8")
    config = load_projects_config(path)
    assert config.owner == "nivintw"
    assert config.owner_type == "user"  # default
    assert [f.name for f in config.fields] == ["Status", "Target"]
    assert config.fields[0].options is not None
    assert config.fields[0].options[1].description == "Completed"


def test_single_select_requires_options() -> None:
    """A single-select field with no options is rejected."""
    with pytest.raises(ValidationError, match="requires a non-empty 'options'"):
        ProjectField(name="Status", data_type="single_select")


def test_non_single_select_forbids_options() -> None:
    """A non-single-select field carrying options is rejected."""
    with pytest.raises(ValidationError, match="only valid for a 'single_select'"):
        # Dict input mirrors how YAML loads; model_validate exercises the coercion path.
        ProjectField.model_validate(
            {"name": "Target", "data_type": "date", "options": [{"name": "x"}]}
        )


def test_duplicate_option_names_rejected() -> None:
    """Duplicate option names within a field are rejected."""
    with pytest.raises(ValidationError, match="duplicate option names"):
        ProjectField.model_validate(
            {
                "name": "Status",
                "data_type": "single_select",
                "options": [{"name": "Todo"}, {"name": "Todo"}],
            }
        )


def test_duplicate_field_names_rejected() -> None:
    """Two fields with the same name are rejected."""
    with pytest.raises(ValidationError, match="duplicate field names"):
        ProjectsConfig(
            owner="nivintw",
            number=2,
            fields=[
                ProjectField(name="Status", data_type="date"),
                ProjectField(name="Status", data_type="date"),
            ],
        )


def test_invalid_owner_rejected() -> None:
    """An owner login with invalid characters is rejected."""
    with pytest.raises(ValidationError, match="not a valid GitHub owner"):
        ProjectsConfig(
            owner="not/valid", number=2, fields=[ProjectField(name="T", data_type="date")]
        )


def test_bad_color_rejected() -> None:
    """An option color outside GitHub's palette is rejected."""
    with pytest.raises(ValidationError):
        ProjectField.model_validate(
            {
                "name": "Status",
                "data_type": "single_select",
                "options": [{"name": "Todo", "color": "MAUVE"}],
            }
        )


def test_missing_file_raises_config_error(tmp_path: Path) -> None:
    """A missing config file surfaces as a ConfigError."""
    with pytest.raises(ConfigError, match="cannot read config file"):
        load_projects_config(tmp_path / "nope.yaml")


def test_schema_error_raises_config_error(tmp_path: Path) -> None:
    """A schema-invalid config surfaces as a ConfigError, not a raw ValidationError."""
    path = tmp_path / "projects.yaml"
    path.write_text("owner: nivintw\nnumber: 2\nfields: []\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid projects configuration"):
        load_projects_config(path)
