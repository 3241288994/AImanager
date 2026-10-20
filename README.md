# AImanager

<p align="center">
  <strong>统一管理 AI CLI、私有 API 与本机 / 服务器项目上下文</strong>
</p>

AImanager保留已有 Codex 账号、额度、会话与 LabContext 能力，新增
「AI 接入」中心，支持 Claude Code / Antigravity 独立多账号、官方网页登录与额度快照，以及 Gemini
网页账号池等私有 Chat Completions API 的配置、启停检测和模型目录探测。
CLI 安装不等于已登录；API 目录可达不等于生成成功。当前不会自动迁移或复用第三方项目的 OAuth token。

[AI 接入与更名兼容说明](docs/ai-connections.md) · [按模型名协作](docs/ai-collaboration.md) · **贴一个路径，让 ChatGPT 读懂你的本机和服务器项目。**

<p align="center">
  <a href="https://github.com/3241288994/codexmanager/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/3241288994/codexmanager/actions/workflows/ci.yml/badge.svg" /></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-22c55e.svg" /></a>
  <img alt="LabContext Provider 0.9.0" src="https://img.shields.io/badge/LabContext-Provider%200.9.0-6366f1.svg" />
</p>

复制一个本机或服务器绝对路径，ChatGPT 就能在你授权的范围内查看目录、找到入口文件、继续读取
关键代码与文档，并解释整个项目是做什么的——无需先上传项目，也无需先注册工作区。

> **一句话卖点：把路径贴给 ChatGPT，让它直接读懂你电脑和服务器上的真实项目。**

[交给 Agent 安装](INSTALL.md) · [路径直读与工作区](docs/local-workspaces.md) · [连接 ChatGPT](docs/open-source/03-openai-plugin-and-tunnel.md) · [服务器部署](docs/open-source/01-server-deployment.md)

English: **AImanager unifies AI CLI access, private API connections, and project context.** Paste a path and let ChatGPT understand a project on your computer or server, with bounded tools and private credentials.

<p align="center">
  <a href="docs/assets/codexmanager-promo-v1.png">
    <img width="760" alt="AImanager：贴一个路径，让 ChatGPT 读懂本机与服务器项目（更名前宣传图）" src="docs/assets/codexmanager-promo-v1.png" />
  </a>
</p>

## 一眼看懂它怎么用

下面是一段典型流程。路径只是示例，实际可使用你已经授权的本机或服务器目录。

```text
你：
请读取服务器上的 /srv/research/web-agent，先看目录，再找到入口文件，告诉我这个项目怎么运行。

ChatGPT：
✓ 已确认来源：服务器
✓ 已读取两层目录：README.md、pyproject.toml、src/、tests/、configs/
✓ 找到主要入口：src/main.py
✓ 继续检查 README.md、pyproject.toml 与入口模块

这是一个用于网页任务规划与执行的 Agent 项目：
- src/main.py 负责启动任务和加载配置
- src/agent/ 保存规划、动作选择与错误恢复逻辑
- configs/ 定义模型、浏览器环境和实验参数
- tests/ 覆盖页面解析与任务执行

建议先从 README.md 的 Quick Start 启动，再查看 configs/default.yaml。
```

这个过程由四步组成：

| 你做什么 | ChatGPT 做什么 |
| --- | --- |
| 1. 粘贴绝对路径 | 判断它来自本机还是服务器，并交给正确的 Provider |
| 2. 要求“先看目录” | 返回有限深度的目录树，不把整个项目塞进上下文 |
| 3. 要求“找到入口” | 按需读取 README、依赖配置和候选入口文件 |
| 4. 继续追问 | 解释模块关系、运行方法、研究目标，或固定为长期工作区 |

你也可以直接这样问：

```text
请查看本地电脑的 /Users/me/Documents/project，找到入口文件并解释项目结构。
请读取服务器 /srv/research/paper-a/README.md，总结当前研究目标与运行方法。
请在服务器 /srv/research/experiments 下列出两层目录，并比较两个实验的结果文件。
```

