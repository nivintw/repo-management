<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Settings

Repository-level settings and merge options. Every field is optional; a field left unset is
left unmanaged on the repo (not reset to a default). All the set fields batch into a single
`Repository.edit()` call plus, when `topics` is set, one additional topics call.

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `description` | string | unmanaged | |
| `homepage` | string | unmanaged | |
| `private` | bool | unmanaged | Mutually exclusive with `visibility` |
| `visibility` | `public` \| `private` \| `internal` | unmanaged | Mutually exclusive with `private`; `internal` only for enterprise-org repos |
| `topics` | list[string] | unmanaged | Diffed and replaced via a separate call; order-insensitive |
| `has_issues` | bool | unmanaged | |
| `has_wiki` | bool | unmanaged | |
| `has_projects` | bool | unmanaged | |
| `has_discussions` | bool | unmanaged | |
| `default_branch` | string | unmanaged | |
| `allow_squash_merge` | bool | unmanaged | |
| `allow_merge_commit` | bool | unmanaged | |
| `allow_rebase_merge` | bool | unmanaged | |
| `allow_auto_merge` | bool | unmanaged | |
| `delete_branch_on_merge` | bool | unmanaged | |
| `allow_update_branch` | bool | unmanaged | |
| `squash_merge_commit_title` | `PR_TITLE` \| `COMMIT_OR_PR_TITLE` | unmanaged | Required if `squash_merge_commit_message` is set |
| `squash_merge_commit_message` | `PR_BODY` \| `COMMIT_MESSAGES` \| `BLANK` | unmanaged | |
| `merge_commit_title` | `PR_TITLE` \| `MERGE_MESSAGE` | unmanaged | Required if `merge_commit_message` is set |
| `merge_commit_message` | `PR_BODY` \| `PR_TITLE` \| `BLANK` | unmanaged | |
| `web_commit_signoff_required` | bool | unmanaged | |
| `is_template` | bool | unmanaged | |
| `archived` | bool | unmanaged | |

```yaml
settings:
  has_issues: true
  has_wiki: true
  has_projects: true
  allow_squash_merge: false
  allow_merge_commit: false
  allow_rebase_merge: true
  delete_branch_on_merge: true
  default_branch: main
  allow_auto_merge: true
  allow_update_branch: true
```

GitHub's API requires the `*_title` field in the same request whenever its `*_message`
counterpart is set — even when the title's own value isn't changing — so the two are
validated as a pair at config-load time: setting `squash_merge_commit_message` (or
`merge_commit_message`) without its matching title is a config error, not a deferred API
rejection.

`visibility` is mutually exclusive with `private` — setting both is a config-load error. It
exists because `private: bool` can't express the third `internal` tier that repos in an
enterprise organization have. `internal` is only valid for a repo owned by an enterprise
organization; a personal-account repo can only be public or private, where `private` remains
the natural choice.

`topics` is diffed separately from the rest of the section: GitHub's topics endpoint is its
own call (`replace_topics`), compared order-insensitively against the repo's current topics,
so reordering the list in config alone produces no change.
