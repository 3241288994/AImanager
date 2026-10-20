# AImanager：AI 接入与更名兼容说明

AImanager 是 CodexManager 的新产品名称。现有账号、数据库、LabContext 和服务部署保持兼容。

## AI 接入中心

打开 `/connections/`。这是管理员功能，沿用现有 RPC 身份验证与角色检查；普通成员不能查看或修改配置。
「服务主机」指运行 AImanager Service 的机器，网页所在电脑不一定是这台机器。

- 官方 CLI：检查服务进程 PATH 中的 `codex`、`claude`、`agy`；显示官方登录命令和说明。
  安装检测不读取凭证、不启动 CLI，也不假装已经登录。Claude / Antigravity 可使用下方托管登录，
  Codex 及现有非托管配置继续在 SSH 终端登录。
- API：添加、编辑、删除入口，启用或停用管理检测。停用不会停止第三方账号池。
- 检测：请求 `GET /v1/models`；Gemini client 入口还检查 `GET /health`。模型 ID 来自实时返回，
  不把网页服务的模型别名当作已验证的官方型号。原始健康 JSON 不返回浏览器。
  账号池摘要仅显示可用账号数、编号、白名单状态与冷却秒数，不显示账号 ID、邮箱或任意原始字段。
- 不发送生成请求、不自动重放失败请求，也不宣称模型目录探测等于生成成功。
- 「多账号与统一额度」：为 Claude / Antigravity 创建独立私有配置，通过受限的官方 CLI OAuth 会话
  打开官方授权页并提交返回码；验证后可切换默认账号。切换只影响新启动的托管 CLI，不打断已有任务。
- 额度刷新只执行官方 `/usage`，不提交模型问题。能读取到的百分比按原时间窗口展示，附来源与采集时间；
  未提供的重置时间、Token、费用或不兼容额度格式均显示未知，不拼接成虚假的统一余额。
  Codex 额度/用量保留在原页面；不同平台百分比不可直接相加，总览统计账号数和快照覆盖数。
  第三方网页账号轮询、限流和恢复仍由原账号池负责。

## Gemini 网页账号池

默认入口根据服务主机生成：Mac `http://127.0.0.1:6969/v1`，其他系统
`http://127.0.0.1:16969/v1`。可编辑并持久保存。首次未保存时显示默认项；删除最后一项后保持为空。

选择 `gemini-web-client` 凭证来源：

- Linux：`~/.config/gemini-web-client/client.env`
- Mac：`~/.local/share/gemini-web-pool/server-client/client.env`
- 只解析 `GEMINI_WEB_API_KEY`，不会执行或 source 文件；最大 32 KiB，Unix 权限须为 0600。
- 配置文件本身不包含在数据库或 RPC 返回中。API 密钥仅用于后端请求的 Authorization 头。

服务器的 16969 入口依赖 Mac 在线、账号池运行及其独立反向 SSH 通道。LabContext 桥接健康不能
证明此通道健康。账号恢复或验证码请在原账号池界面处理，不将 Cookie / 密码上传服务器。

其他私有反代可选择 `aimanager-env`，在**服务进程环境**配置 `AIMANAGER_UPSTREAM_API_KEY` 后
重启 Service。此变量默认未设置，只被对应入口的显式探测读取，不覆盖任何现有 app setting。
该来源目前共用一个密钥，不适合需要不同密钥的多个上游；不得把密钥填到 URL、名称或 ID 中。

仅支持数字回环地址 `127.0.0.1` / `[::1]`、`/v1` 路径，拒绝内嵌用户名、密码、查询参数和重定向。
远端 API 需要先建立受控的 SSH 通道。不自动启动或修改现有通道、代理与账号池。

入口元数据保存在既有 app settings 的 `aimanager.connections.v1`，无新数据库迁移；修改即时生效，
桌面、Web 和 Service 使用同一套 RPC。只升级 Web 无法获得新后端能力，需配套升级 Service。

## 官方登录入口

AI 接入页直接显示 Claude / Antigravity 的实际登录状态，不再要求先填写平台、备注或创建空账号。
点击「网页登录」即可使用尚未登录的独立配置；「登录其他账号」会按需创建另一份隔离配置。
在弹出的官方域名页面由本人完成认证。
如官方 CLI 要求返回码，把它粘贴到页面的密码型返回码输入框；输入不保存在浏览器存储或日志中，
只转交当前 CLI。页面刷新可恢复当前会话 ID。取消会话只停止本次受管 CLI，不删除账号凭证。
授权会话最长 15 分钟，额度会话最长 60 秒，最多同时 4 个。网页不能提交任意终端命令。

Claude 使用独立 `CLAUDE_CONFIG_DIR`；两个平台均使用独立的进程级 HOME/XDG 目录，不继承
服务进程的 API key、路由配置、项目 hook 或桌面 keyring。Antigravity 托管账号目前限 Linux
无桌面 keyring 环境；Mac 上拒绝创建这类账号，避免同一个系统钥匙串使多个目录串号。
Python 3.8+ 是托管会话的运行依赖；Windows 托管会话暂不支持。

