# 统一 LabContext Router

CodexManager 可以把相互独立的本机 LabContext 和服务器 LabContext 放在一个可选 Router 后面，
同时保持安装方式解耦：只装本机、只连服务器、两者并用都使用同一套命令和同一个 MCP 地址。

```text
ChatGPT 网页版 ─ Secure MCP Tunnel ─┐
                                    ├─ 127.0.0.1:1460/mcp (Router)
CodexManager Web 控制台 ────────────┘       ├─ local Provider  ─ 本机目录
                                             └─ server Provider ─ SSH 转发 ─ 服务器目录
```

Router 不包含 LabContext 本身，也不要求 Provider 由同一种方式安装。每个 Provider 只需提供兼容的
`/mcp`；需要在 CodexManager Web 页面管理工作区时，再为它配置 `/admin` 和私有 token 文件。

## 安装与初始化

要求 Python 3.9+。安装脚本只复制两个零依赖 Python 文件，不会安装或启动任何 Provider：

```bash
scripts/install-labcontext.sh
```

选择符合需要的模式进行一次性初始化：

```bash
# 仅本机
labcontext init local --tunnel-profile labcontext

# 仅服务器；SSH Host 可以是 ~/.ssh/config 中的别名
labcontext init server --ssh-host your-server --tunnel-profile labcontext

# 本机 + 服务器
labcontext init hybrid --ssh-host your-server --tunnel-profile labcontext
```

生成的文件是：

- `~/.config/labcontext/config.toml`：Provider、端口和允许访问 Router 的 Web Origin；
- `~/.config/labcontext/launcher.env`：可选 SSH/Tunnel 进程设置，权限自动设为 `0600`。

初始化不会覆盖已有配置；确实需要重建时才使用 `--force`。仓库中的
`deploy/labcontext-router.example.toml` 展示了完整双 Provider 配置。

## Provider 端口

| 端口 | 用途 |
| --- | --- |
| `1455` | server Provider，或单 Provider 模式下的 LabContext |
| `1456` | hybrid 模式下的 local Provider |
| `1460` | 统一 Router 的 `/mcp`、健康检查和本机 Web 管理桥 |
| `48761` | CodexManager Web UI；服务器模式下可由同一 SSH 连接转发 |

在 hybrid 模式中，本机和转发后的服务器端口不能冲突。若本机 LabContext 仍监听 `1455`，请将它
改到 `1456`，或相应修改 `config.toml` 与 `launcher.env` 中的 server 转发端口。

每个启用了管理桥的 Provider 都要有对应 token 文件。token 不应写入 TOML、Git 或浏览器；
Router 只从 `admin_token_file` 读取它，并只监听 IPv4 回环地址。

需要指定 SSH identity、绕过个人 SSH config，或保留服务器到本机代理的反向转发时，可在私有
`launcher.env` 设置 `LABCONTEXT_SSH_IDENTITY_FILE`、`LABCONTEXT_SSH_CONFIG_FILE`、
`LABCONTEXT_SERVER_PROXY_REMOTE_PORT` 与 `LABCONTEXT_LOCAL_PROXY_PORT`。已有 API-key 文件可通过
`LABCONTEXT_SECRET_ENV_FILE` 引用，不需要复制密钥内容。

启用反向代理转发时，SSH bridge 默认在服务器写入
`~/.local/state/labcontext/ssh-bridge-<端口>.pid`，用于一键修复时验证残留会话归属。需要调整位置可在
私有 `launcher.env` 设置 `LABCONTEXT_SSH_REMOTE_STATE_FILE`；该文件只记录远端 shell PID，不包含密钥。

## Tunnel 与日常启动

Tunnel profile 应指向 Router，而不是某个 Provider：

```bash
tunnel-client init \
  --profile labcontext \
  --tunnel-id tunnel_your_id \
  --mcp-server-url http://127.0.0.1:1460/mcp
```

把 `CONTROL_PLANE_API_KEY` 注入当前环境，或写入权限为 `0600` 的私有
`launcher.env`。先检查配置，再启动全部已启用组件：

```bash
labcontext doctor
labcontext
```

