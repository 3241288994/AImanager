# CodexManager 公共源码交付说明

生成日期：2026-08-31（Asia/Shanghai）

本目录已经整理为可建立全新 GitHub 历史的 CodexManager 公共源码。发布包由
`scripts/open-source/package.sh` 生成，位于 `dist-open-source/`；该目录被 Git 忽略，不会进入源码仓库。

## 已完成的公开边界

- 移除了个人联系、赞赏、推广和私有部署默认值；保留了 MIT 许可与上游来源说明。
- LabContext 管理连接默认只允许原生 loopback，或 Docker 的
  `host.docker.internal` 宿主机网关。个人 SSH Host 别名和端口转发不会被提交。
- Web Docker Compose 仅发布回环端口，使用非 root 容器、最小 capability、Docker secret
  和首次启动密码哈希；详细请求日志默认关闭。
- 桌面更新默认关闭。发布自己的 GitHub Release 后，维护者才可通过
  `CODEXMANAGER_UPDATE_REPO=owner/repository` 启用对应仓库的更新源。
- `plugins/codexmanager-connector` 是无连接 ID、无 MCP endpoint 的技能型模板。
  当前项目没有 `/mcp` 或公开的 `/v1`；不要把管理 RPC 或 LabContext 管理端注册为 MCP。
- 历史的插件市场、账号导入导出和 warmup RPC 不再注册到公开 Tauri invoke 表，避免暴露服务端已不支持的入口。
- 源码包会排除数据库、凭据、日志、构建缓存、Node/Rust 产物、Tauri 生成 schema、用户插件 `.app.json` 和原始交付压缩包。

## 本次验证

| 检查 | 结果 |
| --- | --- |
| 前端 lint | 通过 |
| 前端静态构建 | 通过；生成 `/`、`/sessions`、`/labcontext` |
| 前端运行时测试 | 29/29 通过 |
| Playwright 浏览器回归 | 1/1 通过 |
| Rust 工作区测试 | `cargo test --workspace --locked` 通过（服务库 933 项通过） |
| Tauri 桌面壳测试 | 49/49 通过 |
| 插件模板验证 | 通过 |
| Shell、Python 与 YAML 语法检查 | 通过 |
| 公开发布预检 | 通过；当前主机没有 Docker Compose，因此仅跳过 Compose 渲染 |
| 源码 tar.gz 内容检查 | 通过；未包含运行时或构建产物 |

完整命令与限制见 [VALIDATION_REPORT.md](VALIDATION_REPORT.md)。

## 推送到 GitHub 前仍需由维护者完成

1. 在 GitHub 创建空仓库，并确认仓库名称、维护者资料、品牌素材和许可归属。
2. 使用 gitleaks、trufflehog 或等价工具扫描当前工作树及全部待推送 Git 历史。
3. 在具备 Docker Compose 的干净主机按[服务器部署说明](docs/open-source/01-server-deployment.md)完成一次真实启动与 SSH 转发 smoke test。
4. 启用 GitHub 私密漏洞报告、Dependabot、分支保护和 CI 必需检查；若运营公开服务，再准备隐私政策、服务条款和事件响应渠道。
5. 首次桌面 Release 发布完成后，才为该发行版设置 `CODEXMANAGER_UPDATE_REPO`。公开 MCP 是独立里程碑，前提见 [Tunnel 与插件说明](docs/open-source/03-openai-plugin-and-tunnel.md)。

## 建立新仓库

```bash
git init -b main
git add .
git diff --cached --check
git commit -m "chore: prepare public open-source release"
git remote add origin https://github.com/your-account/AImanager.git
git push -u origin main
```

推送前再次运行 `scripts/open-source/preflight.sh`，并确认 `git status --ignored` 中的
`.env`、数据库、`target`、`node_modules` 与 `dist-open-source` 均没有被暂存。
