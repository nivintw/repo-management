<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Deploy keys and autolinks

Grouped together because both share the same reconciliation quirk: GitHub's REST API has no
update endpoint for either resource, so a config change that would otherwise be a single
in-place update is instead planned as a delete of the stale item paired with a create of the
new one.

## deploy_keys

Deploy keys, matched by `key` content (not `title` — GitHub allows duplicate titles, but key
content is the real identity).

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `title` | string | **required** | |
| `key` | string | **required** | The public key content; match key |
| `read_only` | bool | `true` | |

```yaml
deploy_keys:
  - title: ci-deploy
    key: "ssh-ed25519 AAAAC3Nza... ci@example"
    read_only: true
```

Matching normalizes each key to just its algorithm and base64 body, dropping any trailing
`ssh-keygen`-style comment and ambient whitespace a YAML block scalar can introduce — so a
key that's unchanged except for its comment isn't planned as a spurious delete+recreate. The
same normalizer governs the `extends:` keyed-list merge for this section, so two entries
differing only by comment/whitespace can't survive a merge as if they were different keys.

!!! warning
    Changing `title` or `read_only` for the same key content is planned as a **delete of the
    old key paired with a create of the new one**, not a single in-place update — GitHub's
    deploy-key API has no update endpoint.

## autolinks

Autolink references, matched by `key_prefix` — a prefix like `TICKET-` in commit messages
and PR text is turned into a link using `url_template`.

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `key_prefix` | string | **required** | Match key |
| `url_template` | string | **required** | Must contain `<num>` |
| `is_alphanumeric` | bool | `true` | Whether the reference may include letters, not just digits |

```yaml
autolinks:
  - key_prefix: "TICKET-"
    url_template: "https://example.atlassian.net/browse/TICKET-<num>"
```

!!! warning
    Like deploy keys, GitHub's autolinks API has no update endpoint — a changed
    `url_template`/`is_alphanumeric` for an existing `key_prefix` is a delete-and-recreate,
    not an in-place update.