两个页面共用登录状态：每 15 秒读取状态，返回浏览器窗口时重新同步。官方 CLI 状态检查
最多每 60 秒执行一次，每批最多 4 个账号；手动「同步登录状态」可主动验证。Claude 读取
官方 `auth status`；Antigravity 核对当前隔离配置内官方 OAuth 记录的结构、期限与权限，
兼容 RFC3339 纳秒时间戳，不再只凭终端成功文案判定。此处「已登录」表示官方凭证已保存，
不等于网络、订阅权限或模型生成已验证；这些仍通过额度/连接检查分别报告。

「账号与额度」首页提供 Codex / Claude Code / Antigravity 三个平台页签，分别展示账号、
默认配置和额度快照。账号切换仍需显式选择；同步不会自动替你切换默认账号或覆盖原凭证。

托管配置默认位于 `~/.local/state/aimanager`，目录 0700、文件 0600。可通过服务端启动变量
`AIMANAGER_STATE_DIR` 指定绝对路径；`AIMANAGER_CLAUDE_BIN`、`AIMANAGER_ANTIGRAVITY_BIN`
可指定官方原生 CLI 的绝对路径。默认优先使用 `~/.local/share/aimanager/bin/claude`、`agy`，
再查询 PATH。上述变量仅在启动/运行 CLI 时生效，不覆盖已有应用设置，也不能由浏览器指定。

安装 `scripts/aimanager-cli` 到用户 PATH 后，通过以下命令使用页面选中的账号：

```bash
aimanager-cli claude -- <Claude 参数>
aimanager-cli antigravity -- <Antigravity 参数>
```

可在没有旧客户端的服务器上将 `claude` / `agy` 设为此启动器的符号链接；已有客户端不得直接覆盖，
应使用显式 `aimanager-cli`。原生客户端存放在独立位置，避免启动器递归。未选择默认账号时拒绝启动，
不会静默退回其他账号。修改服务端状态路径时，终端启动器也要设置同一 `AIMANAGER_STATE_DIR`。

- Claude Code：`claude auth login`，然后 `claude auth status`。会员登录与 Console API 计费不同，
  应检查实际认证方式；不从 Claude 网页提取 Cookie。
  [官方 CLI 文档](https://code.claude.com/docs/en/cli-reference)
- Antigravity：在 SSH 终端运行 `agy`，按官方提示在本机浏览器授权，复制返回码到终端。
  不从酒馆或第三方反代项目复制 token 来冒充 CLI 会话。
  [官方认证说明](https://www.antigravity.google/docs/install?tab=cli)

## 更名兼容

本轮更名覆盖产品标题、主要界面、桌面窗口与产品名称。暂保留：

- GitHub 仓库 URL、Cargo 包、二进制 `codexmanager-service/web/start` 与现有启动命令；
- `CODEXMANAGER_*` 变量、现有配置/数据库目录、RPC/HTTP 协议标识和桌面 bundle identifier；
- 历史版权、NOTICE、原项目来源及历史发布记录。

不机械替换上述标识，避免新程序找不到旧数据、生成第二套数据库或破坏脚本。
后续若迁移可执行文件或 GitHub 仓库名，应提供兼容别名、迁移与回滚步骤，而不是覆盖用户数据。


## 接入与额度页面的职责

- `/connections/` 是所有 AI 接入的统一入口：Codex 设备授权与身份切换、Claude Code / Antigravity 隔离登录与默认账号，以及 API 地址管理和连通性检测。
- `/` 只提供额度窗口、重置时间、最近成功快照、模型目录及刷新。登录、添加与切换账号的操作均在接入中心。
- 额度刷新失败保留上次成功快照，显示本次失败原因，不能将未知值显示为零或已恢复。
- Claude 读取原生 CLI 使用的只读 OAuth usage 接口；此上游接口可能变化，401/403 需要重新验证官方授权，不会在管理端静默复制或改写 token。
- Antigravity 读取官方 `/usage` 面板。首次主题、登录、条款与数据使用选项需要在官方 CLI 完成；不会自动接受数据收集选项，不提交模型生成请求。
- Antigravity 模型通过 `agy models` 获取；Claude 仅展示官方缓存中未禁用的额外模型选项，明确标记不是完整模型列表。Codex 显示官方来源的服务模型目录，可能使用缓存，并非逐账号授权验证。API 入口读取上游 `/v1/models`，不会将健康状态当成额度。
- 托管 CLI 和后台 worker 继承 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY 与 NO_PROXY 及其小写形式。需要 SSH 反向代理时，在服务环境和命令启动环境配置同一地址，不要把端口写死到公共源码。

验证：Python 账号与额度测试、前端运行时测试、主 Playwright（含两个页面的操作边界及 390px 布局）、静态构建、Service AI 专项和 Web Rust 测试。自定义浏览器路径可通过 `AIMANAGER_TEST_BROWSER` 指定。
