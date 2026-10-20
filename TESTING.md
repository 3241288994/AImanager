# Testing

## Frontend and desktop shell

```bash
corepack pnpm@10.30.3 -C apps install --frozen-lockfile
corepack pnpm@10.30.3 -C apps run build:desktop
corepack pnpm@10.30.3 -C apps run test:runtime
corepack pnpm@10.30.3 -C apps run test:e2e
```

`test:runtime` validates the maintained browser/desktop transport surface, command registration, local-workspace security boundaries, analytics calculations, and key utility behavior. `test:e2e` builds the static export and exercises the five maintained routes with mocked service responses, including OAuth handoff, cross-page account state, recovery, quota provenance, and the Web-mode block on local folder access. It also captures the README demo screens in `apps/test-results/readme-*.png`; these are not live-account verification. `test:navigation` runs the route and cross-page synchronization subset. Install Playwright browsers when prompted by Playwright.

## Rust

```bash
cargo test --workspace --locked -- --test-threads=1
cargo test -p codexmanager-core --locked usage_analytics --lib
cargo test -p codexmanager-service --locked usage_analytics --lib
cargo test -p codexmanager-service --locked labcontext::tests
cargo test -p codexmanager-web --locked
cargo test --manifest-path apps/src-tauri/Cargo.toml --locked --lib -- --test-threads=1
```

For gateway or protocol changes, add targeted coverage for responses and chat-completions endpoints, streaming and non-streaming flows, and tool calls.

The workspace and desktop commands intentionally use one test thread: the service suite switches
between isolated SQLite files, and desktop tests select home-directory settings through
process-wide environment variables. This keeps the documented commands and CI deterministic.

The desktop updater is intentionally disabled until `CODEXMANAGER_UPDATE_REPO=owner/repository` is configured. Keep it unset in development and public-source checks unless you are testing your own GitHub Release feed.

## LabContext Provider

Use Python 3.11 or newer. The suite includes real generated HTML/PDF fixtures,
direct-path safety checks, MCP tool-schema coverage, and document pagination.

```bash
python3.12 -m venv /tmp/labcontext-provider-test
/tmp/labcontext-provider-test/bin/pip install './labcontext-provider[dev]'
/tmp/labcontext-provider-test/bin/pytest -q labcontext-provider/tests
```

## Container and release checks

```bash
scripts/open-source/preflight.sh
docker compose --env-file deploy/.env -f deploy/docker-compose.self-hosted.yml config
scripts/open-source/package.sh CodexManager-open-source
```

Compose 配置和启动需要 `CODEXMANAGER_WEB_ACCESS_PASSWORD_FILE_HOST` 指向私有密码文件；按 [服务器部署说明](docs/open-source/01-server-deployment.md) 创建它。预检在 Docker 可用时会使用临时空文件仅验证 Compose 语法，不能替代真实 secret 的启动测试。

The preflight script requires ripgrep (`rg`) and intentionally fails when it finds runtime secrets, user-specific plugin registrations, personal deployment references, or known personal/promotional assets. Missing ripgrep stops validation rather than silently skipping secret checks.
