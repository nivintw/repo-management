<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Environments

Deployment environments, matched by `name`: protection rules plus environment-scoped
`secrets`/`variables` (same shape as the top-level [secrets and variables](secrets-and-variables.md)
sections, but scoped to the environment).

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `name` | string | **required** | Match key |
| `wait_timer` | int | unmanaged | Minutes to wait before allowing deployment |
| `reviewers` | list[reviewer] | unmanaged | Required reviewers; see below |
| `prevent_self_review` | bool | unmanaged | |
| `deployment_branch_policy.protected_branches` | bool | unmanaged | Mutually exclusive with `custom_branch_policies` |
| `deployment_branch_policy.custom_branch_policies` | bool | unmanaged | Mutually exclusive with `protected_branches` |
| `secrets` | list[secret] | unmanaged | Same shape as the top-level `secrets` section |
| `variables` | list[variable] | unmanaged | Same shape as the top-level `variables` section |

Setting both `protected_branches: true` and `custom_branch_policies: true` is a config error
at load time — GitHub's API rejects that combination too, but with an opaque error, so it's
caught earlier here.

Each reviewer is a `User` (by `login`) or a `Team` (by `slug`), resolved to the numeric ID
GitHub's API requires when the plan runs — a `Team` reviewer requires an org-owned
repository. `login`/`slug` must be a valid GitHub identifier (letters, digits, and internal
hyphens only — no `/`), since the value is used directly in the resolution request.

```yaml
environments:
  - name: production
    wait_timer: 10
    reviewers:
      - {type: User, login: octocat}
      - {type: Team, slug: platform}
    prevent_self_review: true
    deployment_branch_policy: {protected_branches: true}
    secrets:
      - {name: DEPLOY_TOKEN, value_from_env: PROD_DEPLOY_TOKEN}
    variables:
      - {name: REGION, value: us-east-1}
```

!!! note
    GitHub's create-environment endpoint is a single call covering wait timer, reviewers,
    self-review prevention, and branch policy together — there's no partial-update form. An
    unset field on an *existing* environment is preserved at its current live value rather
    than reset, the same policy [settings](settings.md) and [actions](actions.md) use for
    their own unmanaged fields. For a brand-new environment, an unset field falls back to
    GitHub's own defaults (`wait_timer: 0`, no reviewers, `prevent_self_review: false`, no
    branch policy) instead.

For a brand-new environment there's nothing yet to diff its secrets/variables against, so
its protection rules and its declared secrets/variables are folded into one `CREATE` change:
applying it creates the environment first, then pushes each secret/variable against the
newly-created environment.
