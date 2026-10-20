# 按模型名协作

`ai-collab` 为 Codex 提供小型协作执行层：Claude 使用 AImanager 当前选择的
官方 CLI OAuth 配置，Gemini 使用已有网页反代。配套
`skills/multi-model-collaboration/SKILL.md` 负责自然语言触发与任务交接。

## 安装与使用

要求 Python 3.8+ 和 Linux（进程身份核验使用 `/proc`），不增加 Python 第三方依赖。
默认安装至用户目录，从任意项目目录运行：

```bash
python3 scripts/install-ai-collab.py
ai-collab init
ai-collab doctor
ai-collab resolve opus5.5
ai-collab models --refresh
ai-collab run --model opus5.5 --role reviewer \
  --prompt-file ./task.txt --file ./change.diff
ai-collab run --model opus5.5 --role reviewer \
  --workspace /absolute/project --prompt "阅读项目并审查登录流程"
ai-collab wait JOB_ID --timeout 30
ai-collab result JOB_ID
```

在 Codex 中说“请与 opus5.5 协作审查这次修改”即可。已有任务时，只发送
“opus5.5”也表示为该任务选择这个协作者。新增 skill 由新开的 Codex 会话发现。

默认映射：

| 名称 | 调用渠道 | 请求模型 |
|---|---|---|
| `opus5.5`、`Opus 5.5`、`claude-opus-5-5` | Claude Code | `claude-opus-5-5` |
| `gemini4`、`Gemini 4`、`gemini-argon` | Gemini 网页反代 | `gemini-argon` |
| `claude`、`gemini` | 对应渠道的可配置默认值 | 初始为上述两个模型 |

默认配置路径 `~/.config/ai-collab/config.json`；可用 `AI_COLLAB_CONFIG` 覆盖。
任务保存在 `~/.local/state/ai-collab/`，可用 `AI_COLLAB_STATE_DIR` 覆盖。
初次 `init --proxy URL` 可指定现有 Claude 出站代理；不改写系统代理或 AImanager 配置。
Gemini 凭据从已有 `~/.config/gemini-web-client/client.env` 读取，环境变量
`GEMINI_WEB_BASE_URL`、`GEMINI_WEB_API_KEY` 优先。不会在协作配置中复制 token。
支持 HTTPS 端点以及 loopback HTTP，拒绝携带凭据跳转。

## 协作边界与升级

默认提交任务及显式附带的文本；Claude 也可通过 `--workspace` 获得指定项目
或文件夹的 Read/Glob/Grep 直读能力，最多四个目录。此模式使用已验证的
Claude Code 2.1.304+，启用原生 `--restricted` 路径边界、`--safe-mode`、
凭据文件 Read deny 规则，仅保留读取与搜索工具，并记录工具调用及成功/失败状态。
工作区为 CLI 所在主机可访问的真实目录，不会复制整份项目；记录目录身份与
起始 Git revision，目录内容是实时读取，并非不可变快照。替换了根目录则终止任务。
本次调用不加载项目 hooks/MCP，也不开放 shell 或文件写入；
Codex 负责采纳补丁、执行测试和最终验收。
PDF、Office、远程路径等先通过现有 LabContext 解析，提交必要摘录。

文件最多 20 个，每个不超过 256 KiB，总输入最多 1 MiB，结果最多 4 MiB；
二进制和已识别凭据文件拒绝附带。上下文不会静默截断。任务最多并发 4 个，
超时可设为 5–1800 秒，默认 600 秒。`--dry-run` 只准备清单，不请求模型。
`--after JOB_ID` 显式加入成功任务的结果，不依赖模型端隐式会话记忆。

任务创建时固定模型、Claude 账号、输入哈希和配置快照；Gemini 固定网页反代
端点，账号由已有账号池管理，在响应头可用时记录实际服务账号。模型输出中的实际模型信息
另外保存：Claude 为 CLI metadata，Gemini 为 proxy metadata，均不依赖
模型口头自述；代理 metadata 不是对代理背后模型的独立鉴定。
发现模型不一致、空输出、截断、失败、取消或超时均不会当成成功。
没有自动重试或跨渠道回退；取消本地执行不能撤销上游已接受的请求。

`models --refresh` 不改变默认模型。Claude 目录是官方 CLI 的部分缓存，
Gemini 目录是代理声明；`doctor` 不消耗模型生成额度，也不证明推理成功。
明确的新版本可注册为新名称：

```bash
ai-collab alias set NEW_ALIAS --provider claude-code --model VERIFIED_MODEL_ID
ai-collab alias default claude NEW_ALIAS
```

已有名称须显式 `--replace` 才能替换，配置改动保留上一份备份。先核对官方
模型 ID、CLI 最低版本与账号权限，再用小型真实任务验证。

## JSON、状态与诊断

默认和 `--json` 都只向 stdout 输出一个版本化 JSON envelope：

```json
{"schemaVersion":1,"ok":true,"data":{"name":"opus5.5","provider":"claude-code","model":"claude-opus-5-5"}}
```

错误格式：

```json
{"schemaVersion":1,"ok":false,"error":{"code":"unknown_model","message":"..."}}
```

- 查询：`resolve` 返回路由；`models` 返回 configured/defaults 和可选 discovered。
- 执行：`run` 返回带 `id`、`state`、`route` 的任务；提交成功不等于模型成功。
- 读取：`status`/`wait` 返回任务状态；`result` 只返回成功结果及模型证据。
- 修改：`alias` 管理映射；`cancel` 返回本地取消是否已请求。
- 原始只读入口：`request --provider gemini-web --path /models`。

状态为 queued/running/succeeded/failed/cancelled/timed_out/interrupted。
CLI 参数或调用错误返回非零；`doctor` 检测失败、`run --wait` 或 `wait`
发现失败终态也返回非零。`status` 查询失败任务本身仍成功返回状态对象。
任务输入、原始输出和诊断文件是私有本地资料，不应提交 Git。
不自动删除任务，按用户需要在无活动任务时清理个人 state 目录。

官方依据：[Claude 非交互调用](https://code.claude.com/docs/en/headless)、
[CLI 参数](https://code.claude.com/docs/en/cli-reference)、
[Codex skills](https://learn.chatgpt.com/docs/build-skills)。
