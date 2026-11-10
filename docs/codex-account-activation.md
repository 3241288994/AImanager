# Codex account activation / 账号生效

In **AI connections → Add Codex account → Start authorization**, finish the official
authorization while keeping the dialog open. By default this only saves the account,
leaving the current identity unchanged. Optionally select **Switch after authorization**.
Then use **Switch to this account** on either the quota page or AI connections.
This controls Codex on the **service host and paired Macs**, using independent
authorization on each device. Matching checks the token subject, ChatGPT account
and workspace; equal email addresses never establish identity. It does not change browser ChatGPT sign-in,
Secure MCP Tunnel ownership, or Connector authorization.

## Paired Mac synchronization

The account cards show server and Mac identities separately. The UI requests both
hosts by default (`syncDevices: true`); automation that omits it retains the previous
service-host-only behavior. This is a coordinated request, **not an atomic switch**:
one host can complete while the other waits for authorization, sessions or network.
Cancellation stops unfinished steps; it does not roll back a host already switched.

Authorize each additional account **once on the Mac** using the official device
code shown in the Mac status card. Independent OAuth grants avoid cross-device
refresh-token rotation conflicts. Only account IDs, identity claims, status and
temporary device codes cross SSH/RPC, never access/refresh/ID tokens. Grant files
stay private on their own host. A newly paired Mac does not replay an earlier
request; click the desired account after pairing.

Install `scripts/codex_device_rpc.py` as a private, user-owned helper on the server,
then run this on the Mac with a Python interpreter providing `tomlkit` and
`websockets` (sync client with Unix sockets):

```sh
python scripts/install_codex_device.py --ssh-target USER@HOST \
  --ssh-key /absolute/path/to/key --remote-helper /absolute/server/path/codex_device_rpc.py \
  --codex-binary /absolute/path/to/codex
```

An optional `--proxy http://127.0.0.1:PORT` applies only to isolated native login and
refresh workers. Installation does not switch accounts or modify the user's Codex
profile. The installer validates existing SSH host keys; it does not disable host
verification. The helper targets the existing local service at port 48760 and reads
the administrator RPC token privately under the server user's home.

Configuration: `~/.config/aimanager/codex-device.json`; metadata, device-local grants
and recoverable profile backups: `~/.local/state/aimanager/codex-device/`;
LaunchAgent: `~/Library/LaunchAgents/org.aimanager.codex-device.plist`.
The device ID persists across upgrades. The metadata-only registry is stored in
`codex_profile.devices` (empty by default), at most four devices, no schema change.
The metadata heartbeat uses reusable SSH connections and bounded 8-second long
polling in the SSH helper, which checks loopback task metadata every 250 ms.
The serial RPC service never blocks waiting for a new request. Pending
work is retried every 2 seconds; network failures back off to 120 seconds.
After writing local credentials, the Mac waits for daemon identity readiness.
Temporary activation failures remain pending and retry without overwriting the
original backup; daemon restarts are spaced at least 15 seconds apart and deferred
while tasks are active. External identity changes still stop the pending request.
The service host follows the same two-stage flow: once credentials are written,
retries only verify/activate the background daemon. Pending intents and restart
throttling survive service restarts. Repeated requests for the same in-flight
account preserve the request and any ongoing device authorization. Legacy
background-verification warnings can recover after identity verification;
cancelled and failed device requests are never revived. The Mac metadata
bootstrap preserves the last confirmed identity until a fresh observation exists.
Offline tasks expire after 24 hours. No listening Mac
HTTP port, browser-to-local credential channel or new environment variable is used.
Desktop and Web share administrator-only RPC; ordinary members cannot pair devices.

If the helper is offline, restore the SSH route and check its private `health.json`;
restart it using `launchctl kickstart gui/$(id -u)/org.aimanager.codex-device`.
Keep its configured Python interpreter installed when upgrading the Provider.
Active native-daemon tasks are never forcibly stopped; already-running classic
CLI processes keep the identity loaded in their own memory until restarted.

Current official account entitlements determine plan labels. Historical billing
product names do not override current `Free`; missing/failed checks remain unknown,
not automatically Free. Normal account refresh updates the entitlement without a
manual plan override. The timestamp still indicates how fresh the snapshot is.

