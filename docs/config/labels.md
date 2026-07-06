<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Labels

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