`labcontext` 会按配置启动 SSH 转发、Router 和 Tunnel，并在退出时回收这些子进程。Provider
默认仍由各自的 launchd、systemd、Docker 或手工命令管理；若希望同一命令顺便启动独立安装的
local Provider，可在 `launcher.env` 设置不经过 shell 展开的
`LABCONTEXT_LOCAL_PROVIDER_COMMAND`。原有个人启动脚本可以保留，确认新 profile 可用后再停用。

启动命令是幂等的：如果兼容的 Router 已经运行，它只会显示当前连接中心地址，不会再启动一套
Provider、SSH、Router 和 Tunnel。可随时获取分层诊断：

```bash
labcontext status
labcontext doctor
labcontext repair
```

`status` 不只检查端口，还会核对 Provider 身份与最低版本、执行 MCP 初始化、读取工具清单、调用一次
`list_workspaces`，并检查管理接口、SSH 子进程和 Tunnel `/readyz`。启动器运行记录默认写入
`~/.local/state/labcontext-router/launcher-status.json`，其中只包含 PID、状态和退出码，不包含命令行、
token 或其他凭据。一键修复状态和日志默认写入同目录的 `recovery-status.json` 与 `recovery.log`。
可用 `LABCONTEXT_STATUS_FILE`、`LABCONTEXT_RECOVERY_STATUS_FILE`、
`LABCONTEXT_RECOVERY_LOG_FILE`、`LABCONTEXT_TUNNEL_HEALTH_URL` 与
`LABCONTEXT_DASHBOARD_URL` 调整对应地址。local Provider、SSH 或 Tunnel 异常退出时，Router 与连接
中心会继续运行，启动器采用有上限的退避自动重试；因此可以看见真实错误，而不是整套服务反复消失。
SSH bridge 退出且确认反向端口冲突时，监督器会自动尝试一次带 PID 标记的安全清理并复验端口，
成功后重连，无需手动运行 repair。每个启动器生命周期最多清理一次，避免与另一台电脑反复抢占。
标记缺失、身份不匹配或清理后仍冲突时，会停止该桥接的重复重试，将原因写入连接中心修复状态；
本地 Provider 和 Router 保持运行。解决提示中的问题后，点击“一键修复”或运行 `labcontext repair`。

当 Router 仍在但某个子链路已经失效时，重复执行裸 `labcontext` 不会启动第二套进程。此时：

- `labcontext doctor` 会真实执行 SSH 登录检查；桥接未运行时还会单独验证反向转发端口，因此能够区分认证失败、超时、依赖缺失和远端端口被旧会话占用；
- `labcontext repair` 会自行完成安全检查，并用当前配置重建完整链路；新版 SSH bridge 会在服务器留下
  仅当前用户可写的 PID 标记，确认远端端口属于自己残留的会话后才能自动清理，不会按端口盲目杀进程；
- 清理远端会话后会短暂等待端口释放，并识别是否已有新的健康 LabContext 启动器接管该端口，避免把
  正常的并发启动或端口交接误报成修复失败；
- 如果监督器意外退出但子进程仍在，修复只会停止状态文件中 PID、进程组和预期命令全部吻合的
  Provider、SSH、Router 与 Tunnel；任一身份不匹配就中止，不会接管普通用户进程；
- `labcontext restart` 无条件重新加载当前配置，`labcontext stop` 则只做干净退出；两者都拒绝向无法验证为 LabContext 启动器的 PID 发信号。

SSH 主机可以填写 `~/.ssh/config` 中的别名。启动器会沿用该别名的 `HostName`、`User`、密钥、
跳板机和算法设置；如果别名已经声明了相同端口的 `LocalForward` / `RemoteForward`，不会再追加重复转发。
不要把 `LABCONTEXT_SSH_CONFIG_FILE=/dev/null` 与依赖 SSH 别名的配置同时使用。

## ChatGPT 中的调用方式

兼容 Provider 暴露 `inspect_path` 时，可以直接粘贴绝对路径，无需注册工作区：

```text
请读取本地电脑的 /Users/me/Desktop/project/README.md 并总结。
请列出服务器 /srv/research/project 下两层目录，并找出主要入口文件。
```

