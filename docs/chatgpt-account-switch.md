# ChatGPT 换号运维：后台接入层

本功能只做后台架构与 CLI 运维，不增加前端面板、按钮、轮询或换号专用 MCP 工具。
项目环境和账号接入分离：更换 ChatGPT 网页账号时保留 Provider、工作区、目录授权、SSH、
Router 和数据库，只调整必要的 Tunnel 配置与凭据。不会代替本人登录、安装/授权插件、
切换 Codex CLI 账号，或转移 ChatGPT 的历史、记忆和订阅。

## 升级与提前准备

```bash
scripts/install-labcontext.sh
labcontext connections snapshot
labcontext connections list
labcontext connections export
```

安装器只复制启动器、Router 及配套模块，不启动或停止现有进程，也不读取运行凭据。
后台功能不依赖更新 Web；旧启动器需在方便时停止并重新运行一次 `labcontext`，才支持局部
重连。无需重装 Provider、修改数据库或重新注册工作区。

`snapshot` 首次将当前 profile、健康地址及凭据来源类型写入
`~/.config/labcontext/connections.json`（0600），不改动 `launcher.env`，不复制密钥、
Tunnel YAML、浏览器登录态或工作区数据。重复执行保留已有配置及选择。
`export` 只打印无凭据恢复清单和项目交接提示词，不创建文件或改变运行状态。
**这不是完整备份**：原 Tunnel profile 和凭据需要另行安全保管，单靠清单不能恢复登录。

## 以后换号

1. 本人登录目标 ChatGPT/Platform 账号，确认所需组织/工作区权限。能合法复用 Tunnel 时
   可复用；无法管理或关联旧 Tunnel 时新建 Tunnel 和受限运行凭据。不要覆盖旧 profile。
2. 按当前 `tunnel-client help quickstart` 准备独立 profile，并指向现有 Router。例如：

   ```bash
   tunnel-client init --profile labcontext-next --tunnel-id tunnel_your_new_id \
     --mcp-server-url http://127.0.0.1:1460/mcp
   ```

   自定义 Router 端口时使用真实地址。profile 的健康监听地址须与后续登记的 `--health-url`
   一致，默认 `http://127.0.0.1:8080`；切换先停止旧 Tunnel，不要求两者同时监听同一端口。
3. 在 Git 工作树之外，用安全编辑器创建专用凭据文件，仅含 `CONTROL_PLANE_API_KEY=...`，
   权限为 `0600`。不要将密钥放入命令参数、聊天、网页或日志。
4. 登记并检查，不激活新接入：

   ```bash
   labcontext connections add next --label personal-next \
     --profile labcontext-next --secret-file /absolute/path/to/next.env
   labcontext connections check next
   ```

5. 准备完成后显式切换，查看结果：

   ```bash
   labcontext connections use next
   labcontext connections list
   ```

   切换前诊断失败时不停止原连接；启动失败、超时或健康端口仍被占用时保留原选择，尝试
   恢复原 Tunnel，不接管其他进程。新进程通过稳定性及 `/readyz` 检查后才保存选择。
   原账号凭据已失效时，旧接入也可能恢复失败，需按原因处理，不能保证回滚后联网。
6. 本人在目标 ChatGPT 账号安装并授权插件，必要时刷新工具元数据，实际调用
   `list_workspaces`，再用非敏感示例调用 `inspect_path` 核对结果。后台不模拟验收成功，
   本机健康检查也不证明新账号具有插件权限。

## 局部恢复

```bash
# 仅重连当前 Tunnel，重新读取该接入的凭据文件
labcontext connections reconnect

# 显式返回原配置；前提是原凭据仍然可用
labcontext connections use current
```

这些命令不重启 Provider、SSH 或 Router，不更换任何网页/CLI 登录。
重启后专用凭据文件缺失或权限不符时，项目服务仍运行，Tunnel 明确报告不可用，不会回退
使用旧账号密钥。修正文件后可单独重连。后台任务结果和原因代码用 `connections list` 查看，
不依赖前端页面；切换和整套修复不能并行，不要重复提交任务。

## 架构和安全边界

- 连接目录随 `launcher.env` 存放，运行任务随 `launcher-status.json` 存放；自定义
  `--env-file` 或现有 `LABCONTEXT_STATUS_FILE` 时随其移动。无目录时兼容旧配置，只读检查
  不创建目录文件；持久化选择会在下次启动时恢复。
- 专用凭据只注入 Tunnel 子进程，不注入 Provider、SSH 或 Router。文件须属于当前用户且
  不对组/其他用户开放；拒绝符号链接、未知环境项与密钥缺失，不执行 shell 内容。
  旧式 `launcher.env` 密钥方式保持兼容。
- 配置原子写入、内核文件锁、受控进程句柄与有上限的超时保证任务隔离。配置文件损坏不能
  导致整套项目服务退出；进程崩溃后内核锁自动释放，不抢占其他机器或未知进程。
- CLI 使用本机 Router 的内部状态/控制通道 `GET /api/connections` 和
  `POST /api/connections/action`。通道保留精确 Origin 限制，检查回环 Host 和 JSON 类型；
  前端不调用这些接口，不提供浏览器配置保存/验证码接口，也不扩展 MCP 工具列表。
  不返回密钥或专用凭据路径，不应将 Router 或 Tunnel admin UI 暴露到公网。
- “本机链路已就绪”仅指 Provider 实际调用和已启用传输检查；账号授权与工具可用性以目标
  ChatGPT 中的实际调用为准。若还要使用新账号的 Codex 权益，须另行完成 Codex CLI 登录。

`export` 中的项目交接提示词使用已有工作区概述与科研上下文，由用户先选择项目，不自动
执行代码、修改文件或启动付费分析，也不会假装拥有旧账号的聊天记忆。

官方接入流程参见 [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
与[添加自定义 MCP](https://developers.openai.com/api/docs/guides/custom-mcp-server)。

## 验证范围

后台测试使用隔离临时目录、本机模拟 Provider 和 Tunnel 子进程，不使用真实账号密钥，
覆盖 CLI 切换、PID 保持、凭据隔离、失败恢复、崩溃锁释放、控制通道边界及密钥缺失时保持
项目服务。前端回归明确检查不存在换号入口，且不会轮询后台接入通道。

```bash
scripts/open-source/preflight.sh
corepack pnpm@10.30.3 -C apps run build
corepack pnpm@10.30.3 -C apps run test:runtime
corepack pnpm@10.30.3 -C apps run test:e2e
```

本机缺少 Cargo，`cargo test -p codexmanager-web` 返回
`zsh: command not found: cargo`；Rust manifest 检查同样跳过。
按用户安排，未更换 GPT 账号或改动现有运行凭据，真实新账号的插件验收留待后续本人换号时进行。
