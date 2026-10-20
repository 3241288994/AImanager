# CLI 会话与恢复

AImanager 的「会话与恢复」按 Codex、Claude Code、Antigravity 分页。
这里展示的是 **AImanager 服务所在主机** 的记录；网页运行在另一台电脑时，
恢复命令应在服务器终端执行。

| CLI | 数据来源 | 恢复方式 |
| --- | --- | --- |
| Codex | 本地 SQLite threads 索引 | `codex resume SESSION_ID`，保留原有单条 provider 索引修复 |
| Claude Code | 托管账号 `.claude/projects/*/*.jsonl` | 官方 `--resume SESSION_ID` |
| Antigravity | 托管账号 `conversation_summaries.db`，只读连接 | 官方 `--conversation SESSION_ID` |

Claude Code 与 Antigravity 的命令通过 `aimanager-cli` 固定账号和状态目录，
不会修改当前默认账号。例如：

```bash
aimanager-cli claude --account-id ACCOUNT_ID -- --resume SESSION_ID
aimanager-cli antigravity --account-id ACCOUNT_ID -- --conversation SESSION_ID
```

页面支持当前账号优先、账号切换、搜索、刷新、会话详情和命令复制。
`--continue` 用于在原项目目录继续该账号最近一次会话；没有保存记录时，
页面显示空状态，命令能否恢复由官方 CLI 决定。Antigravity 本地索引条目
不代表云端会话始终可访问。目录丢失时应恢复目录或手动进入迁移后的项目。

Claude 只读取每份日志首尾各 64 KiB，不返回模型回复和工具正文。
每次最多检查 1,000 个目录和 1,000 个文件、读取 16 MiB、耗时 4 秒；
达到整体限制或文件不可读时标记部分结果。由于只读取首尾，缺失的标题或工作目录
不会根据正文猜测。Antigravity 在 SQL 内限制字段长度，最多返回 500 条。
返回条目另受 512 KiB 响应预算限制。两者均拒绝跨账号符号链接，搜索条件参数化，不修改原始会话。

升级时需要同时更新 Service、Web 和 `scripts/aimanager-cli` 启动器。
现有 `claude`、`agy` 别名继续可用。

## 名称兼容

界面、桌面窗口和说明文档统一使用 **AImanager**。`codexmanager-*` 二进制、
Cargo 包名、HTTP 协议头、数据库、配置目录、存储键和历史发布文件名仍保留，
以兼容已有安装。无需重命名数据目录或重新登录。
