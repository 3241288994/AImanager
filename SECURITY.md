# Security Policy

## Supported scope

Please report vulnerabilities in AImanager itself, especially issues involving account tokens, API/platform keys, RPC tokens, Web authentication, local gateway authorization, LabContext admin access, sensitive logging, or desktop/Web/service privilege boundaries.

## Reporting a vulnerability

Do not publish working exploits, valid credentials, private account data, or detailed reproduction steps in a public Issue.

Use GitHub's private vulnerability reporting for this repository when it is enabled. If it is unavailable, open a minimal public Issue containing only the impact and ask the maintainer for a private reporting channel. Do not include any secret in that Issue.

Useful reports include the affected version, impact, prerequisites, sanitized reproduction steps, and redacted logs or screenshots.

## Data handling rules

Never commit or publish:

- OpenAI access, refresh, or ID tokens; cookies; API keys; platform keys; or passwords.
- `auth.json`, `codexmanager.rpc-token`, LabContext admin tokens, `.env` files, SQLite data, account imports/exports, or browser automation traces.
- Raw request bodies, account identifiers, or screenshots that could expose credentials.

Default deployment is loopback-only. If you intentionally expose a service beyond loopback, you are responsible for TLS, strong authentication, network access control, rate limits, request-size limits, redacted logs, and incident response.
