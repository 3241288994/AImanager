# 本地电脑接入

## 当前公开版的客户端边界

当前公开版不提供 OpenAI 兼容 `/v1` 网关，因此不要把
`http://127.0.0.1:48761/v1` 配置为 Codex CLI 的 `base_url`，也不要将管理 RPC、账号 token、
`codexmanager.rpc-token` 或 LabContext admin token 当作 API Key。

请继续使用 Codex CLI 的官方登录与配置方式；AImanager 负责在服务器上管理已获授权的
账号、额度信号、会话恢复和 LabContext 工作区。若要让 ChatGPT 网页使用服务器科研工具，请按
[Tunnel 与插件教程](03-openai-plugin-and-tunnel.md)部署独立、受审计的 MCP 适配层。

本机的 `auth.json`、`config.toml` 与任何登录凭据只属于当前用户，绝不能复制到本仓库、插件
目录、截图或 issue 中。

## 本地开发

要求：Node.js 20+、Corepack、Python 3 和 Rust stable。桌面打包还需要对应平台的 Tauri
依赖。

```bash
corepack pnpm@10.30.3 -C apps install --frozen-lockfile
corepack pnpm@10.30.3 -C apps run build
corepack pnpm@10.30.3 -C apps run test:runtime
corepack pnpm@10.30.3 -C apps run test:e2e
cargo test --workspace --locked -- --test-threads=1
```

本仓库不携带 `node_modules`、Rust `target`、Next.js 输出、数据库或运行时凭据；它们应在
自己的开发环境中重新生成。提交或发布前运行：

```bash
scripts/open-source/preflight.sh
```

该脚本会拒绝常见的秘密、数据库、个人插件连接和已知个人部署引用；它不能替代对最终
Git 历史运行的专用秘密扫描器。

## 桌面端更新源

公开源码不会预置任何更新仓库。你创建自己的 GitHub Release 后，才为桌面端进程设置
`CODEXMANAGER_UPDATE_REPO=owner/repository`，然后重启应用。留空时更新检查与下载准备会明确
提示尚未配置，而不会访问上游项目。预发布更新也必须显式设置
`CODEXMANAGER_UPDATE_PRERELEASE=1`。
