# 轻量协作首版验证记录

日期：2026-10-21。实现版本：`ai-collab 0.2.0`。
本次验证功能与集成正确性，不构成模型能力排名或效率提升基准。
安装及用法见[使用说明](ai-collaboration.md)。

## 自动验证

| 范围 | 结果 |
|---|---|
| scripts 完整 Python 测试 | 111 项通过，其中 ai-collab 39 项 |
| LabContext Provider | 105 项通过 |
| 开源预检 | 通过，包含 Rust manifest 与 Compose 检查 |
| Skill 格式、安装器、安装后版本 | 通过 |
| 补丁空白检查 | 通过 |

回归覆盖了精确模型路由、API messages 保存与续接、旧轮次拒绝、重叠目录写锁、
MCP 任务归属、策略变更后的重新授权、符号链接越界、异常后服务存活、
工具调用日志解析、进程组回收与 PID 复用保护、SSH 固定入口与 JSON stdin。
Router 验证了来源限定 ID、跨来源冲突拒绝，以及协作提交超时后不自动重发。
Provider 测试隔离了用户本机可选桥的配置，启用或不启用插件均不影响单测结果。

## 真实模型与服务验证

| 场景 | 观察结果 |
|---|---|
| Claude Code 原生 exec | 在独立测试目录修改函数、增加断言并运行 Python 检查；主控复跑通过 |
| Claude 原生 reply | 原 session ID 保持；不重复提供标记也能接上前文；后续继续修改和运行检查成功 |
| Codex 原生 exec | 修复测试函数，实际执行断言；主控复跑通过 |
| Codex 原生 reply | 原 thread ID 保持，正确接续上轮上下文 |
| Claude 账号环境调用 Codex | 使用实际隔离账号环境启动已安装 CLI，成功解析原配置并完成指定目录只读任务 |
| Gemini API reply | 从保存的历史取得预算和开支，正确计算追加开支后的合计 104、余额 16 |
| 已安装 stdio MCP | initialize、七个工具发现、jobs 调用通过 |
| Router → 在线 Provider → CLI | 提交真实 Claude 只读任务、获得带来源的 ID、查询并取回真实结果 |
| MCP 执行策略 | 当前部署允许指定项目 read/text，未启用 exec；exec 请求明确拒绝 |

实际测试使用 Claude Code 2.1.304，供应方 metadata 报告 `claude-opus-5-5`；
Codex CLI 0.163.0 请求 `gpt-6-astra`。后者事件流没有独立模型字段，
工具如实记录为 `explicit_request_only`。Gemini metadata 由反代声明，
不视为对后端模型的独立鉴定。

Opus 5.5 另做了两轮代码审阅，发现并推动修复 Router 重复提交、等待超时、
MCP 异常退出、派生进程清理和工具策略接入问题。其审阅为静态阅读，
自动测试及真实调用由主控执行，没有将静态审查表述为测试通过。

## 发现与限制

- Gemini 首轮出现多次不稳定拒答，直接调用也能复现；续接能正确利用历史。
  因此本次证明了 API 历史传递与续接可用，**没有证明反代推理稳定**。
  工具的 `succeeded` 表示调用完成，主控仍须判断拒答和结论质量。
- 首次 Claude 多工具执行触发解析器局部变量覆盖，实际文件操作已发生但任务被判失败。
  修复后以新任务验证修改、执行、续接；原失败记录保留，未改写为成功。
- Linux 原生 sandbox 的范围取决于 harness。Claude Bash 与文件工具不是同一种读取边界；
  不将它宣传为对任意不可信代码的容器级隔离。
- SSH 传输已完成离线回归与固定入口实现；本次没有已配置的另一台 SSH 执行主机，
  未声称真实跨机器 SSH 委派通过。
- Router 在服务器临时端口进行了真实端到端测试；本次没有改动 Mac 上的常驻 Router。
  Mac 需要同步新版脚本并刷新工具元数据，才能完整使用新的任务来源处理。
- 不同主控的调用环境已经核对，但未对所有第三方 harness 做兼容性验证。

服务器只更新协作工具、两处 skill 与 Provider 的可选桥；原有五个工作区、
配置/token 哈希、数据库 device/inode/migrations、Service/Start 二进制保持不变。
Web/Start 服务 PID 未变，`/api/runtime`、`/labcontext/` 均返回 200。
首次部署检查误用了 Provider 不提供的 `/health`，已自动回滚；改为真实 MCP
初始化验证后部署成功。这是检查脚本问题，保留在部署记录中。
