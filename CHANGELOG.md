<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Changelog

<!-- release-please manages this file; new releases are prepended above the history below. -->

## [1.3.0](https://github.com/nivintw/repo-management/compare/v1.2.2...v1.3.0) (2026-07-03)


### Features

* Add a documentation site (GitHub Pages, docs/) ([1d26452](https://github.com/nivintw/repo-management/commit/1d26452fc6b1f6656706ef16a7fd6770b3f4d16f)), closes [#74](https://github.com/nivintw/repo-management/issues/74)
* Automerge non-major dependency PRs fleet-wide ([535d7dd](https://github.com/nivintw/repo-management/commit/535d7dd0423bfb5588ee1ba8e8d52ab5577a2bf6)), closes [#69](https://github.com/nivintw/repo-management/issues/69)
* Manage the Actions workflow-approval permission in settings ([6782e00](https://github.com/nivintw/repo-management/commit/6782e00dfff27203d94f5c302377fa98ea967937)), closes [#70](https://github.com/nivintw/repo-management/issues/70)


### Bug Fixes

* Address Copilot review on PR [#75](https://github.com/nivintw/repo-management/issues/75) ([cc883ac](https://github.com/nivintw/repo-management/commit/cc883ac1c17fa66de6fabb33f5dc2666e2473ea4))
* Address review-battery findings ([5483ec5](https://github.com/nivintw/repo-management/commit/5483ec5b6885a428eae287396625188a3afa4dd8))
* Make the README stand alone as the PyPI long description ([60df255](https://github.com/nivintw/repo-management/commit/60df255f30b5e6e62f90a391470e7be937d095bb)), closes [#74](https://github.com/nivintw/repo-management/issues/74)

## [1.2.2](https://github.com/nivintw/repo-management/compare/v1.2.1...v1.2.2) (2026-07-03)


### Bug Fixes

* Address review findings in the publish pipeline ([fdf107e](https://github.com/nivintw/repo-management/commit/fdf107e8e5f2f4471acde83a1a9a12e2e9714c8e))
* Rehearse releases on TestPyPI before publishing to PyPI ([9d43561](https://github.com/nivintw/repo-management/commit/9d43561b587df2d80d6b7db0439ec2989ca3b37f))

## [1.2.1](https://github.com/nivintw/repo-management/compare/v1.2.0...v1.2.1) (2026-06-29)


### Bug Fixes

* Arm the binary-checksum tamper gate in the central Renovate runner ([6bb3c15](https://github.com/nivintw/repo-management/commit/6bb3c154126db8987c89c98f9f9b5cff556c25ca)), closes [#48](https://github.com/nivintw/repo-management/issues/48)

## [1.2.0](https://github.com/nivintw/repo-management/compare/v1.1.0...v1.2.0) (2026-06-29)


### Features

* Add central self-hosted Renovate runner for the fleet ([73d69da](https://github.com/nivintw/repo-management/commit/73d69da44c81174b397281cbfabfdf594574af60)), closes [#42](https://github.com/nivintw/repo-management/issues/42)


### Bug Fixes

* Gate Renovate dry-run on workflow_dispatch event explicitly ([38750de](https://github.com/nivintw/repo-management/commit/38750deaff30df3596a1ab0890ab894fc5dd2326))
* Reject multi-owner fleets in list-repos --format names ([a1526c8](https://github.com/nivintw/repo-management/commit/a1526c84c422267b73219e5e9ab45ae9ff712939))

## [1.1.0](https://github.com/nivintw/repo-management/compare/v1.0.3...v1.1.0) (2026-06-28)


### Features

* Preview config plans on pull requests ([722f345](https://github.com/nivintw/repo-management/commit/722f3458a359058a1f659560959b833ea3dde514)), closes [#35](https://github.com/nivintw/repo-management/issues/35)
* Skip already-present secrets on apply, add --force-secrets ([df7f54b](https://github.com/nivintw/repo-management/commit/df7f54b4bfc0303798f44575901c1f0776c643c9)), closes [#37](https://github.com/nivintw/repo-management/issues/37)


### Bug Fixes

* Allowlist release-please's autorelease labels fleet-wide ([3d726d4](https://github.com/nivintw/repo-management/commit/3d726d47eb4844f44cbf7ed7b0cf59857588649b))
* Give the plan token write-level admin so the preview is accurate ([5298ae2](https://github.com/nivintw/repo-management/commit/5298ae28a10292cb286f6f7ab0607d36d91fc0ab))
* Manage ddns credentials via the package layer ([f85945f](https://github.com/nivintw/repo-management/commit/f85945f4c3f55c8423f440c44f6f736b3fe1a349)), closes [#22](https://github.com/nivintw/repo-management/issues/22)

## [1.0.3](https://github.com/nivintw/repo-management/compare/v1.0.2...v1.0.3) (2026-06-28)


### Bug Fixes

* Reject empty env values so unset secrets fail fast ([0516e04](https://github.com/nivintw/repo-management/commit/0516e04cac87e097485b94f5a24baea00b36161f))
* Track the scaffold repo's rename to copier-batteries-included-template ([4088e44](https://github.com/nivintw/repo-management/commit/4088e447c822608302bd0ff1f327c3fa84042eea)), closes [#29](https://github.com/nivintw/repo-management/issues/29)

## [1.0.2](https://github.com/nivintw/repo-management/compare/v1.0.1...v1.0.2) (2026-06-28)


### Bug Fixes

* Track the scaffold repo's rename to copier-batteries-included-template ([4088e44](https://github.com/nivintw/repo-management/commit/4088e447c822608302bd0ff1f327c3fa84042eea)), closes [#29](https://github.com/nivintw/repo-management/issues/29)

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
