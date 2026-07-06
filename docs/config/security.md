<!--
SPDX-FileCopyrightText: © 2026 Tyler Nivin
SPDX-License-Identifier: MIT
-->

# Security

Repository security posture. Every field is optional and independently managed — each maps
to its own GitHub endpoint, so a plan can show anywhere from zero to four separate changes
for this section (secret scanning and push protection share GitHub's nested
`security_and_analysis` object and are batched into a single change when either differs).

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `secret_scanning` | bool | unmanaged | |
| `secret_scanning_push_protection` | bool | unmanaged | |
| `vulnerability_alerts` | bool | unmanaged | Dependabot vulnerability alerts |
| `automated_security_fixes` | bool | unmanaged | Dependabot security updates |
| `private_vulnerability_reporting` | bool | unmanaged | No PyGithub support — driven directly through the authenticated requester |

```yaml
security:
  secret_scanning: true
  secret_scanning_push_protection: true
  vulnerability_alerts: true
  automated_security_fixes: true
  private_vulnerability_reporting: true
```

`private_vulnerability_reporting`'s status is read from a raw REST call; a 404 response
(the feature has never been turned on for the repo) is treated as "currently disabled"
rather than an error, the same convention the [pages](pages.md) manager uses for a feature
that isn't configured yet.
