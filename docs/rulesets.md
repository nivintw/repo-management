<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Rulesets reference

Repository rulesets — branch or tag protection rules — are declared under a config's `rulesets:` section. Each entry is matched to a live ruleset by `name` and updated to exactly the declared spec.

## Ruleset shape

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `name` | string | required | Match key |
| `target` | `branch` \| `tag` \| `push` | `branch` | |
| `enforcement` | `active` \| `evaluate` \| `disabled` | `active` | |
| `bypass_actors` | list | `[]` | See [Bypass actors](#bypass-actors) |
| `conditions` | object | empty `ref_name` | See [Conditions](#conditions) |
| `rules` | list | `[]` | See [Rule types](#rule-types) |

```yaml
rulesets:
  - name: main-branch-protection
    target: branch
    enforcement: active
    conditions:
      ref_name:
        include: ["~DEFAULT_BRANCH"]
        exclude: []
    bypass_actors:
      - actor_type: OrganizationAdmin
        bypass_mode: always
    rules:
      - type: pull_request
        required_approving_review_count: 1
        dismiss_stale_reviews_on_push: true
      - type: required_status_checks
        required_checks: [ci, lint]
        strict_required_status_checks_policy: true
```

Rulesets merge across `extends:` layers the same way as the config's other keyed lists — by `name`, same-key item replaces in place, new items append. See [composing with extends](config.md#composing-with-extends) in the config reference.

## Tag rulesets

Setting `target: tag` protects tags instead of branches — the same rule types, conditions, and bypass actors apply, just matched against tag names. A common case is locking down release tags so only an automated release process can create them, closing a publish trust boundary: if a CI workflow trusts "pushing a `v*` tag" as the signal to publish, anyone who can push that tag can trigger a publish from an arbitrary tree.

```yaml
rulesets:
  - name: protect release tags
    target: tag
    enforcement: active
    conditions:
      ref_name:
        include: ["v*"]
        exclude: []
    rules:
      - type: creation
      - type: update
      - type: deletion
    bypass_actors:
      - actor_type: RepositoryRole
        actor_id: 5   # Repository Admins (a built-in base role — no slug, use its id)
        bypass_mode: always
      - actor_type: Integration
        actor_slug: my-release-app   # resolved to the App's id at plan time
        bypass_mode: always
```

The `bypass_actors` entries are what let the automated process (here, a GitHub App) still create/move/delete the tag while everyone else is blocked by the three rules above. Naming the App by `actor_slug` beats hand-copying its numeric id; see [Bypass actors](#bypass-actors) for which types resolve by slug. Give admins a bypass too, not just the automation: without one, a broken App installation or key locks every repo owner out of their own tags until the ruleset itself is edited.

## Push rulesets

GitHub partitions rule types by target. A `push` ruleset accepts *only* the four file-restriction rule types — `file_path_restriction`, `max_file_path_length`, `file_extension_restriction`, and `max_file_size` — and every other rule type is branch/tag-only. This tool enforces the partition at config-load time (a load error), not at apply (a 422): the four file rules require `target: push`, any other rule type on a push target is rejected, and the four file rules are rejected on a branch/tag target.

A push ruleset selects no refs, so it must *not* carry a `conditions.ref_name` include/exclude — declaring one is rejected at load.

```yaml
rulesets:
  - name: block-binaries-and-large-files
    target: push
    enforcement: active
    rules:
      - type: max_file_size
        max_file_size: 100
      - type: file_extension_restriction
        restricted_file_extensions: [".exe", ".dll"]
```

## Matching and drift

!!! note
    A ruleset is matched to a live one by `name`. Once matched, every declared list — `rules`, `bypass_actors`, and the ref-name include/exclude patterns in `conditions` — must equal the live list exactly, not just be a subset. A rule someone added by hand in the GitHub UI counts as drift and triggers an update that removes it, same as any other mismatch.

    Server-supplied metadata that the config never sets — a check's `integration_id`, a bypass actor's resolved `actor_id`, timestamps — is ignored when comparing, so values GitHub fills in on its own can't cause spurious churn on every plan.

    Rulesets inherited from an organization or enterprise are never matched or deleted: the listing call uses `includes_parents=false`, so only rulesets defined directly on the repo are ever in scope.

!!! warning
    A declared `rulesets:` section is authoritative for the repo's *own* rulesets: any repo-level ruleset whose name isn't in the config gets deleted, and an explicit empty list (`rulesets: []`) deletes every one of them. Omitting the `rulesets:` key entirely, by contrast, leaves existing rulesets untouched — `None` and `[]` are not the same thing here.

## Conditions

Conditions select which refs a ruleset applies to, via `ref_name.include` and `ref_name.exclude` pattern lists.

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `ref_name.include` | list[string] | `[]` | Two special tokens: `~DEFAULT_BRANCH`, `~ALL` |
| `ref_name.exclude` | list[string] | `[]` | |

```yaml
conditions:
  ref_name:
    include: ["~DEFAULT_BRANCH"]
    exclude: ["refs/heads/releases/**"]
```

## Bypass actors

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `actor_type` | `Integration` \| `OrganizationAdmin` \| `RepositoryRole` \| `Team` \| `DeployKey` | required | |
| `actor_id` | int | unset | The numeric id. Required for `Integration`, `RepositoryRole`, and `Team` **unless** `actor_slug` is set; must be omitted for `DeployKey`; ignored for `OrganizationAdmin` |
| `actor_slug` | string | unset | A human-readable name resolved to `actor_id` at plan time — an App slug (`Integration`), a team slug (`Team`), or a **custom** repository-role name (`RepositoryRole`). Set exactly one of `actor_id`/`actor_slug` for those types |
| `bypass_mode` | `always` \| `pull_request` | `always` | |

!!! tip "Name a bypass actor by slug, not a hidden id"
    You rarely know an App's or team's numeric id off-hand. Give `actor_slug` instead and the
    tool looks the id up via the GitHub API when it plans:

    - `Integration` → the App's slug (`GET /apps/{slug}`)
    - `Team` → the team's slug within the repo's org (`GET /orgs/{org}/teams/{slug}`)
    - `RepositoryRole` → a **custom** repository role's name (matched case-insensitively). GitHub's
      built-in base roles (read/triage/write/maintain/admin) have no name→id endpoint, so those
      still need a literal `actor_id`.

    A slug that doesn't resolve fails the plan loudly — it's never silently dropped.

!!! note
    The `actor_type`/`actor_id` coherence is validated at config load, following GitHub's own
    rule: "Required for Integration, RepositoryRole, Team, and User actor types. If actor_type
    is OrganizationAdmin, actor_id is ignored. If actor_type is DeployKey, this should be null."
    Supplying `actor_slug` satisfies the "required" half without a literal id. This model does
    not include the `User` actor type.

## Rule types

Each entry in `rules:` has a `type` discriminator plus that type's own parameters. The groups below cover every supported type.

### Parameterless

These take no parameters — just the `type`:

```yaml
rules:
  - type: creation
  - type: deletion
  - type: non_fast_forward
  - type: required_linear_history
  - type: required_signatures
```

### Pattern rules

`commit_message_pattern`, `commit_author_email_pattern`, `committer_email_pattern`, `branch_name_pattern`, and `tag_name_pattern` all share the same parameter shape:

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `operator` | `starts_with` \| `ends_with` \| `contains` \| `regex` | required | |
| `pattern` | string | required | |
| `name` | string | unset | Label shown for the pattern in the GitHub UI |
| `negate` | bool | `false` | |

```yaml
rules:
  - type: commit_message_pattern
    operator: regex
    pattern: '^(feat|fix|docs|refactor|chore)(\(.+\))?: .+'
    name: conventional-commits
```

### update

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `update_allows_fetch_and_merge` | bool | `false` | |

### pull_request

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `required_approving_review_count` | int | `0` | |
| `dismiss_stale_reviews_on_push` | bool | `false` | |
| `require_code_owner_review` | bool | `false` | |
| `require_last_push_approval` | bool | `false` | |
| `required_review_thread_resolution` | bool | `false` | |
| `allowed_merge_methods` | list of `merge` \| `squash` \| `rebase` | unset | Unset allows all methods |

### required_status_checks

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `required_checks` | list | `[]` | Bare strings are coerced to `{context: ...}`; entries may also set `integration_id` |
| `strict_required_status_checks_policy` | bool | `false` | |
| `do_not_enforce_on_create` | bool | `false` | |

```yaml
rules:
  - type: required_status_checks
    required_checks: [ci, lint]      # shorthand for [{context: ci}, {context: lint}]
    strict_required_status_checks_policy: true
```

### required_deployments

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `required_deployment_environments` | list[string] | `[]` | Environment names |

### merge_queue

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `check_response_timeout_minutes` | int | `60` | |
| `grouping_strategy` | `ALLGREEN` \| `HEADGREEN` | `ALLGREEN` | |
| `max_entries_to_build` | int | `5` | |
| `max_entries_to_merge` | int | `5` | |
| `merge_method` | `MERGE` \| `SQUASH` \| `REBASE` | `MERGE` | |
| `min_entries_to_merge` | int | `1` | |
| `min_entries_to_merge_wait_minutes` | int | `5` | |

### File restrictions

Four separate rule types, each gating one kind of file-level change. These are valid *only* on a `push` ruleset (see [Push rulesets](#push-rulesets) above):

| Rule type | Field | Default | Notes |
| --- | --- | --- | --- |
| `file_path_restriction` | `restricted_file_paths` | `[]` | Paths that cannot be added or modified |
| `max_file_path_length` | `max_file_path_length` | required | Maximum path length, in characters |
| `file_extension_restriction` | `restricted_file_extensions` | `[]` | Extensions that cannot be added or modified |
| `max_file_size` | `max_file_size` | required | Maximum blob size, in MB |

### workflows

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `workflows` | list of `{repository_id, path, ref?, sha?}` | `[]` | `repository_id` and `path` required per entry |
| `do_not_enforce_on_create` | bool | `false` | |

```yaml
rules:
  - type: workflows
    workflows:
      - repository_id: 123456789
        path: .github/workflows/ci.yml
        ref: refs/heads/main
```

### code_scanning

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `code_scanning_tools` | list of `{tool, security_alerts_threshold, alerts_threshold}` | `[]` | `security_alerts_threshold` defaults to `high_or_higher`, `alerts_threshold` to `errors` |

### copilot_code_review

A branch-target rule that requests an automatic Copilot review on the PR flow. It supersedes the deprecated `automatic_copilot_code_review_enabled` `pull_request` parameter.

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `review_on_push` | bool | `false` | Re-review when new commits are pushed |
| `review_draft_pull_requests` | bool | `false` | Also review draft PRs |
