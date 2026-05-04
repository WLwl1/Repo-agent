# Security Policy

Repo Agent is a local repository investigation tool. Its default posture is conservative: inspect files, keep evidence traceable, and run only allow-listed verification commands.

## Supported Versions

Security fixes target the latest public release and the `main` branch.

## Reporting a Vulnerability

Please report security issues privately before opening a public issue. Include:

- the affected command or API endpoint
- the repository layout or minimal reproduction
- the expected boundary and the observed bypass
- whether a model, `.env` setting, or web studio endpoint was involved

## Security Boundaries

Repo Agent should:

- reject repository paths outside configured allowed roots
- block path traversal for file reads, reports, and static assets
- avoid reading or writing `.env` files through agent tools
- ignore generated run/cache/report/log directories during indexing
- run verification commands with `shell=False` and an allow-listed executable
- require explicit confirmation before applying workspace-run edits back to source

Repo Agent is not a sandbox for arbitrary untrusted code. Only point it at repositories you are willing to inspect locally.