## 把你常用的 CLI 和 API 模型搭配起来，一起完成任务

在已安装并配置协作 skill 的 Agent 中，直接提出任务并报出模型名，例如：

```text
请与 opus5.5 一起查看这个项目，分别提出方案，再讨论关键差异并落实修改。
请让 gemini4 分析这份材料，再结合项目中的实际约束给出建议。
```

- **轻量自由，你的 AI 你来组合。** 不增加常驻调度服务，谁负责、谁帮忙、怎样分工，
  按任务决定；不同 CLI/API 可以通过适配器接入。
- **让 CLI 和 API 都用上真本事。** CLI 自主查看项目、分析并执行授权任务，
  API 围绕相关材料出方案、补思路、审阅结果；双方可以继续讨论和互相反馈。
- **好用的做法留下来，下次不用从头教（规划中）。** 目标是自动把有效分工和步骤
  整理成配方，遇到类似任务时复用、修订。目前已有任务记录和四份配方，尚未实现自动沉淀。

三部分很简单：**Skill 教怎么合作，`ai-collab` 负责调用，配方保存做法。**
目前执行工具要求 Linux，已适配 Claude Code、Codex CLI 和 Gemini API 渠道；
新增渠道需要编写适配器，尚不是任意 CLI/API 即插即用。
具体支持范围与三部分说明见[使用说明](docs/ai-collaboration.md)。

## 本机、服务器，或者两边一起

| 模式 | 能访问什么 | 适合谁 |
| --- | --- | --- |
| `local` | 本机明确授权的目录 | 代码、论文和资料都在个人电脑上 |
| `server` | SSH 后面的服务器授权目录 | 主要在科研服务器、工作站或私有云工作 |
| `hybrid`（推荐） | 同一个 ChatGPT 连接中的本机 + 服务器 | 本机写作、服务器训练，希望上下文连贯 |

两端完全解耦：只需要本机就不必安装服务器组件，只需要服务器也不必开放本机文件。访问范围始终由
各端 Provider 的 `registry.allowed_roots` 控制；根目录、凭据、隐藏密钥和不支持的二进制不会因为
贴了路径就自动开放。

## 两种使用方式

### 路径直读：临时、快速、零注册

`inspect_path` 适合“现在帮我看看这个目录/文件”。Provider 0.9.0 支持（工作区文件读取共用同一解析器）：

- 有限深度目录树；
- 常见代码、配置、日志、文本及 README、Dockerfile、Makefile 等文件；
- HTML 可见正文，不加载外部资源；
- 文本型 PDF 的分页读取与搜索；
- DOCX 正文、XLSX 单元格、PPTX 幻灯片文字和 IPYNB 源码/纯文本输出；
- 扫描型 PDF 的明确 OCR 提示，而不是猜测内容。

### 工作区：长期项目上下文

需要持续研究时，再把路径固定为工作区。工作区可以维护项目概述、证据索引、实验结果、研究图、
分析任务和最近 Codex 会话衔接。路径直读与工作区共用同一套目录授权，但互不强制：先读懂，再决定
是否长期管理。

## 最省事的安装方式：交给 Agent

不用逐行复制部署命令。把下面内容交给能操作目标电脑和服务器的编码 Agent：

```text
请安装 https://github.com/3241288994/codexmanager ，模式为 hybrid。
服务器 SSH Host 是 <你的 SSH 别名>；本机允许读取 <本机目录>，服务器允许读取 <服务器目录>。
请先完整阅读仓库中的 AGENTS.md 和 INSTALL.md，按其中的 Agent 执行契约操作；
沿用已有 SSH 配置和密钥，不在对话或日志中输出凭据。只有必须由我在 OpenAI 页面完成时再通知我。
```

只使用一端时把模式改为 `local` 或 `server`。[`INSTALL.md`](INSTALL.md) 定义了只读盘点、备份、
组件安装、人工授权检查点与真实调用验收，Agent 不应把“端口已打开”误报成“已经完全连通”。

## 连接异常：点一下“一键修复”

