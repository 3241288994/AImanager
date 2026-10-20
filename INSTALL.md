# 安装：贴一个路径，让 ChatGPT 读懂本机和服务器项目

这份文件是 AImanager（原 CodexManager）面向人类与自动化 Agent 的统一安装入口。现有二进制名、
环境变量和数据路径保留兼容，见 [AI 接入与更名说明](docs/ai-connections.md)。安装完成后，用户可以直接把
授权范围内的本机或服务器绝对路径贴给 ChatGPT；Agent 负责在明确边界内完成大部分部署工作，只把
OpenAI 网页授权、秘密注入和高风险选择留给用户。

## 先选一种模式

| 模式 | 安装位置 | 能读取什么 | 适用场景 |
| --- | --- | --- | --- |
| `local` | 本机 Provider + Router + Tunnel | 本机授权目录 | 只研究本机项目 |
| `server` | 服务器 Provider；本机 Router + SSH bridge + Tunnel | 服务器授权目录 | 只研究服务器项目 |
| `hybrid`（推荐） | 本机与服务器各自安装 Provider；本机运行 Router + SSH bridge + Tunnel | 本机与服务器授权目录 | 用一个 ChatGPT 连接统一研究两端项目 |

Provider、Router、AImanager Web 和 Tunnel 是解耦组件。无需为了只使用一种模式而安装另外一端，
也不要把 Provider 的 `/admin`、AImanager 的 `/api/rpc` 或 SSH 端口当作 MCP endpoint。

## 一句话交给 Agent

把下面内容中的占位符换成自己的信息后，整段交给能操作目标电脑和服务器的编码 Agent：

```text
请安装或升级 https://github.com/3241288994/codexmanager 。

安装模式：<local | server | hybrid>
服务器 SSH Host：<使用 ~/.ssh/config 中的别名；local 模式删除本行>
本机允许读取的根目录：<绝对路径；server 模式删除本行>
服务器允许读取的根目录：<绝对路径；local 模式删除本行>

先完整阅读仓库中的 AGENTS.md、INSTALL.md，以及 INSTALL.md 指向的相关文档，再开始操作。
遵守 INSTALL.md 的 Agent 执行契约：先只读盘点与备份，再安装；复用已有 SSH 配置和密钥；
不得在对话、命令输出、日志或 Git 中显示 token、密码、API key 和私钥。
已有 AImanager / CodexManager、Provider、Router、Tunnel、数据库和配置不得直接覆盖。
遇到 OpenAI 页面授权或秘密注入时暂停并给我最短的人工操作说明，其余步骤继续自动完成。
最终运行全部验收项，并报告组件版本、监听地址、通过/失败项、备份位置和下一步。
```

升级已有部署时，建议再补一句：

```text
这是生产中的升级：只替换需要更新的组件，保留配置、token、数据库及其 inode/migrations；
部署前后分别记录校验值和 PID，失败时回滚，不要用新空配置覆盖现有配置。
```

## Agent 执行契约

如果你是执行安装的 Agent，请严格按以下阶段工作。不要因为用户给出了服务器地址，就跳过本机与
服务器的边界检查。

### 1. 只读盘点

1. 确认操作系统、CPU 架构、Python、Docker Compose、Git、SSH、Rust、Node/Corepack 的可用性；
   Provider 要求 Python 3.11+，并且只检查所选模式真正需要的依赖，不能只凭命令存在就判定可用。
2. 检查 `1455`、`1456`、`1460`、`48760`、`48761` 和 Tunnel 健康端口是否已被占用，并识别进程，
   不要仅凭端口打开就判断服务正确。
3. 检查已有安装、进程、systemd/launchd 服务、配置、token 文件和数据库。先记录状态与校验值，
   再创建带时间戳的备份。
4. 克隆或更新源码时保留用户改动。远端部署没有 Git 仓库时，使用“临时目录拉取 → 差异审查 →
   合并”，不要直接覆盖运行目录。

### 2. 按组件安装

只读取与所选拓扑有关的说明：

