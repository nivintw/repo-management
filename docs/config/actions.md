<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Actions

Actions enablement, policy, workflow permissions, and the fork-PR / access / retention
settings — seven separate GitHub API endpoints under `/actions/permissions`. Every field is
optional; a field left unset is left unmanaged, and an unmanaged field that shares an endpoint
with a managed one (e.g. `enabled` vs. `allowed_actions`) is written back with its live value
on apply so the PUT doesn't clear it.

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `enabled` | bool | unmanaged | Whether Actions is enabled on the repo |
| `allowed_actions` | `all` \| `local_only` \| `selected` | unmanaged | |
| `sha_pinning_required` | bool | unmanaged | Require actions to be pinned to a full-length commit SHA (shares the permissions endpoint) |
| `selected_actions.github_owned_allowed` | bool | `true` | Requires `allowed_actions: selected` |
| `selected_actions.verified_allowed` | bool | `false` | |
| `selected_actions.patterns_allowed` | list[string] | `[]` | `owner/repo` patterns |
| `default_workflow_permissions` | `read` \| `write` | unmanaged | Default `GITHUB_TOKEN` permissions |
| `can_approve_pull_request_reviews` | bool | unmanaged | "Allow GitHub Actions to create and approve pull requests" |
| `access_level` | `none` \| `user` \| `organization` | unmanaged | Which outside workflows may use this repo's actions/reusable workflows (private/internal repos) |
| `artifact_and_log_retention_days` | int > 0 | unmanaged | Artifact & log retention period, in days (GitHub enforces the org-configured ceiling) |
| `fork_pr_contributor_approval` | `first_time_contributors_new_to_github` \| `first_time_contributors` \| `all_external_contributors` | unmanaged | Approval policy for fork PRs from outside collaborators (public repos) |
| `fork_pr_workflows_private_repos.run_workflows_from_fork_pull_requests` | bool | unmanaged | Run workflows on fork PRs (private/internal repos) |
| `fork_pr_workflows_private_repos.send_write_tokens_to_workflows` | bool | unmanaged | Send write tokens to fork-PR workflows |
| `fork_pr_workflows_private_repos.send_secrets_and_variables` | bool | unmanaged | Expose secrets/variables to fork-PR workflows |
| `fork_pr_workflows_private_repos.require_approval_for_fork_pr_workflows` | bool | unmanaged | Require approval for fork-PR workflows |

```yaml
actions:
  enabled: true
  allowed_actions: selected
  sha_pinning_required: true
  selected_actions:
    github_owned_allowed: true
    verified_allowed: true
    patterns_allowed: ["astral-sh/*"]
  default_workflow_permissions: read
  can_approve_pull_request_reviews: true
  access_level: organization
  artifact_and_log_retention_days: 30
  fork_pr_contributor_approval: all_external_contributors
  fork_pr_workflows_private_repos:
    run_workflows_from_fork_pull_requests: true
    require_approval_for_fork_pr_workflows: true
```

Setting `selected_actions` without also setting `allowed_actions: selected` is a config
error rejected at load time, not a silently-ignored sub-config — GitHub rejects that
combination too, but this fails fast instead.

Several fields share one endpoint and so behave as a pair (or group) for the
write-back-unmanaged-fields rule above: `enabled` / `allowed_actions` / `sha_pinning_required`
share the permissions endpoint, `default_workflow_permissions` /
`can_approve_pull_request_reviews` share the workflow-permissions endpoint, and the four
`fork_pr_workflows_private_repos.*` fields share the private-repo fork-PR endpoint. Declaring
one member of a group writes the others back with their live values, so it never clears them —
in particular the API-required `run_workflows_from_fork_pull_requests` is always sent even when
left unmanaged.

`access_level` and the two fork-PR settings only apply to certain repo visibilities
(`access_level` and `fork_pr_workflows_private_repos` to private/internal repos,
`fork_pr_contributor_approval` to public repos). The manager stays declarative and sends what
you declare; GitHub rejects an inapplicable value (e.g. a non-`none` `access_level` on a public
repo) at apply time rather than the config silently dropping it.
