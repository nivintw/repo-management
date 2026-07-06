<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Collaborators

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
