# OpenAI 插件与 Secure MCP Tunnel

## 当前仓库的边界

AImanager service 提供 Web 管理、内部 RPC 和可选 LabContext 管理适配，但**它自身不实现
MCP endpoint，也不暴露 OpenAI 兼容 `/v1` 网关**。仓库另带一个可选、独立运行的
LabContext Router，它在 `127.0.0.1:1460/mcp` 聚合已经存在的 LabContext Provider。因此：

- 不要把 `/api/rpc`、`/rpc`、LabContext 管理端或个人 SSH 端口转发填入 ChatGPT 的 MCP 地址。
- Secure MCP Tunnel 只能把已有的 MCP server（包括可选 Router）安全连接到 OpenAI；它不会把
  普通 REST 或 AImanager 管理 RPC 转换成 MCP。
- `plugins/codexmanager-connector` 是一个可公开分发的**技能型插件模板**。它不含 MCP
  连接、Tunnel ID、运行时 API Key 或用户专属 `.app.json`。

官方文档明确说明：Tunnel 适用于私有 MCP 连接和开发者模式测试，不用于公共插件提交或
分发；公开插件需要稳定、可公开访问的 HTTPS MCP endpoint。参见
[Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)。

## 私有开发：为独立 MCP 服务建立 Tunnel

只有在你已经启动并验证了 MCP 服务时，才使用本节。它可以是单独部署的服务，也可以是仓库的
可选 LabContext Router。该服务应只暴露经过筛选、低权限、有输入 schema 的工具；账号切换、
删除、密钥读取、凭据导入等管理动作不应成为默认模型工具。

1. 先在同一私有网络中启动 MCP 服务，并用 MCP Inspector 验证工具列表、参数、鉴权、错误
   和确认行为。HTTP 服务通常使用 `/mcp`；也可以是 stdio 服务。
2. 在 OpenAI Platform 的 Tunnel 设置中创建或选择 Tunnel，获得 `tunnel_id`，并把
   `tunnel-client` 的运行时 API Key 存入秘密管理器。运行 `tunnel-client` 的身份需要对应
   的 Tunnel 权限；ChatGPT developer mode 权限是另一套工作区权限。
3. 在能访问该 MCP 服务的主机上配置并检查 Tunnel。例如 HTTP MCP 服务可使用：

   ```bash
   export CONTROL_PLANE_API_KEY="$(your-secret-manager-read-command)"
   tunnel-client init \
     --profile codexmanager-private \
     --tunnel-id tunnel_your_id \
     --mcp-server-url http://127.0.0.1:3000/mcp
   tunnel-client doctor --profile codexmanager-private --explain
   tunnel-client run --profile codexmanager-private
   ```

   运行进程需要出站 HTTPS 到 OpenAI，且能在本地访问 MCP 服务；不需要入站公网端口。不要将
   runtime API Key、`tunnel_id`、配置 profile 或 `tunnel-client` 日志提交到 Git。
4. 在 ChatGPT 中启用 developer mode，打开 Plugins，点击加号创建开发者模式 app。在
   Connection 中选择 **Tunnel**，选取可见 Tunnel 或输入已有的 `tunnel_id`，再检查发现的
   工具和元数据。
5. 用新会话运行正向、负向、鉴权失败和需要确认的写操作测试。更新工具 schema、描述或
   鉴权后，重启服务并在连接界面刷新元数据。

Tunnel 必须与目标 Platform organization 和 ChatGPT workspace 关联；若只关联了个人
Platform organization，它不一定会出现在 Enterprise/Edu 工作区。完整的权限、网络和
排障要求见 [官方 Tunnel 指南](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
与 [连接和测试插件指南](https://developers.openai.com/plugins/deploy/connect-chatgpt)。

## 与 LabContext 的关系

`LABCONTEXT_ADMIN_URL` 仅供 AImanager 的管理适配使用。无论它指向同机 loopback、
Docker 宿主机网关还是私有转发，它都不是 MCP 地址。若要让 ChatGPT 使用科研工具，可让
Tunnel 直接连接单个 LabContext `/mcp`，也可使用可选 Router 聚合多个 LabContext；不要把
`/admin` 当成模型工具地址。

### 本地电脑上的工作区

AImanager 桌面版可以通过回环适配直接管理本机 LabContext，但这仍只是管理连接。若要让
ChatGPT 网页使用本机项目，需要在本机运行 MCP endpoint 和 Tunnel。统一 Router 可让一条
Tunnel 同时路由本机与 SSH 转发后的服务器 Provider，同时保持两套 Provider 独立安装。配置见
[统一 LabContext Router](../labcontext-router.md)，目录授权见[本地工作区](../local-workspaces.md)。
兼容 Provider 暴露 `inspect_path` 后，ChatGPT 也可以直接读取其 `registry.allowed_roots` 下的本机
或服务器绝对路径，无需先注册工作区；hybrid 模式下应在提示词中明确来源。仓库内的独立
Provider 0.9.0 支持常见代码、配置、日志、HTML、文本型 PDF、DOCX、XLSX、PPTX 和 IPYNB；
PDF 可按页续读或搜索，扫描件会返回需要 OCR，Office/Notebook 内容只提取而不执行。
本机与服务器 Provider 可分别安装，不要求同时启用。

## 插件模板的使用方式

公开仓库中先验证技能型插件的 manifest 和公开边界：

```bash
python3 -m json.tool plugins/codexmanager-connector/.codex-plugin/plugin.json >/dev/null
scripts/open-source/preflight.sh
```

再使用 Codex 内置的 `plugin-creator` 验证器，或按
[官方插件构建文档](https://developers.openai.com/codex/build-plugins) 安装到本地 marketplace
后在新会话测试。技能型插件不需要 MCP 连接即可测试。

如果未来独立 MCP 服务已经完成并在 OpenAI 中注册了兼容连接，请先复制
`plugins/codexmanager-connector` 到 Git 工作树之外。该副本中的
`scripts/configure_registered_connection.py` 只帮助写入本地 `.app.json` 和 manifest 映射；
它**不会**创建 Tunnel、注册 ChatGPT 连接或验证 MCP 服务。不要把这个私有副本、`.app.json`
或注册 ID 提交回来。

## 公开插件的前提

在提交公共插件前，独立 MCP 服务必须具备：

- 稳定的公开 HTTPS MCP endpoint（通常为 `/mcp`），而非 Secure MCP Tunnel；
- OAuth 或等价的逐用户授权和最小 scope；
- 服务端参数校验、限流、超时、幂等保护和工具级确认；
- prompt injection 防护与不可信内容隔离；
- 日志脱敏、隐私政策、服务条款和安全响应渠道。

先开源和维护自托管 AImanager 源码与技能型插件；独立 MCP 层经过设计、测试和安全审计后，
再作为单独里程碑发布。
