# SPDX-FileCopyrightText: © 2026 Tyler Nivin
# SPDX-License-Identifier: MIT

"""Shared pydantic base model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Strict(BaseModel):
    """Base model that rejects unknown keys, catching config typos early."""

    model_config = ConfigDict(extra="forbid")