Pro tier labels such as `Pro 200$` mean the **monthly USD tier**, not the amount
actually charged (taxes, discounts and billing currencies can differ). A generic
`pro` response does not establish a price. Display-only confirmations live in the
`codex_profile.pro_tiers` setting (default `{}`), keyed by account ID with
`monthlyUsd` and the exact current subscription `expiresAt`. They are exposed as
`planMonthlyUsd` / `planPriceSource: user_confirmed` by the account API. Only an
active Pro subscription in that same, unexpired period receives the label. Free,
unknown, revoked and renewed subscriptions do not inherit a historical price.
There is no new frontend setting, environment variable, migration or billing write.

**Device-code sign-in is the default.** Allow device-code login in the target
account's ChatGPT security settings (or ask the workspace administrator), generate
a code, open the official verification page, and enter it within 15 minutes. Keep
the AImanager dialog open. This flow does not use the Mac/server localhost callback
and does not bind or forward port 1455. Never share the code or auth cache in chat.
Device codes cannot bypass OpenAI's security verification or workspace policy.

The explicit **Browser callback (fallback)** option still requires a working,
authorized localhost callback channel. Do not reuse LabContext's MCP forward on
1455: it is a different service, and an IPv6-only callback listener on the server
does not make the Mac's IPv4 MCP tunnel a login callback. Configure an independent
callback channel before using that fallback. This update does not move LabContext
ports, modify SSH, or change the existing callback environment settings.

Device-code polling treats normal pending 403/404 JSON responses as pending, but
stops on HTML/security challenge responses rather than silently retrying for 15
minutes. The UI distinguishes verification, permissions, timeout and network errors
without displaying upstream HTML. A closed dialog never automatically switches the
current account; if the user completes authorization elsewhere, the backend may
still save that account until the device request expires. Service restarts terminate
in-flight device-code polling; generate a fresh code after restarting the service.