Router 会将 `source=local` 或 `source=server` 交给对应 Provider。hybrid 模式下必须明确来源；
只配置一个 Provider 时可以省略。可访问范围由对应 Provider 的 `registry.allowed_roots` 决定，
目录返回深度和条目数受限，凭据、不支持的二进制、大文件和拒绝规则仍然生效。Provider 0.9.0
统一支持常见代码、配置、日志、HTML、文本型 PDF、DOCX、XLSX、PPTX 和 IPYNB；不会执行宏、
公式或 Notebook 代码。PDF 支持页码范围和搜索，扫描件会报告需要 OCR。

需要长期项目上下文时，再调用 `list_workspaces`。Router 会给每个结果增加稳定的
`workspace_ref`，例如 `local:paper-a` 或 `server:paper-a`。之后将这个值传给
`workspace_overview`、`research_context` 等工具；异步任务返回的 `job_id` 也会带 Provider 前缀。

当只有一个 Provider 暴露某工具时，Router 可以自动选择它；当两个 Provider 中存在同名
`workspace_id` 时，必须使用 `workspace_ref`，以免查询到错误电脑上的项目。某个 Provider 临时
离线不会阻止另一个 Provider 的工作区被列出，返回结果会同时标记各来源状态。

路径直读与工作区互不替代：前者适合临时查看，后者提供项目概述、证据索引、实验、研究图和
Codex 会话衔接。统一 Router 要求 Provider 至少为 `0.7.0`，并且提供 `list_workspaces` 与
`inspect_path`；不兼容的 Provider 会明确显示为不可用，不会仅因端口可连接而被误判为正常。

## Web 控制台

浏览器打开 `http://127.0.0.1:48761/labcontext/` 时会探测
`http://127.0.0.1:1460/api/status`。页面内置的连接中心分别显示 Router、Provider、SSH 子进程和
OpenAI Tunnel：全部通过后自动收起并进入正常工作区界面，出现降级或失败时保持展开，支持重新检测
和复制脱敏诊断。降级时可以点击“一键修复”：网页只请求浏览器本机回环地址上的 Router，独立恢复
进程会先运行安全诊断，检查通过后才停止已验证的旧监督器、重建连接并执行真实能力复检。SSH 密钥
错误、网络超时等无法安全自动处理的情况不会强行接管，而会显示失败阶段、原始原因、原因代码和
人工建议。带有效托管标记的服务器反向端口残留会自动清理；旧版或第三方会话没有标记时仍拒绝接管。
Router 重启期间页面会持续轮询恢复状态。

恢复接口只有回环 Router 提供：`POST /api/recovery/repair` 创建任务，`GET /api/recovery` 读取结果。
接口仍受精确 Origin 限制，不应将 Router 暴露到局域网或公网。Router 本身无法访问时，网页无法发起
修复，需在终端单独运行 `labcontext repair`。`repair` 已包含诊断；不要用 `doctor && repair`，否则
`doctor` 发现故障后的非零退出码会阻止 Shell 执行修复。
如果 `local` Provider 的 MCP 和 admin 都可用，页面会自动解锁“本地电脑”；
不需要切换到 Tauri 桌面版。桌面版仍保留原生目录选择器，Web 版则要求填写运行 local Provider
的电脑能够访问的绝对路径。

如果 CodexManager Web 使用了其他 Origin，必须把精确 Origin 加入 `cors_origins` 后重启
Router。不要使用通配 Origin，也不要把 `1460`、Provider 的 `/admin` 或 token 暴露到局域网或
公网。

## 故障定位

```bash
labcontext doctor
labcontext status
labcontext repair
labcontext restart
labcontext stop
curl -fsS http://127.0.0.1:1460/healthz
curl -fsS http://127.0.0.1:1460/api/status
```

`/healthz` 用于 Router 存活检查，`/api/status` 才是完整就绪诊断。后者会分别显示 `local` /
`server` 的身份、版本、MCP、真实工具调用与 `adminStatus`，并报告启动器子进程和 Tunnel 状态。
常见问题是 Provider 未启动或版本过旧、SSH 转发端口冲突、admin token 文件路径错误，或 Tunnel
profile 仍指向旧的 `1455/mcp`。
