<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Webhooks

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
