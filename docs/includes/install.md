<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

<!-- Shared content fragment, included via pymdownx.snippets (`--8<-- "install.md"`) from
     any docs page that needs install instructions, so they can't drift between copies
     (nivintw/repo-management#96). -->

```bash
uv tool install repo-management    # or: pip install repo-management
```

Requires Python 3.14+. Authentication uses a GitHub token, read from `$GITHUB_TOKEN` (or
`--token`); the token needs the scopes for whatever you manage (repo administration,
Actions secrets, and so on).
