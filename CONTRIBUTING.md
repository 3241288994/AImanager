# Contributing

Thanks for contributing to AImanager.

## Development setup

Required tools: Node.js 20+, Corepack/pnpm 10.30.3, Python 3, and Rust stable. Desktop packaging additionally needs the platform dependencies required by Tauri v2.

```bash
corepack pnpm@10.30.3 -C apps install --frozen-lockfile
corepack pnpm@10.30.3 -C apps run lint
corepack pnpm@10.30.3 -C apps run build:desktop
corepack pnpm@10.30.3 -C apps run test:runtime
cargo test --workspace --locked -- --test-threads=1
```

## Ownership boundaries

- `apps/src/`: UI, typed frontend clients, runtime helpers, and tests.
- `apps/src-tauri/`: desktop shell and Tauri commands.
- `crates/core/`: SQLite migrations and shared persistence primitives.
- `crates/service/`: service RPC, account/session/LabContext behavior, and gateway code.
- `crates/web/`: authenticated Web shell and service proxy.
- `deploy/`, `docker/`, `scripts/`, `.github/`: packaging and delivery automation.

Read [AGENTS.md](AGENTS.md) before changing repository code. Changes inside `apps/` must also follow [apps/AGENTS.md](apps/AGENTS.md).

## Pull requests

- Keep a change focused; do not combine unrelated refactors, product behavior, and release automation.
- Add or update tests whenever behavior changes.
- Never commit `.env`, `auth.json`, database files, API keys, RPC tokens, LabContext tokens, browser traces, screenshots containing account data, or generated release artifacts.
- For gateway/protocol changes, cover both `/v1/responses` and `/v1/chat/completions`, streaming and non-streaming behavior, and tools when applicable.
- Update user-facing documentation and `CHANGELOG.md` when an interface, environment variable, deployment flow, or supported scope changes. In particular, do not add a default desktop update repository; releases must opt in through `CODEXMANAGER_UPDATE_REPO`.

Before opening a PR, run the narrowest relevant checks from [TESTING.md](TESTING.md) and `scripts/open-source/preflight.sh`.
