<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

<!-- Managed by commitizen. The first release will populate this file. -->

## v1.0.0 (2026-06-26)

### ✨ Features

- manage Actions variables + dogfood repo config with apply-on-main
- manage GitHub Actions variables
- rulesets + shared/extendable config, with authoritative sections
- make every declared config section authoritative
- replace branch protection with rulesets and shared/extendable config
- YAML-driven GitHub repository manager
- add YAML-driven GitHub repository manager

### 🐛🚑️ Fixes

- make ruleset diffing idempotent against server-supplied fields
- correct reconciliation bugs found in review

### ♻️ Refactorings

- derive ruleset serialization from pydantic model_dump
- batch settings edits and unify manager conventions

### 💚👷 CI & Build

- apply repo config on main and add the fleet config
- authenticate the CI App via the CI_CLIENT_ID variable

### 📝💡 Documentation

- document secret and branch-protection limitations
