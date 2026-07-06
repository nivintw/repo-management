<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Actions

Actions enablement/policy and workflow permissions — three separate GitHub API endpoints.
Every field is optional; a field left unset is left unmanaged, and an unmanaged field of a pair
(e.g. `enabled` vs. `allowed_actions`, which share one endpoint) is written back with its
live value on apply so the PUT doesn't clear it.

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `enabled` | bool | unmanaged | Whether Actions is enabled on the repo |
| `allowed_actions` | `all` \| `local_only` \| `selected` | unmanaged | |
| `selected_actions.github_owned_allowed` | bool | `true` | Requires `allowed_actions: selected` |
| `selected_actions.verified_allowed` | bool | `false` | |
| `selected_actions.patterns_allowed` | list[string] | `[]` | `owner/repo` patterns |
| `default_workflow_permissions` | `read` \| `write` | unmanaged | |
| `can_approve_pull_request_reviews` | bool | unmanaged | "Allow GitHub Actions to create and approve pull requests" |

```yaml
actions:
  enabled: true
  allowed_actions: selected
  selected_actions:
    github_owned_allowed: true
    verified_allowed: true
    patterns_allowed: ["astral-sh/*"]
  default_workflow_permissions: read
  can_approve_pull_request_reviews: true
```

Setting `selected_actions` without also setting `allowed_actions: selected` is a config
error rejected at load time, not a silently-ignored sub-config — GitHub rejects that
combination too, but this fails fast instead.

`default_workflow_permissions` and `can_approve_pull_request_reviews` share the
workflow-permissions endpoint the same way `enabled`/`allowed_actions` share the permissions
endpoint, so the two behave as one pair for the write-back-unmanaged-fields rule above.
