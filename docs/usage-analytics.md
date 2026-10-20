# 用量分析

入口：侧边栏「用量分析」（`/analytics/`），仅包含 Codex、Claude Code、Antigravity 三个 CLI，可切换平台与账号。网页账号池额度位于「账号与额度」。

- Codex：保留官方账号工作区的每日 Credits、Tokens、交互轮数与参考金额，支持 JSON / CSV。
- Claude Code：解析服务主机上该托管账号 `.claude/projects` 中已保存的 JSONL；按消息 ID 去重流式片段及重复日志，缓存写入计入未缓存输入，缓存读取单列。统计的是模型回复次数，不称作用户轮数。未保存的会话不计入，也不代表其他设备的总使用量。不导出对话内容，不推算账单。
- Claude Code / Antigravity：保留官方剩余额度的每日最新快照（UTC，最多 366 天），独立显示各窗口与重置时间。重置后的百分比变化不能推算成消耗量。Antigravity 缺少可靠逐日 Tokens 数据时明确说明，不补零、不伪造趋势。

新增 `aiAccounts/action` 的 `analytics` 操作，参数 `accountId/startDate/endDate`（结束日期不含），沿用管理员权限。历史保存在私有 `AIMANAGER_STATE_DIR/usage-history/<accountId>.json`，不修改 SQLite schema。首次读取会保留已有的成功额度快照；后续成功刷新持续更新。

Claude 日志读取上限：1000 个文件、64 MiB 总量、单行 1 MiB、8 秒；跳过软链接，目录最多向下三层。达到上限时展示「部分统计」，不声称完整覆盖。所选范围最多 366 天，报告只返回数值与来源元数据。

## 页面展示

界面按筛选、指标卡片、每日趋势、参考价格、每日明细排列。Tokens 柱状图使用天蓝（未缓存输入）、薄荷绿（缓存输入）、浅紫（输出）堆叠配色；Credits/交互轮数使用对应的柔和面积图，可通过分段按钮切换。定价推导与手动系数收在可展开区域，非账单说明和同步错误始终可见。每日表格支持滚动、固定表头和行悬停；总 Tokens 卡片显示紧凑数字，悬停查看完整值，明细和导出保留原始精度。兼容浅色、深色与低透明度模式。

## 数据与刷新

- 复用现有账号凭据、工作区请求头与代理；请求 ChatGPT 的私有 `wham/analytics/daily-workspace-usage-counts` 接口。无需额外网页登录。
- 默认选择与本机凭据身份核对一致的当前 Codex 账号；手动选择其他账号不会切换 Codex 登录。
- 首次打开所选范围时同步；页面可见时每 10 分钟检查并同步。离开页面后停止自动采集，手动刷新不受该间隔限制。
- 范围最多 366 天；界面结束日期包含当天，RPC 的 `endDate` 为排他边界。保留上游日期分桶，不重新按本机时区分桶；当天数据尚未完整。
- 数据属于所选 ChatGPT 账号工作区，可能包含多设备或工作区成员的用量，不等同于当前服务器会话统计。
- 缺失指标显示「未提供」，不自动当作零；缓存命中率为缓存输入 / 全部输入，跨日按 Token 加权。
- 日粒度数据不足以精确还原非零点重置的滚动额度周期，因此不把日累计值标为精确周期用量，也不推算官方周额度。
- 金额默认使用自动推导的 Credits 参考系数，详见下方定价说明。手动美元 / Credit 系数保存在 `app_settings.usage_analytics_usd_per_credit`，所有账号共用；手动值优先（包括 0），留空恢复自动定价。

## 自动定价与金额口径

页面打开时自动检查[官方 API 定价](https://developers.openai.com/api/docs/pricing)和[官方 Codex Credits 表](https://learn.chatgpt.com/docs/pricing)，通过官方 `.md` 文档读取。价格有效缓存 24 小时；页面每小时检查一次，失败至少间隔一小时自动重试；可手动强制同步。离开页面不运行定时同步。网络请求使用现有代理，不发送账号凭据或工作区信息；两张表均成功解析和交叉验证后才替换缓存。

**参考金额 = 工作区 Credits × 推导参考系数（USD/Credit），不是官方 Credits 售价，也不是实际账单或逐模型 API 消费额。** 推导方式为：匹配两表模型，取标准短上下文 API 输入单价 / Credits 输入消耗量的中位数；至少匹配 3 个模型，并要求所有匹配模型的输入、缓存输入、输出比例均在 1% 内一致（允许官方表格舍入）。2026-09-19 实测匹配 7 个模型，推导系数约为 0.04。若以后比例分化、页面结构变化、网络失败，不猜测新价格，显示错误并保留旧快照；超过 24 小时明确显示缓存已过时。

官方说明 Credits 购买价和折扣取决于套餐或协议，故不能将上述推导值当作购买价格。套餐内 Credits 也可能计入统计；Fast、长上下文的等价 API 费用可能不同。实测云端每日模型明细仅含 Credits/轮数等，没有按模型拆分的 Token 数，所以不按总 Tokens 或当前模型伪造逐模型金额，也不将本机跨账号日志混入所选工作区。

所有历史日期按当前参考系数重估，不还原历史成交价。JSON / CSV 导出包含计算方式、系数、价格采集时间、来源和非账单标记；JSON 还含价格表交叉验证记录及两份官方文档的 SHA-256。原始 Tokens/Credits 保持不变。

价格状态存于 `app_settings.usage_analytics_official_reference_v1`，初始为空；缓存和错误状态重启后保留，Web/Tauri/服务端共用。自动定价本身不另增数据库表、环境变量或第三方价格源，也不修改旧网关计费规则。

## 存储与错误处理

SQLite migration `069_usage_analytics` 新增独立日记录、同步状态和快照表。日记录按账号及日期隔离，不受 `usage_snapshots` 最新额度清理策略影响。成功刷新在事务中替换所选日期范围，范围外历史保留；每账号保留最近 180 次标准化快照。快照不保存 token、Cookie、对话正文或上游完整响应。

网络、401、403、429、字段格式错误均保留历史记录与上次成功时间，不触发账号切换、refresh token 轮换或账号可用性变更。401 时先在 Codex 完成登录再重试。私有接口可用性不属于 OpenAI 公开 API 保证。

RPC：`account/analytics/read`、`account/analytics/refresh`（`accountId`, `startDate`, `endDate`），`account/analytics/setRate`（`usdPerCredit`，可为 null）。另有 `account/analytics/pricingRefresh`（`force` 默认为 false，true 手动强制同步）。Web 命令映射与 Tauri 命令同步提供。

这些 RPC 能读取服务器账号凭据并访问工作区统计。在 `accounts` 多用户认证模式中，它们仅允许管理员调用，不属于成员自助数据接口。

## 来源

参考 [Wangnov/codex-meter](https://github.com/Wangnov/codex-meter)，核查版本 `a4c8873ad35bcb4769d9fee4675671eed0aec333`（扩展 0.2.19），借鉴其日统计接口及 Token/缓存计算规则，按本项目 Rust + React 架构实现。许可及版权声明见 [第三方声明](../THIRD_PARTY_NOTICES.md)。

## 验证

```bash
cargo test -p codexmanager-core usage_analytics --lib
cargo test -p codexmanager-service usage_analytics --lib
node --test apps/tests/usage-analytics.test.mjs
pnpm -C apps build:desktop
```