Reference: [Official authentication guidance](https://learn.chatgpt.com/docs/auth#login-on-headless-devices).

Active daemon tasks defer the switch: credentials and the current default remain
unchanged. The service checks runtime status every 2 seconds and switches once
all loaded threads are explicitly idle/notLoaded; idle windows need not close.
Running tools and waiting-for-approval/input flags are active. Unreadable, unknown,
paginated or system-error status blocks switching conservatively. Idle clients may
need to reconnect after the official background restart; saved history is retained.
The banner shows pending, failed or unverified activation and
offers cancellation/retry. Only the latest requested target is queued. Cancellation
is scoped to its request ID so a stale browser cannot cancel a newer request.

The queue stores IDs, timestamps and reason codes in `codex_profile.account_switch`
(empty by default), never passwords, 2FA seeds or tokens. It survives service restarts,
expires after 24 hours, and stops if the profile/identity changes elsewhere. Changing
the profile path, restoring a profile or selecting gateway mode cancels the queue.
Desktop and Web use the same service RPC; no page needs to remain open for retries.
Credential/profile failures stop retries until the user requests another attempt.
New failures after writing credentials are shown as unverified, never success.

Regression probe: `python3 scripts/tests/probe_codex_account_switch.py /path/to/codexmanager-service`.
It uses an isolated database, synthetic accounts and a mock Unix-socket daemon to
check deferral, cancellation, restart recovery, credential preservation and expiry;
it does not authenticate with OpenAI or access the user's active profile.

Before switching away, AImanager saves any newer CLI-refreshed credentials back to
the matching account under its refresh lock, checking token subject as well as ID.
Healthy access tokens are not needlessly rotated on every switch. History files are
not rewritten. Expired/revoked authorization can still require official sign-in again.

Legacy duplicate IDs are reconciled only when issuer, token subject, ChatGPT
account ID and workspace ID all match. Older credentials are disabled and hidden
from the normal account list, not deleted. Usage and session history remain in
the database. Equal email addresses alone never trigger reconciliation.

`codex login status` checks stored login data, not complete network connectivity.
If it reports a login but the interactive CLI asks again, check `codex doctor
--summary` and the terminal's proxy settings. The service's environment is not
automatically inherited by Termius/SSH terminals. A routing-discovery timeout is
not proof that the account credentials are invalid.

The shared Codex daemon may still cache an older login. On supported Unix hosts,
applying an account checks the daemon over its local Unix socket. AImanager uses
the official lifecycle command to restart it only if repeated checks confirm **no
active tasks**, then verifies the returned ChatGPT identity. Busy, inaccessible,
or unsupported daemons are left running with an explicit warning. Wait for active
tasks to finish and apply the account again, or deliberately run
`codex app-server daemon restart` once no work is running. An identity match in
`auth.json` alone does not prove that an existing daemon has reloaded it.

## 中文

在 **AI 接入 → 添加 Codex 账号 → 开始授权** 完成首次官方授权，保持弹窗打开。
默认只添加、不改变当前账号；需要立即使用时勾选“授权后同时切换到此账号”。
之后在 **账号与额度** 或 **AI 接入** 点击“切换到此账号”即可。
作用范围是 **服务器和已接入 Mac 的 Codex 默认账号**，不改变浏览器 ChatGPT 登录，
也不更换 Tunnel/Connector 所属账号。两端分别保存独立授权，不互相复制令牌。
Mac 首次使用某个账号时，在 Mac 状态卡完成一次官方设备码授权；之后可直接切换。
页面分别显示两端进度，一端完成不代表另一端完成；离线恢复后继续，忙时排队。
取消只停止未完成步骤，不回退已经切换的一端；已运行的经典 CLI 进程仍需退出重开。
安装、配置路径及恢复命令见上方 Paired Mac synchronization。

套餐标签以官方当前权益为准：当前是 Free 时直接标注 **FREE / 免费版 · 无付费权益**，
历史 Pro 账单不再触发冲突警告。自动额度刷新会同步套餐信息；读取失败不误判为 Free，
仍保留数据更新时间以说明快照的新鲜度。

默认采用**设备码登录**：先在目标账号的 ChatGPT 安全设置中允许设备码登录（工作区
可能需要管理员授权），再生成设备码，在官方页面输入并于 15 分钟内完成；保持弹窗
打开。此流程不依赖 localhost 回调，不占用或转发 1455 端口，也不能绕过安全验证。
备用“浏览器回调登录”仍要求独立、可用的回调通道，不能把 LabContext 的 1455 MCP
转发当作回调。更新不会移动 LabContext 端口、修改 SSH 或已有回调环境配置。
服务重启会终止未完成的设备码轮询，请重新生成；关闭弹窗不会自动切换当前账号，
但仍在有效期内的官方授权若完成，服务器可能继续保存该账号。不要在聊天中分享设备码。

后台有正在执行的任务时先排队，旧账号和凭据保持不变。服务每 2 秒检查一次，
所有会话明确空闲即可切换，不必退出窗口；执行工具、等待审批或输入仍按活跃处理。
状态读取失败、未知状态或系统异常不会误当空闲。闲置客户端在后台重启后可能需要
重新连接，历史记录不会删除。Mac 采用可唤醒的长轮询，缩短请求传达的等待。
页面明确区分待切换、失败、尚未核实，并提供取消和重试；仅保留最后请求的目标。
换出前会将 CLI 已刷新的凭据按账号身份回存，切回时不会简单恢复过期备份，也不会
每次无条件刷新令牌。凭据被撤销或真正失效时，仍需再次官方授权。

待切换状态保存在 `codex_profile.account_switch` 设置中，默认为空；不包含密码、
二次验证密钥或令牌。服务重启后继续，24 小时后过期；身份被外部修改、切换 Profile、
恢复配置或改用网关时停止/取消。网页关闭不影响队列；凭据或配置错误不会无限重试。

旧重复记录仅在发行方、令牌主体、ChatGPT 账号及工作区全部相同时归档停用，
保留历史与凭据，不以邮箱相同为合并依据。

如果 `codex login status` 显示已登录，但新会话仍要求登录，先运行
`codex doctor --summary`，检查终端代理。Termius 终端不会继承 AImanager 服务的
代理环境；工作区路由发现超时不能据此判为凭据失效。

Pro 金额标注为 **Pro 200$** 等月度美元档位，不是实际扣款金额。笼统的 Pro 字段不
用于猜价；用户确认金额仅绑定当前有效订阅周期，续期、降级或信息不足时不沿用。

新版本还会检查 Unix 主机上的 Codex 常驻后台。重复确认没有活跃任务时，
使用官方命令安全重启后台并核对登录身份；有会话、检查失败或版本不支持时不强制
重启，并返回具体提示。结束会话后重新“设为默认”即可；也可确认没有任务运行后
手动执行 `codex app-server daemon restart`。只核对磁盘凭据不能证明后台已换号。
