<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Changelog

<!-- release-please manages this file; new releases are prepended above the history below. -->

## [1.11.1](https://github.com/nivintw/repo-management/compare/v1.11.0...v1.11.1) (2026-07-14)


### Bug Fixes

* **apply:** preflight every write's payload so a missing secret aborts cleanly ([0b94273](https://github.com/nivintw/repo-management/commit/0b94273e8d5dea92c639285bb04b64287e34a5e8)), closes [#148](https://github.com/nivintw/repo-management/issues/148)
* **environments:** map a write-time unresolved variable to ConfigError ([f6f6255](https://github.com/nivintw/repo-management/commit/f6f6255061f0ea5470a6f5356b032835e6275d97)), closes [#148](https://github.com/nivintw/repo-management/issues/148)
* **secrets:** resolve values at consumption so plan never crashes on unset env ([bb9c4b6](https://github.com/nivintw/repo-management/commit/bb9c4b6e0225cc0f587503b11be4342aef0d46c2)), closes [#148](https://github.com/nivintw/repo-management/issues/148)

## [1.11.0](https://github.com/nivintw/repo-management/compare/v1.10.0...v1.11.0) (2026-07-09)


### Features

* **security:** enable the Dependabot security floor, dedup the Renovate seam ([1d6f83d](https://github.com/nivintw/repo-management/commit/1d6f83da5c18ea27f8c849da46dfc764ade5f8eb))

## [1.10.0](https://github.com/nivintw/repo-management/compare/v1.9.0...v1.10.0) (2026-07-09)


### Features

* **secrets:** re-push only when the source secret is newer than the target ([ad97a32](https://github.com/nivintw/repo-management/commit/ad97a32406d6f09993b136094b37c13ee7bce8c0)), closes [#141](https://github.com/nivintw/repo-management/issues/141)


### Bug Fixes

* **ci:** adopt the two-phase stranded-Release-PR query to stop the GraphQL node-limit crash ([1dd4306](https://github.com/nivintw/repo-management/commit/1dd430676f7c1a5347e963f756eb23599c4b42a2)), closes [#140](https://github.com/nivintw/repo-management/issues/140)
* **secrets:** read target updated_at via getattr so an undatable container degrades ([165b8be](https://github.com/nivintw/repo-management/commit/165b8be7690835763c3ee5bd849103e47a48f70f))


### Performance Improvements

* **secrets:** skip the source-timestamp read when no secret is env-sourced ([156fdad](https://github.com/nivintw/repo-management/commit/156fdad62e3b33f056aa3b3704e011c3871803fb))

## [1.9.0](https://github.com/nivintw/repo-management/compare/v1.8.0...v1.9.0) (2026-07-09)


### Features

* **projects:** Add ProjectsManager for declarative board schema ([d5e4f30](https://github.com/nivintw/repo-management/commit/d5e4f30dee3174f25bc15d303c01217101ac56eb))
* **projects:** Add roadmap status/reconcile/insights automations ([3b5a7a1](https://github.com/nivintw/repo-management/commit/3b5a7a1cd563cc10535607a9c4f51f1c199eed88))
* **projects:** Add roadmap status/reconcile/insights workflows ([5a4c863](https://github.com/nivintw/repo-management/commit/5a4c863bfb18f46cf1172bf8bee4ba3a5324628c))
* **projects:** Declare ROADMAP_PROJECT_TOKEN so apply-config won't prune it ([f315723](https://github.com/nivintw/repo-management/commit/f3157232d1be769ded1138cdabac5d70467d1da8))


### Bug Fixes

* **projects:** Address Copilot review — field-value/label truncation + wording ([9b16ab0](https://github.com/nivintw/repo-management/commit/9b16ab0610c6da1ddfd9ca11363c4eddf217b1b8))
* **projects:** Address Copilot round 2 — label ambiguity, mention safety, week date ([ddf1c90](https://github.com/nivintw/repo-management/commit/ddf1c9090e50b1b0c536077021888518b97d866c))
* **projects:** Address Copilot round 3 — doc ref, option casing, sweep concurrency ([e50d20e](https://github.com/nivintw/repo-management/commit/e50d20ea14cdffda89692ab692ca136fdaf98a55))
* **projects:** Correct token guidance — user boards need a classic project-scope PAT ([99f7888](https://github.com/nivintw/repo-management/commit/99f78885a42872679e2b5270ff6c9cd2f1a136f2))
* **projects:** Exclude archived items and fail loud on empty/misconfigured boards ([440034a](https://github.com/nivintw/repo-management/commit/440034a8e9e8f506f11b37ee4b1d104bef8e784f))
* **projects:** HTML-escape board titles/phase in the status update body ([6840503](https://github.com/nivintw/repo-management/commit/68405039648ba04cb79b09f7c366b3f1204ddb72))

## [1.8.0](https://github.com/nivintw/repo-management/compare/v1.7.7...v1.8.0) (2026-07-07)


### Features

* Expand the config surface — patterns, push rulesets, teams, CODEOWNERS ([f74a507](https://github.com/nivintw/repo-management/commit/f74a50715cef4119ebefb9c63ea112e1ee2ac1fb))


### Bug Fixes

* Harden deployment-branch-policy pattern handling (Copilot review) ([0a5676e](https://github.com/nivintw/repo-management/commit/0a5676eaa7bba67c89a1a2eab920431518580a30))

## [1.7.7](https://github.com/nivintw/repo-management/compare/v1.7.6...v1.7.7) (2026-07-06)


### Bug Fixes

* Harden and correct the stranded-Release-PR non-bot-commit guard ([5517914](https://github.com/nivintw/repo-management/commit/5517914d486de0266beca427c7c126f3fe9c638f))
* Restore labeled error message for an unreadable pin file ([ac83a75](https://github.com/nivintw/repo-management/commit/ac83a75be7943f67b26c04555dcc356d20252e6b))

## [1.7.6](https://github.com/nivintw/repo-management/compare/v1.7.5...v1.7.6) (2026-07-06)


### Bug Fixes

* Bump the stale docs.yml pin and cover it in the trigger paths ([fbad55a](https://github.com/nivintw/repo-management/commit/fbad55acddabd3387c717d66fc78d46c7be5d841)), closes [#118](https://github.com/nivintw/repo-management/issues/118)

## [1.7.5](https://github.com/nivintw/repo-management/compare/v1.7.4...v1.7.5) (2026-07-06)


### Bug Fixes

* Address review-pr findings on the copier update ([5381479](https://github.com/nivintw/repo-management/commit/53814792ac9f28bf400470f82a506d4ee34e138b))

## [1.7.4](https://github.com/nivintw/repo-management/compare/v1.7.3...v1.7.4) (2026-07-06)


### Bug Fixes

* Flip public repos to workflow-based Pages, fold ddns into package.yml ([3ffc57a](https://github.com/nivintw/repo-management/commit/3ffc57acbfd6af938fd87f42dccc3a2ceff6682a)), closes [#88](https://github.com/nivintw/repo-management/issues/88)

## [1.7.3](https://github.com/nivintw/repo-management/compare/v1.7.2...v1.7.3) (2026-07-06)


### Bug Fixes

* Request pages permission when minting the CI App token ([93dc546](https://github.com/nivintw/repo-management/commit/93dc5469da47f745ba44b9ea48bdd6014feb29f9)), closes [#106](https://github.com/nivintw/repo-management/issues/106)

## [1.7.2](https://github.com/nivintw/repo-management/compare/v1.7.1...v1.7.2) (2026-07-06)


### Bug Fixes

* Use full ref path for the release-tag ruleset's pattern ([e269830](https://github.com/nivintw/repo-management/commit/e2698304c4ef4f42e177826c274b070798854bf0)), closes [#103](https://github.com/nivintw/repo-management/issues/103)

## [1.7.1](https://github.com/nivintw/repo-management/compare/v1.7.0...v1.7.1) (2026-07-06)


### Bug Fixes

* Flip repo-management's GitHub Pages source to Actions-based builds ([70aef90](https://github.com/nivintw/repo-management/commit/70aef903b761ce2381d36600f776d5d398ffdf8a)), closes [#87](https://github.com/nivintw/repo-management/issues/87)

## [1.7.0](https://github.com/nivintw/repo-management/compare/v1.6.1...v1.7.0) (2026-07-06)


### Features

* Declare workflow-based Pages config, pin docs-site's caller SHA ([8c671ba](https://github.com/nivintw/repo-management/commit/8c671ba045e1bc68f89742234f605f54ef0bb902)), closes [#87](https://github.com/nivintw/repo-management/issues/87)


### Bug Fixes

* Defer the pages: config flip out of this PR to avoid a deploy race ([7f7f1af](https://github.com/nivintw/repo-management/commit/7f7f1afe37838c9a83785880f9a6674641de8e3b)), closes [#87](https://github.com/nivintw/repo-management/issues/87)
* Exclude not-yet-live doc-site links from lychee ([b8bed15](https://github.com/nivintw/repo-management/commit/b8bed15c3b8cd0865de267b327809cf69a99a6fb)), closes [#87](https://github.com/nivintw/repo-management/issues/87)
* Rename docs/index.html -&gt; legacy-index.html, keep legacy site self-consistent ([4635e48](https://github.com/nivintw/repo-management/commit/4635e488ee23ae1a040fd2842af87ff175e1e3f1)), closes [#87](https://github.com/nivintw/repo-management/issues/87)
* Watch overrides/** in docs-site.yml's push trigger ([0642f4b](https://github.com/nivintw/repo-management/commit/0642f4bc5162f796664a1bb96d70ce4b7af5f4ac)), closes [#87](https://github.com/nivintw/repo-management/issues/87)

## [1.6.1](https://github.com/nivintw/repo-management/compare/v1.6.0...v1.6.1) (2026-07-06)


### Bug Fixes

* Reconcile stale references and comments from review ([3b10fcd](https://github.com/nivintw/repo-management/commit/3b10fcdc04353e3f1d3a914872606eadf5e623ed)), closes [#91](https://github.com/nivintw/repo-management/issues/91)

## [1.6.0](https://github.com/nivintw/repo-management/compare/v1.5.0...v1.6.0) (2026-07-05)


### Features

* Add reusable MkDocs Material docs-build-and-deploy workflow ([fef7f1f](https://github.com/nivintw/repo-management/commit/fef7f1f035ad5a18fb01cbfce7e06a4109f146c6)), closes [#86](https://github.com/nivintw/repo-management/issues/86)


### Bug Fixes

* Address review findings on the reusable docs workflow ([5994058](https://github.com/nivintw/repo-management/commit/599405831fddc2f956d64169ba662787733c3f30))

## [1.5.0](https://github.com/nivintw/repo-management/compare/v1.4.1...v1.5.0) (2026-07-04)


### Features

* Close the settings-coverage audit and speed up Renovate cadence ([4f4a26b](https://github.com/nivintw/repo-management/commit/4f4a26b0733a616c868b6c5dd354e5bf3318eefe))


### Bug Fixes

* Address review-pr findings on the new managers ([8fa53e4](https://github.com/nivintw/repo-management/commit/8fa53e49a48c0a3745edf3a3605e4941265d953c))
* Don't resend or display an in-sync security_and_analysis field ([821d8d4](https://github.com/nivintw/repo-management/commit/821d8d4376075aa12a984e9af1a7f46122ce602f))
* Enforce the merge-commit title/message pairing GitHub's API requires ([46014c7](https://github.com/nivintw/repo-management/commit/46014c7da4d827c8efe47c4c178e272a85a7e5c5))
* Merge deploy_keys by the same normalized identity the manager diffs by ([ae2ac60](https://github.com/nivintw/repo-management/commit/ae2ac60290116cc5006f30d808faedb07601a425))
* Reject autolink url_template missing the &lt;num&gt; placeholder ([956f7e9](https://github.com/nivintw/repo-management/commit/956f7e933ac0b6835ec43b4d175e88c594ba2a7d))

## [1.4.1](https://github.com/nivintw/repo-management/compare/v1.4.0...v1.4.1) (2026-07-04)


### Bug Fixes

* Require a longer release age for credential-receiving actions ([4cac927](https://github.com/nivintw/repo-management/commit/4cac9278abf03ed65abbe71234f2e57a83a4e751)), closes [#77](https://github.com/nivintw/repo-management/issues/77)

## [1.4.0](https://github.com/nivintw/repo-management/compare/v1.3.0...v1.4.0) (2026-07-04)


### Features

* Add Actions permissions manager and v* tag ruleset ([c14ae9b](https://github.com/nivintw/repo-management/commit/c14ae9b0ff04a4dac6ce5e1973db73c59458e199))


### Bug Fixes

* Address Copilot review on PR [#79](https://github.com/nivintw/repo-management/issues/79) ([6390992](https://github.com/nivintw/repo-management/commit/639099230daebed91e8c62ea3a7f982dc213eff1))
* Enforce ActionsConfig invariant and add tag-ruleset admin bypass ([890d15f](https://github.com/nivintw/repo-management/commit/890d15f982d62a45e8bc89dd611dc3b033b355e8))

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