打开 `http://127.0.0.1:48761/labcontext/`：

1. 连接降级时点击 **一键修复**；
2. 系统自动诊断，清理可验证的旧 SSH 转发或孤儿组件，重建连接并重新验证；
3. 无法安全修复时，页面直接显示具体原因和处理建议。

清理期间若另一个合法的 LabContext 启动器已经接管连接，修复会等待并核对 Router 的真实状态，避免把
短暂的 SSH 端口交接误报为失败。

如果 Router 完全没有运行，终端执行：

```bash
labcontext repair
```

`repair` 会自行完成诊断；不要写成 `labcontext doctor && labcontext repair`，因为诊断发现故障时会
返回非零状态，Shell 的 `&&` 会阻止修复命令执行。

## 它是如何连接起来的

日常使用只需要记住 `labcontext`；下面的组件可以分别安装、升级和替换：

```bash
labcontext status   # 分层状态
labcontext doctor   # 真实验证 SSH 与依赖
labcontext repair   # 降级时安全重建链路
```

```text
ChatGPT 网页版
      │
      ▼
Secure MCP Tunnel
      │
      ▼
LabContext Router · 127.0.0.1:1460/mcp
      ├── local Provider  ── 本机授权目录
      └── server Provider ── SSH bridge ── 服务器授权目录

AImanager Web · 127.0.0.1:48761
      └── 连接中心 / 工作区 / 研究图 / 用量与会话管理
```

- **Provider** 负责受限、只读地理解文件与项目；
- **Router** 把本机与服务器组合成一个稳定 MCP 工具面；
- **Tunnel** 让 ChatGPT 在无需开放入站公网端口的情况下访问 Router；
- **AImanager** 提供 AI 接入、连接诊断、工作区管理，以及 Codex 账号、额度、用量与会话辅助能力。

完整端口、SSH、Tunnel 和故障排查见[统一 LabContext Router](docs/labcontext-router.md)。

## 不只是路径读取

路径直读是主入口，下面这些能力为长期研究提供配套：

- **可验证、可一键修复的连接中心**：逐层检查 Router、Provider 身份与版本、真实 MCP 调用、SSH 子进程和 Tunnel；降级时先安全诊断再自动重建，无法处理则直接显示具体原因。
- **项目工作区**：管理模型可见资产、工具策略、项目概述、证据、实验、分析任务与研究图。
- **账号与额度**：通过官方设备授权添加账号，显示实际生效身份、套餐信号与额度快照，并切换服务器 Codex 凭据。
- **用量分析**：保存 Credits、Token 与交互历史，提供趋势图、JSON/CSV 导出和非账单性质的 USD 参考估算。
- **会话恢复**：读取 `state_5.sqlite` 元数据搜索本地会话并生成 `codex resume` 命令，不导出原始对话。

## 界面预览

### 工作区与连接中心

<img width="1682" height="812" alt="AImanager 工作区与连接中心（更名前界面）" src="https://github.com/user-attachments/assets/27f83e5e-67a3-4a74-aeec-398cc4647539" />

<details>
<summary>查看更多界面：工作区、研究图、账号、用量与会话</summary>

#### 工作区与研究图

<img width="2434" height="996" alt="工作区列表" src="https://github.com/user-attachments/assets/fc8eb835-e473-4a34-a8c9-831898cfbd7f" />
<img width="2382" height="1184" alt="工作区详情" src="https://github.com/user-attachments/assets/aac5d7cf-b728-4936-96f3-a78aec1813c4" />
<img width="2338" height="1240" alt="研究图" src="https://github.com/user-attachments/assets/b280447d-9625-42e3-96cc-4ea0c8a9b237" />

#### 账号与额度

<img width="2358" height="1392" alt="账号与额度" src="https://github.com/user-attachments/assets/f197bd8d-97e6-45ba-ba54-9af31e89efdc" />

#### 用量分析

