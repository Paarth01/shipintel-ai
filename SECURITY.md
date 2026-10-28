# Security policy

ShipIntel AI is an independent portfolio project (synthetic data, rule-based extraction). Reports are still welcome.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's private reporting:
**Security tab -> "Report a vulnerability"** on this repository.

Include: what you found, how to reproduce it (a minimal input is ideal), the version/commit, and the impact you expect.
You can expect an acknowledgement within a few days; this is a personal project, so there is no bounty and no SLA.

## Supported versions

Only the latest commit on `main` is maintained.

## What has already been looked at

A self-audit and remediation (resource exhaustion, request-size limits, authentication, UI injection, dependency CVEs) is documented in
[`docs/audit_remediation.md`](docs/audit_remediation.md), with residual risks and the independent-review package in
[`docs/security_review_checklist.md`](docs/security_review_checklist.md). **No independent review has been performed.**
