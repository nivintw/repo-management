<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Changelog

<!-- release-please manages this file; new releases are prepended above the history below. -->

## [1.0.1](https://github.com/nivintw/repo-management/compare/v1.0.0...v1.0.1) (2026-06-28)


### Bug Fixes

* Reject empty env values so unset secrets fail fast ([0516e04](https://github.com/nivintw/repo-management/commit/0516e04cac87e097485b94f5a24baea00b36161f))

## v1.0.0 (2026-06-26)

### Features

- manage Actions variables + dogfood repo config with apply-on-main
- manage GitHub Actions variables
- rulesets + shared/extendable config, with authoritative sections
- make every declared config section authoritative
- replace branch protection with rulesets and shared/extendable config
- YAML-driven GitHub repository manager
- add YAML-driven GitHub repository manager

### Bug Fixes

- make ruleset diffing idempotent against server-supplied fields
- correct reconciliation bugs found in review

### Code Refactoring

- derive ruleset serialization from pydantic model_dump
- batch settings edits and unify manager conventions

### Continuous Integration

- apply repo config on main and add the fleet config
- authenticate the CI App via the CI_CLIENT_ID variable

### Documentation

- document secret and branch-protection limitations
