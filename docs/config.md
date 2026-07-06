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

The five below (security, labels, collaborators, webhooks, GitHub Pages) are short enough
to stay on this page as sections; the denser or paired ones get their own reference page:

| Section | Purpose |
| --- | --- |
| [rulesets](rulesets.md) | Repository rulesets — target, enforcement, bypass actors, conditions, and rule types |
| [settings](config/settings.md) | Repository-level settings and merge options |
| [actions](config/actions.md) | Actions enablement, allowed-actions policy, and workflow permissions |
| [security](#security) | Secret scanning, Dependabot, and private vulnerability reporting |
| [labels](#labels) | Issue and PR labels |
| [collaborators](#collaborators) | Direct collaborators and their permission level |
| [webhooks](#webhooks) | Repository webhooks |
| [deploy_keys and autolinks](config/deploy-keys-and-autolinks.md) | Deploy keys and autolink references |
| [GitHub Pages](#github-pages) | GitHub Pages configuration |
| [secrets and variables](config/secrets-and-variables.md) | Actions secrets and repository variables |
| [environments](config/environments.md) | Deployment environments, protection rules, and environment-scoped secrets/variables |

## Security

Repository security posture. Every field is optional and independently managed — each maps
to its own GitHub endpoint, so a plan can show anywhere from zero to four separate changes
for this section (secret scanning and push protection share GitHub's nested
`security_and_analysis` object and are batched into a single change when either differs).

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `secret_scanning` | bool | unmanaged | |
| `secret_scanning_push_protection` | bool | unmanaged | |
| `vulnerability_alerts` | bool | unmanaged | Dependabot vulnerability alerts |
| `automated_security_fixes` | bool | unmanaged | Dependabot security updates |
| `private_vulnerability_reporting` | bool | unmanaged | See note below on how "unset" is determined |

```yaml
security:
  secret_scanning: true
  secret_scanning_push_protection: true
  vulnerability_alerts: true
  automated_security_fixes: true
  private_vulnerability_reporting: true
```

`private_vulnerability_reporting`'s status is read from a raw REST call; a 404 response
(the feature has never been turned on for the repo) is treated as "currently disabled"
rather than an error, the same convention the [Pages](#github-pages) section uses for a
feature that isn't configured yet.

## Labels

Issue and PR labels, matched by `name`. Exact-set semantics apply: labels on the repo that
aren't in the list are deleted.

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `name` | string | **required** | Match key |
| `color` | string | `ededed` | A leading `#` is stripped and the value lowercased before it's sent |
| `description` | string | unmanaged | Omitted means left as-is on GitHub, not cleared |

```yaml
labels:
  - name: bug
    color: d73a4a
    description: Something isn't working
  - name: needs-triage
    color: fbca04
  # release-please manages this one's description itself; omitting it here means this
  # config only enforces the color and never overwrites whatever description it sets.
  - name: "autorelease: pending"
    color: ededed
```

A label is updated only when its `color` differs, or when `description` is set in config
and differs from the live value — an omitted `description` never triggers an update and
never clears an existing one.

## Collaborators

Direct collaborators and their permission level, matched by `username`.

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `username` | string | **required** | Match key |
| `permission` | `pull` \| `triage` \| `push` \| `maintain` \| `admin` | `push` | |

```yaml
collaborators:
  - username: octocat
    permission: admin
```

!!! note
    Only **direct** collaborators (GitHub affiliation `direct`) are managed. Access
    inherited from an organization or a team is never inspected or touched, so this section
    can't accidentally revoke org-level access.

GitHub's legacy permission field collapses `maintain` into `write` and `triage` into
`read`, which would never converge as those roles; the manager instead reads each
collaborator's granular `role_name` and maps only `read`/`write` back to `pull`/`push`
(`triage`, `maintain`, and `admin` are reported verbatim), so a config declaring `triage` or
`maintain` reconciles correctly instead of endlessly re-applying.

## Webhooks

Repository webhooks, matched by `url`.

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `url` | string | **required** | Match key |
| `events` | list[string] | `[push]` | |
| `active` | bool | `true` | |
| `content_type` | `json` \| `form` | `json` | |
| `insecure_ssl` | bool | `false` | |
| `secret_from_env` | string | unset | Env var holding the webhook secret |

```yaml
webhooks:
  - url: https://example.com/hooks/ci
    events: [push, pull_request]
    secret_from_env: CI_WEBHOOK_SECRET
```

!!! note
    A webhook with a secret is re-sent on *every* apply, whether or not anything else
    changed — the GitHub API never returns a webhook's existing secret, so there's no value
    to diff against. Plans show it as `(set)` rather than printing it.

## GitHub Pages

GitHub Pages configuration. Omitting `pages:` entirely leaves it unmanaged; declaring it
with `enabled: false` disables Pages if it's currently on.

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `enabled` | bool | `true` | Set `false` to disable an existing Pages site |
| `build_type` | `legacy` \| `workflow` | **required** when enabled | |
| `source.branch` | string | **required** if `source` is set | Only meaningful for `build_type: legacy` |
| `source.path` | `/` \| `/docs` | `/` | |
| `cname` | string | unmanaged | Custom domain |
| `https_enforced` | bool | unmanaged | |

```yaml
pages:
  build_type: legacy
  source: {branch: main, path: "/docs"}
  https_enforced: true
```

`build_type` is required whenever `enabled` is true (the default) — a config error at load
time, not a deferred API rejection, if it's left out.

!!! note
    GitHub's create-Pages-site endpoint only accepts `build_type`/`source` —
    `cname`/`https_enforced` are update-only. Creating a new site with those already set
    takes a create call followed immediately by an update call, both inside one planned
    change.

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
`*.yaml` files are pure base layers that only exist to be pulled in via `extends:` and list
no repos of their own. Neither extension is enforced by the schema; it's a naming convention
this repo relies on to tell the two apart at a glance. `config/base.yaml` is the shared
baseline that `config/gha-public.yml` and `config/gha-private.yml` extend. `config/package.yml`
builds on `gha-public.yml` (rather than `base.yaml` directly, since publishing to PyPI means
the code is inherently public) to add PyPI publish secrets — and, like `gha-public.yml`
itself, plays a dual role: it's a layer `config/repo-management.yml` extends AND an applied
config in its own right, managing `ddns` directly via its own `repos:`:

```yaml
# config/package.yml — extends gha-public.yml; both a layer and an applied config.
extends: gha-public.yml

secrets:
  - {name: TWINE_PYPI_UPLOAD_TOKEN, value_from_env: TWINE_PYPI_UPLOAD_TOKEN}
  - {name: TWINE_PYPI_TEST_UPLOAD_TOKEN, value_from_env: TWINE_PYPI_TEST_UPLOAD_TOKEN}

repos:
  - nivintw/ddns
```

```yaml
# config/repo-management.yml — extends package.yml, overrides repos: to just itself.
extends: package.yml

repos:
  - nivintw/repo-management
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
