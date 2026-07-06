<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Config reference

A config file names the repositories to manage and a shared block of sections applied to
every one of them. Every key is validated, so a typo becomes a load error, not a silent
no-op — unknown fields anywhere in the schema are rejected.

## File anatomy

A config lists `repos:` — `owner/repo` strings, each validated to be in that exact form —
plus the shared sections below. All sections are optional, but the `repos:` list must have
at least one entry.

```yaml
repos:
  - octocat/hello-world
  - octocat/spoon-knife

settings:
  description: "Example repository"
  private: false
  has_issues: true
  delete_branch_on_merge: true

actions:
  enabled: true
  allowed_actions: all
  can_approve_pull_request_reviews: true

labels:
  - name: bug
    color: d73a4a
    description: Something isn't working
  - name: needs-triage
    color: fbca04

collaborators:
  - username: octocat
    permission: admin

webhooks:
  - url: https://example.com/hooks/ci
    events: [push, pull_request]
    secret_from_env: CI_WEBHOOK_SECRET

secrets:
  - name: DEPLOY_TOKEN
    value_from_env: DEPLOY_TOKEN

variables:
  - name: ENVIRONMENT
    value: production

rulesets:
  - name: main-branch-protection
    target: branch
    rules:
      - type: pull_request
        required_approving_review_count: 1
```

## Section authority

!!! warning "A declared section is the complete desired set"
    Anything present on the repo but absent from the section is removed on apply: labels,
    webhooks, secrets, and variables not listed are deleted; direct collaborators not listed
    are removed; repo rulesets not listed are deleted. There's no partial-update mode —
    declaring three labels when the repo has five means the other two go away.

    An **omitted** section is the opposite: leave it out entirely and that whole domain is
    left unmanaged, untouched by apply. Whether you declare a section at all matters just as
    much as what you put in it.

## The sections

Each config section below has its own reference page with the full field table and
reconciliation behavior:

| Section | Purpose |
| --- | --- |
| [rulesets](rulesets.md) | Repository rulesets — target, enforcement, bypass actors, conditions, and rule types |
| [settings](config/settings.md) | Repository-level settings and merge options |
| [actions](config/actions.md) | Actions enablement, allowed-actions policy, and workflow permissions |
| [security](config/security.md) | Secret scanning, Dependabot, and private vulnerability reporting |
| [labels](config/labels.md) | Issue and PR labels |
| [collaborators](config/collaborators.md) | Direct collaborators and their permission level |
| [webhooks](config/webhooks.md) | Repository webhooks |
| [deploy_keys and autolinks](config/deploy-keys-and-autolinks.md) | Deploy keys and autolink references |
| [pages](config/pages.md) | GitHub Pages configuration |
| [secrets and variables](config/secrets-and-variables.md) | Actions secrets and repository variables |
| [environments](config/environments.md) | Deployment environments, protection rules, and environment-scoped secrets/variables |

## Composing with extends

A config can `extends:` one or more base files:

```yaml
extends: ../base/org-defaults.yaml
# or
extends:
  - ../base/org-defaults.yaml
  - ../base/security-baseline.yaml
```

Paths are relative to the file that declares them, and `extends:` is recursive — a base can
itself extend another base. Bases merge underneath the file that extends them, in list
order, and the extending file's own content merges on top of all of them last.

Merge rules:

- **Scalars** (strings, bools, individual `settings`/`actions` fields): the override wins
  outright.
- **Keyed lists** — `rulesets`, `labels`, `secrets`, `variables`, and `environments` by
  `name`; `collaborators` by `username`; `webhooks` by `url`; `deploy_keys` by `key`;
  `autolinks` by `key_prefix` — merge item-by-item: an override item sharing a base item's
  key *replaces* that item in place (keeping its position), and an override item with a new
  key is appended.

A circular `extends` chain (A extends B extends A) is detected and rejected as a config
error rather than looping forever.

By convention, in this repo's own `config/` directory, `*.yml` files are the *applied*
configs — each with its own `repos:` list, picked up by the CLI's config-dir glob — while
`*.yaml` files are base layers that only exist to be pulled in via `extends:`. Neither
extension is enforced by the schema; it's a naming convention this repo relies on to tell
the two apart at a glance. For example, `config/base.yaml` is the shared baseline that
`config/gha-public.yml`, `config/gha-private.yml`, and `config/ddns.yml` all extend (some by
way of `config/package.yaml`, an intermediate layer that adds PyPI publish secrets on top of
`base.yaml` for repos that publish a package):

```yaml
# config/package.yaml — a layer, not an applied config: no repos: of its own.
extends: base.yaml

secrets:
  - {name: TWINE_PYPI_UPLOAD_TOKEN, value_from_env: TWINE_PYPI_UPLOAD_TOKEN}
  - {name: TWINE_PYPI_TEST_UPLOAD_TOKEN, value_from_env: TWINE_PYPI_TEST_UPLOAD_TOKEN}
```

```yaml
# config/ddns.yml — an applied config: extends package.yaml, adds its own repos:.
extends: package.yaml

settings:
  private: false

repos:
  - nivintw/ddns
```

!!! warning
    `extends:` reads local files by relative path with no sandboxing — treat a base file
    with exactly the same scrutiny you'd give the config that includes it. It's a full peer
    of the file that extends it, not an inert template.

## Environment-sourced values

`value_from_env` (secrets, variables) and `secret_from_env` (webhooks) are resolved when a
plan or apply actually runs — not when the config is loaded and validated, so schema checks
don't require any secrets to be present in the environment.

!!! warning
    An env var that's **unset or empty** is a hard error at resolve time, and the two are
    treated identically on purpose: in GitHub Actions, `${{ secrets.X }}` for an unset secret
    expands to an empty string rather than failing the expression, so a presence-only check
    would silently propagate an empty value to every managed repo instead of failing loudly.
