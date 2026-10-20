"use client";

import { useQuery } from "@tanstack/react-query";
import { Globe2, RefreshCw, Clock3, CircleCheck } from "lucide-react";
import { aiConnectionsClient, type AiConnection } from "@/lib/api/ai-connections-client";
import { getAppErrorMessage } from "@/lib/api/transport";
import { activeFirst } from "@/lib/account-order";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const statuses: Record<string, string> = { available: "可用", ready: "就绪", busy: "请求中", active: "活动", cooldown: "冷却中", needs_login: "需要登录", login_required: "需要登录", offline: "离线", unavailable: "不可用", recovering: "恢复中", error: "异常", unknown: "未知" };
const clock = (value: string | null) => value ? new Date(value).toLocaleString() : "未提供";
function Pool({ connection }: { connection: AiConnection }) {
  const quota = useQuery({
    queryKey: ["web-pool-quota", connection.id, connection.baseUrl],
    queryFn: () => aiConnectionsClient.quota(connection.id), enabled: connection.enabled,
    staleTime: 60_000, refetchInterval: 60_000, refetchIntervalInBackground: false, retry: false,
  });
  const accounts = activeFirst(quota.data?.accounts ?? [], account => account.status === "busy" || account.status === "active");
  return <div className="glass-card space-y-5 rounded-2xl border border-border/60 p-5 sm:p-6">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-3"><span className="flex size-10 items-center justify-center rounded-xl bg-sky-500/10 text-sky-600"><Globe2 className="size-5" /></span><div><h3 className="font-semibold">{connection.name}</h3><p className="mt-1 text-xs text-muted-foreground">网页账号池 · 5 小时与每周额度</p></div></div>
      <div className="flex flex-wrap items-center gap-2">{quota.data ? <Badge variant="outline"><CircleCheck className="size-3" />上次观测 {quota.data.readyAccounts ?? "未知"} 个可用</Badge> : null}<Button variant="outline" size="sm" disabled={!connection.enabled || quota.isFetching} onClick={() => void quota.refetch()}><RefreshCw className={`size-3.5 ${quota.isFetching ? "animate-spin" : ""}`} />{quota.isFetching ? "查询中…" : "刷新额度"}</Button></div>
    </div>
    {!connection.enabled ? <p className="text-sm text-muted-foreground">此入口已停用，请在 AI 接入中心启用后查询。</p> : null}
    {quota.isPending && connection.enabled ? <p role="status" className="text-sm text-muted-foreground">正在读取网页账号池额度…</p> : null}
    {quota.error ? <div role="alert" className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm"><p className="font-medium">暂时无法连接网页账号池</p><p className="mt-1 break-words text-xs text-muted-foreground">{getAppErrorMessage(quota.error)}。请检查 Mac 账号池和 SSH 转发；{quota.data ? "以下保留上次快照。" : "额度保持未知。"}</p></div> : null}
    <div className="grid gap-4 lg:grid-cols-2">{accounts.map(account => {
      const busy = account.status === "busy" || account.status === "active";
      return <article key={account.index} className={`space-y-4 rounded-xl border p-5 ${busy ? "border-emerald-500/50 bg-emerald-500/[0.045] ring-1 ring-emerald-500/15" : "border-border/60 bg-background/30"}`}>
        <div className="flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-2"><h4 className="text-sm font-semibold">账号 {account.index}</h4>{account.tier ? <Badge variant="secondary">{account.tier}</Badge> : null}</div><Badge variant={busy ? "default" : "outline"} className={busy ? "bg-emerald-600 text-white" : ""}>{statuses[account.status] ?? "未知"}</Badge></div>
        {account.stale || quota.error || account.probeFailed ? <p className="text-xs text-amber-700 dark:text-amber-300">{account.probeFailed ? "上游额度探测失败，以下为缓存记录。" : "额度快照可能已过期，等待上游更新。"}</p> : null}
        {account.windows.map((window, i) => <div key={window.label} className="space-y-2">
          <div className="flex items-center justify-between text-sm"><span className="text-muted-foreground">{window.label}</span><span className="font-semibold tabular-nums">{window.remainingPercent == null ? "剩余未知" : `剩余 ${window.remainingPercent}%`}</span></div>
          <div className="h-2 overflow-hidden rounded-full bg-muted" role={window.remainingPercent == null ? undefined : "meter"} aria-label={`${window.label} 剩余额度`} aria-valuenow={window.remainingPercent ?? undefined} aria-valuemin={0} aria-valuemax={100}><div className={`h-full rounded-full ${i ? "bg-sky-400" : "bg-emerald-400"}`} style={{ width: `${window.remainingPercent ?? 0}%` }} /></div>
          <div className="flex flex-wrap justify-between gap-2 text-[11px] text-muted-foreground"><span>重置：{clock(window.resetsAt)}</span><span>内部 Credits：{window.remainingCredits == null ? "未知" : window.remainingCredits.toLocaleString()}</span></div>
        </div>)}
        <div className="flex flex-wrap justify-between gap-2 border-t border-border/60 pt-3 text-[11px] text-muted-foreground"><span className="inline-flex items-center gap-1"><Clock3 className="size-3" />上游更新：{clock(account.usageUpdatedAt)}</span>{account.cooldownSeconds ? <span>冷却 {account.cooldownSeconds} 秒</span> : null}</div>
      </article>;
    })}</div>
    {quota.data && !accounts.length ? <p className="rounded-xl border border-dashed p-5 text-center text-sm text-muted-foreground">网页账号池暂未返回账号。</p> : null}
    <p className="text-xs leading-relaxed text-muted-foreground">{quota.data?.note ?? "账号池自动轮转，没有固定默认账号。额度数据由网页账号池提供。"} · 页面可见时每 60 秒更新。</p>
  </div>;
}

export function WebPoolQuota() {
  const connections = useQuery({ queryKey: ["ai-connections"], queryFn: aiConnectionsClient.list, staleTime: 60_000 });
  const pools = connections.data?.items.filter(item => item.credentialSource === "gemini-web-client") ?? [];
  return <section className="space-y-4 border-t border-border/60 pt-6" aria-label="网页账号池额度">
    <div><h2 className="text-lg font-semibold">网页账号池额度</h2><p className="mt-1 text-xs text-muted-foreground">与 CLI 订阅独立展示，关注实际剩余量与刷新时间。</p></div>
    {connections.error ? <p role="alert" className="text-sm text-destructive">{getAppErrorMessage(connections.error)}</p> : null}
    {connections.isPending ? <p role="status" className="text-sm text-muted-foreground">正在读取网页入口…</p> : pools.map(item => <Pool key={item.id} connection={item} />)}
    {connections.data && !pools.length ? <p className="text-sm text-muted-foreground">尚未接入支持额度查询的网页账号池。</p> : null}
  </section>;
}
