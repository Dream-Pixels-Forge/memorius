# Security Policy

## Supported versions

We actively support the latest release of Memorius. Older releases may not receive
security updates.

| Version | Supported |
|---------|-----------|
| 0.9.x   | ✅        |
| < 0.9   | ❌        |

## Reporting a vulnerability

Please do **not** open a public GitHub issue for security vulnerabilities.

Instead, email the maintainer at **dimona.patrick@gmail.com**, or open a
[private security advisory](https://github.com/Dream-Pixels-Forge/memorius/security/advisories/new)
if you prefer GitHub. Include details of the issue, steps to reproduce, and any
suggested fix. We'll acknowledge receipt within 48 hours and work with you on
disclosure and remediation.

## Scope

- Memorius CLI, MCP server, REST API, and agent hooks
- Local-first storage (ChromaDB, SQLite-vec)
- Not included: third-party agent integrations or LLM provider APIs

## Disclosure

We follow coordinated disclosure. Once a fix is ready, we'll:
1. Publish a patch release on PyPI
2. Add a GitHub Release with notes
3. Credit the reporter (unless you prefer to remain anonymous)
