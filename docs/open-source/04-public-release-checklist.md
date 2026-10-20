# 公开发布检查清单

本清单面向首次推送到 GitHub 和之后每次 Release。`scripts/open-source/preflight.sh` 是
仓库内的快速门禁；它不能替代对完整 Git 历史的独立秘密扫描。

## 发布前必须完成

- 确认项目名称、GitHub 仓库 URL、维护者联系方式和品牌素材均已获得授权。
- 保留 MIT `LICENSE` 与 `NOTICE` 中的上游来源说明；核对第三方代码、字体、图标和图片的
  许可证。
- 确认没有赞赏码、群二维码、个人联系方式、个人推广链接或不希望公开的部署地址。
- 阅读 [README](../../README.md)、[部署说明](01-server-deployment.md) 和
  [Tunnel/插件说明](03-openai-plugin-and-tunnel.md)，确保支持范围与实际代码一致。
- 在干净环境重新安装依赖并运行：

  ```bash
  corepack pnpm@10.30.3 -C apps install --frozen-lockfile
  corepack pnpm@10.30.3 -C apps run lint
  corepack pnpm@10.30.3 -C apps run build:desktop
  corepack pnpm@10.30.3 -C apps run test:runtime
  corepack pnpm@10.30.3 -C apps run test:e2e
  cargo test --workspace --locked -- --test-threads=1
  cargo test --manifest-path apps/src-tauri/Cargo.toml --locked --lib
  scripts/open-source/preflight.sh
  ```

- 在发布首个桌面安装包之前确认 `CODEXMANAGER_UPDATE_REPO=owner/repository` 指向新仓库；未发布前应保持为空。不要把上游仓库设为默认更新源。

- 如具备 Docker，渲染并启动一次安全 Compose，再通过 SSH 转发做最小 smoke test：

  ```bash
  cp deploy/.env.example deploy/.env
  # 先按 01-server-deployment.md 创建私有 Web 密码文件并填写其绝对路径。
  docker compose --env-file deploy/.env -f deploy/docker-compose.self-hosted.yml config
  ```

- 用 gitleaks、trufflehog 或等价工具扫描工作树和全部待公开 Git 历史。
- 启用 GitHub 私密漏洞报告、Dependabot、分支保护和所需状态检查；为发行版本建立签名、
  变更记录和可复现打包流程。
- 若运营公开服务，另行补齐隐私政策、服务条款、数据删除、凭据轮换和事件响应流程。

## 不应进入仓库或 Release

- `data/`、数据库、SQLite 备份、账号导入导出文件；
- `.env`、`auth.json`、RPC token、OpenAI/API Key、Tunnel 运行时凭据、LabContext admin token；
- 请求日志、浏览器自动化记录、视频、截图中的真实账号数据；
- `target/`、`node_modules/`、`.next/`、`apps/out/`、`dist-open-source/` 等可重建产物；
- `.app.json`、用户专属插件连接、服务器 `.git` 目录和未审计的旧 Git 历史。

## 建立 GitHub 仓库

在项目根目录确认预检通过后，创建全新的 Git 历史：

```bash
git init -b main
git add .
git status --short
git commit -m "Initial open-source release"
git remote add origin https://github.com/your-account/AImanager.git
git push -u origin main
```

推送前再次执行 `git status --ignored`，确认任何真实 `.env`、数据库、账号文件、`target`、
`node_modules` 和构建输出都未被暂存。不要把现有服务器工作目录的旧 `.git` 目录直接推送。

## 创建源代码 Release 包

```bash
scripts/open-source/package.sh CodexManager-open-source
tar -tzf dist-open-source/CodexManager-open-source.tar.gz
```

脚本会先执行公开预检，再生成仅含源码的确定性 tar.gz 及 SHA-256 文件。上传前检查压缩包
列表，确保没有数据库、token、个人连接配置或构建缓存。

## 建议分阶段发布

1. 先发布自托管源码、私有 SSH 部署方式和技能型插件。
2. 再发布经过安全评审的独立 MCP 服务和开发者模式测试指南。
3. 最后才提供公共托管 MCP；上线前完成逐用户授权、滥用防护、监控和应急预案。