<img width="1195" height="390" alt="用量分析概览" src="https://github.com/user-attachments/assets/c17a9177-a750-4f48-99ff-c79d43227386" />
<img width="1182" height="485" alt="用量趋势" src="https://github.com/user-attachments/assets/05e1b481-ffe0-4ded-80c6-ebe84711e62d" />
<img width="1182" height="455" alt="价格参考" src="https://github.com/user-attachments/assets/6d02cfd2-1073-4c60-8166-3891f4436acf" />

#### 会话恢复

<img width="2366" height="1278" alt="会话恢复" src="https://github.com/user-attachments/assets/63e5a98a-f6b4-4fb9-8c10-37183dc9c444" />

</details>

## 重要边界

- 只有 `registry.allowed_roots` 下经过验证的路径可读；目录深度、条目数、文件大小、PDF 页数和单次响应均有限制。
- 默认部署只监听回环地址；数据库、管理 RPC、账号令牌和 LabContext admin token 不应公开。
- AImanager service 本身不是 MCP endpoint；ChatGPT 连接的是独立 Router 的 `/mcp`，不是 `/api/rpc`、`/rpc` 或 `/admin`。
- 当前公开版不提供公共 OpenAI 兼容 `/v1` 网关。Secure MCP Tunnel 适合私有连接和开发测试，不是公共插件分发机制。
- 请只读取你有权访问的本机和服务器目录，并遵守 OpenAI、Codex 与目标项目的适用条款。

详细边界见 [SECURITY.md](SECURITY.md) 和 [OpenAI 插件与 Tunnel 说明](docs/open-source/03-openai-plugin-and-tunnel.md)。

## 手动部署与开发

| 目标 | 文档 |
| --- | --- |
| Agent 自动安装 | [INSTALL.md](INSTALL.md) |
| 服务器安全部署 | [docs/open-source/01-server-deployment.md](docs/open-source/01-server-deployment.md) |
| 本机路径与工作区 | [docs/local-workspaces.md](docs/local-workspaces.md) |
| Router 与三种模式 | [docs/labcontext-router.md](docs/labcontext-router.md) |
| ChatGPT、插件与 Tunnel | [docs/open-source/03-openai-plugin-and-tunnel.md](docs/open-source/03-openai-plugin-and-tunnel.md) |
| 测试与发布 | [TESTING.md](TESTING.md) · [公开发布清单](docs/open-source/04-public-release-checklist.md) |

本地开发要求 Node.js 20+、Python 3.11+、Rust stable；桌面打包还需要对应平台的 Tauri 依赖。

```bash
corepack pnpm@10.30.3 -C apps install --frozen-lockfile
corepack pnpm@10.30.3 -C apps run build:desktop
corepack pnpm@10.30.3 -C apps run test:runtime
cargo test --workspace --locked -- --test-threads=1
cargo test --manifest-path apps/src-tauri/Cargo.toml --locked --lib
scripts/open-source/preflight.sh
```

## 代码结构

```text
labcontext-provider/     路径直读、工作区、证据与研究工具的只读 Provider
scripts/labcontext*.py   本机 / 服务器统一 Router、SSH bridge 与启动诊断
apps/                    Next.js 管理界面与 Tauri 桌面壳
crates/web/              Web 运行壳、认证与受保护的 RPC 代理
crates/service/          账号、额度、会话、用量和 LabContext 管理适配
crates/core/             SQLite、认证与共享数据结构
crates/start/            service + web 启动器
deploy/                  安全 Compose 与 Router 示例配置
plugins/                 不含用户连接 ID 的公开插件模板
docs/                    路径、部署、Tunnel、安全与发布文档
```

## 贡献、许可与来源

- 安全问题请遵循 [SECURITY.md](SECURITY.md)，不要在公开 Issue 中提交凭据或可利用细节。
- 贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。
- 项目采用 [MIT License](LICENSE)，基于 `qxcnm/Codex-Manager` 的 MIT 许可代码演进而来；详见 [NOTICE](NOTICE) 与[第三方声明](THIRD_PARTY_NOTICES.md)。

会话与恢复支持 Codex、Claude Code 和 Antigravity，详见 [CLI 会话恢复](docs/cli-sessions.md)。