- AImanager Web/服务器：[服务器安全部署](docs/open-source/01-server-deployment.md)
- Provider 与路径授权：[Provider README](labcontext-provider/README.md) 和
  [`labcontext.example.toml`](labcontext-provider/labcontext.example.toml)
- Router、SSH bridge 和三种模式：[统一 LabContext Router](docs/labcontext-router.md)
- OpenAI Tunnel 与 ChatGPT 连接：[插件与 Tunnel](docs/open-source/03-openai-plugin-and-tunnel.md)

仓库提供两个稳定的组件安装入口：

```bash
# 在需要文件读取能力的每台电脑上安装独立 Provider
LABCONTEXT_PROVIDER_PYTHON=python3.12 ./scripts/install-labcontext-provider.sh

# 在控制 ChatGPT 连接的本机安装 Router/启动器
./scripts/install-labcontext.sh
labcontext init <local|server|hybrid> \
  --ssh-host <SSH_HOST> \
  --tunnel-profile labcontext
```

`local` 模式删除 `--ssh-host`；未准备 Tunnel 时也可以先不传 `--tunnel-profile`。初始化不会覆盖已有
Router 配置，除非用户明确授权使用 `--force`。Provider 配置必须复制到 Git 工作树之外并把
`registry.allowed_roots` 收窄到用户明确授权的现有目录；本机和服务器分别授权，不能把 `/`、用户
主目录或通配路径作为偷懒的默认值。

### 3. 人工检查点

以下步骤不得靠猜测：

1. 用户在 OpenAI Platform 创建或选择 Secure MCP Tunnel，并确认目标 organization/workspace；
2. 用户通过环境变量或权限为 `0600` 的私有文件注入 Tunnel runtime key；不要要求用户把 key
   粘贴到聊天中；
3. 在 ChatGPT Developer mode 的 Plugins 中创建/更新连接，Connection 选择 Tunnel；
4. 工具 schema 或描述更新后，重启对应服务，在 ChatGPT 中刷新插件元数据，并使用新会话测试。

Tunnel 是私有 MCP 与开发测试通道，不是公共插件发布地址。公开插件需要独立的公开 HTTPS MCP、
逐用户授权和额外的安全审计。

### 4. 验收，而不是“进程已启动”

至少验证以下结果：

```bash
# Provider：配置可解析，且能列出工作区
~/.local/opt/labcontext-provider/.venv/bin/labctx \
  --config ~/.config/labcontext/provider.toml workspaces

# Router：静态检查 + 真实 MCP/Provider/Tunnel 分层状态
labcontext doctor
labcontext status
labcontext repair

# Web 与连接中心
curl -fsS http://127.0.0.1:48761/__auth_status
curl -fsS http://127.0.0.1:1460/api/status
curl -fsS http://127.0.0.1:1460/api/recovery
```

还要在 ChatGPT 新会话中确认能看到 `inspect_path`，并分别对已授权来源进行一次真实读取；`hybrid`
模式必须各测一次 `source=local` 和 `source=server`。连接中心只有在 Router 身份、Provider 最低版本、
MCP 初始化、工具列表、真实工具调用、SSH 和 Tunnel 检查都通过后，才算“完全连通”。
降级时可以直接点击连接中心的“一键修复”；它会依次执行安全诊断、受控重启和真实能力复检。
安全检查失败时不会强行接管端口或修改凭据，而会显示具体原因和人工处理建议。

最后运行仓库级检查：

```bash
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
./scripts/open-source/preflight.sh
```

源码开发或发布还应按 [TESTING.md](TESTING.md) 执行相应前端、Rust、Playwright 和打包测试。若某项
无法运行，报告准确命令和原因，不能把“跳过”写成“通过”。

## 安装报告应当很短

Agent 最终只需给用户以下信息：

- 采用的模式，以及每个组件安装在哪台机器；
- Provider、Router、AImanager 和 Tunnel 的版本/状态；
- 哪些端口在回环地址监听；
- 验收命令的通过项与唯一未完成的人工步骤；
- 备份和回滚位置；
- 在 ChatGPT 中可直接复制的一条测试提示词。

详细命令、普通启动日志和无关依赖输出应留在本地报告中，不要淹没用户真正需要处理的事项。
