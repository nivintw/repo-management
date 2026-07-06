<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# GitHub Pages

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
