"use client";

import { useState, type CSSProperties } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CalendarDays, Clock3, Database, Download, RefreshCw, Sparkles } from "lucide-react";
import { aiAccountsClient, type AiProvider, type CliAnalyticsReport } from "@/lib/api/ai-accounts-client";
import { getAppErrorMessage } from "@/lib/api/transport";
import { activeFirst } from "@/lib/account-order";
import { offsetDate, sumMetrics } from "@/lib/usage-analytics";
import { useManagedAiAccounts, useManagedCliSession } from "@/hooks/useManagedAiAccounts";
import { CliAuthorizationDialog } from "@/components/ai/cli-authorization-dialog";
import { UsageTrend } from "./usage-trend";
import { Button } from "@/components/ui/button";
import styles from "@/app/analytics/analytics.module.css";

const palette = ["#5bbfa6", "#6caee0", "#ad97dc", "#e6af77", "#83bd89", "#d991b6"];
const format = (value: number | null) => value == null ? "未提供" : value.toLocaleString("zh-CN");

function exportReport(report: CliAnalyticsReport) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }));
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = `${report.provider}-usage-${report.startDate}.json`; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function ManagedCliAnalytics({ provider }: { provider: AiProvider }) {
  const { accounts } = useManagedAiAccounts();
  const client = useQueryClient();
  const auth = useManagedCliSession();
  const [selected, setSelected] = useState("");
  const today = new Date().toISOString().slice(0, 10);
  const [start, setStart] = useState(() => offsetDate(today, -29));
  const [last, setLast] = useState(today);
  const items = activeFirst(accounts.data?.items.filter(item => item.provider === provider) ?? [], item => item.active);
  const account = items.find(item => item.id === selected) ?? items[0];
  const end = last ? offsetDate(last, 1) : "";
  const days = (Date.parse(end) - Date.parse(start)) / 86400000;
  const valid = Boolean(start && last && days > 0 && days <= 366 && last <= today);
  const report = useQuery({
    queryKey: ["cli-analytics", provider, account?.id, start, end, account?.quota.checkedAt],
    queryFn: () => aiAccountsClient.analytics(account!.id, start, end),
    enabled: Boolean(account) && valid, retry: false, staleTime: 60_000,
    refetchInterval: 600_000, refetchIntervalInBackground: false,
  });
  const history = report.data?.quotaHistory ?? [];
  const labels = [...new Set(history.flatMap(row => row.windows.map(window => window.label)))];
  const chart = history.map(row => Object.fromEntries([
    ["time", new Date(row.capturedAt * 1000).toISOString().slice(0, 10)],
    ...row.windows.map(window => [window.label, window.remainingPercent]),
  ]));
  const totals = sumMetrics(report.data?.days ?? []);
  const latest = history.at(-1);
  const error = accounts.error || report.error;
  const name = provider === "claude" ? "Claude Code" : "Antigravity";
  const cards = [
    { label: "总 Tokens", value: totals.totalTokens, icon: Database },
    { label: "输入（含缓存写入）", value: totals.uncachedInputTokens, icon: Database },
    { label: "缓存读取 Tokens", value: totals.cachedInputTokens, icon: Database },
    { label: "模型回复次数", value: totals.turns, icon: Sparkles },
  ];
  return <section className={`${styles.page} space-y-5 pt-5`} aria-label={`${name} 用量分析`}>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="text-lg font-semibold">{name} 使用概览</h2><p className="mt-1 text-xs text-muted-foreground">用量与额度分开呈现，每一条记录都有明确来源。</p></div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" disabled={!report.data} onClick={() => report.data && exportReport(report.data)}><Download className="size-3.5" />JSON</Button>
        <Button size="sm" variant="outline" disabled={!account || !valid || report.isFetching} onClick={() => void client.invalidateQueries({ queryKey: ["cli-analytics", provider] })}><RefreshCw className={`size-3.5 ${report.isFetching ? "animate-spin" : ""}`} />刷新记录</Button>
        <Button size="sm" disabled={!account || account.authStatus !== "authenticated" || auth.busy || auth.live} onClick={() => void auth.run(async () => auth.start(await aiAccountsClient.usage(account!.id)))}>同步官方额度</Button>
      </div>
    </div>
    <div className="glass-card space-y-4 rounded-2xl border border-border/60 p-5">
      <div className="flex flex-wrap items-end gap-4">
        <label className="grid min-w-0 flex-1 basis-52 gap-2 text-xs text-muted-foreground">统计账号<select className={styles.input} value={account?.id ?? ""} onChange={event => setSelected(event.target.value)} aria-label={`${name} 统计账号`}>
          {!items.length ? <option value="">尚无托管账号</option> : items.map(item => <option key={item.id} value={item.id}>{item.active ? "● 当前默认 · " : ""}{item.label}</option>)}
        </select></label>
        <div className="grid w-full grid-cols-2 gap-3 sm:w-auto">
          <label className="grid gap-2 text-xs text-muted-foreground">开始日期<input type="date" max={today} className={styles.input} value={start} onChange={event => setStart(event.target.value)} /></label>
          <label className="grid gap-2 text-xs text-muted-foreground">结束日期（含）<input type="date" max={today} className={styles.input} value={last} onChange={event => setLast(event.target.value)} /></label>
        </div>
        <div className={styles.segmented} role="group" aria-label="快捷日期">{[7, 30, 90].map(n => <button key={n} aria-pressed={last === today && start === offsetDate(today, 1 - n)} onClick={() => { setStart(offsetDate(today, 1 - n)); setLast(today); }}>近 {n} 天</button>)}</div>
      </div>
      {!valid ? <p role="alert" className="text-xs text-destructive">请选择有效日期范围，最多 366 天。</p> : null}
      <div className="flex flex-wrap gap-x-6 gap-y-2 border-t pt-3 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5"><CalendarDays className="size-3.5" />UTC 日期 · {history.length} 天额度快照</span>
        <span className="inline-flex items-center gap-1.5"><Clock3 className="size-3.5" />{report.data ? `读取于 ${new Date(report.data.checkedAt * 1000).toLocaleString()}` : "等待读取"}</span>
      </div>
    </div>
    {error ? <p role="alert" className="rounded-xl border border-destructive/25 p-4 text-sm text-destructive">{getAppErrorMessage(error)}</p> : null}
    {report.data?.coverage.partial ? <p role="alert" className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-amber-700 dark:text-amber-300">日志读取达到资源边界或遇到不可读文件，以下为部分统计，不代表完整用量。</p> : null}
    {provider === "claude" ? <>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map((card, i) => <div key={card.label} className={`glass-card ${styles.stat} rounded-2xl border border-border/60`} style={{ "--tone": palette[i] } as CSSProperties}><div className="flex items-center justify-between text-xs text-muted-foreground"><span>{card.label}</span><card.icon className="size-4" /></div><p className="mt-4 text-2xl font-semibold tabular-nums">{format(card.value)}</p><p className="mt-2 text-[11px] text-muted-foreground">本机该账号已保留的记录</p></div>)}
      </div>
      <UsageTrend days={report.data?.days ?? []} loading={report.isFetching} hasAccount={Boolean(account)} credits={false} turnsLabel="模型回复" />
    </> : <div className="glass-card rounded-2xl border border-sky-500/20 p-5"><h3 className="font-medium">额度窗口观测</h3><p className="mt-2 text-sm leading-relaxed text-muted-foreground">Antigravity 暂无可靠的逐日 Token 来源。下面展示官方剩余额度与重置时间；从本次接入开始保留每日最新快照。</p></div>}
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{latest?.windows.map((window, i) => <div key={window.label} className="glass-card space-y-3 rounded-2xl border border-border/60 p-5">
      <div className="flex items-center justify-between gap-3"><h3 className="text-sm text-muted-foreground">{window.label}</h3><span className="text-xl font-semibold tabular-nums">{window.remainingPercent}%</span></div>
      <div className="h-2 overflow-hidden rounded-full bg-muted" role="meter" aria-label={`${window.label} 剩余额度`} aria-valuenow={window.remainingPercent} aria-valuemin={0} aria-valuemax={100}><div className="h-full rounded-full" style={{ width: `${window.remainingPercent}%`, background: palette[i % palette.length] }} /></div>
      <p className="text-xs text-muted-foreground">范围内最新剩余 · {window.resetsAt ? `重置 ${window.resetsAt}` : "未提供重置时间"}</p>
    </div>)}</div>
    <div className="glass-card rounded-2xl border border-border/60 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">剩余额度趋势</h3><span className="text-xs text-muted-foreground">每日最后一次观测 · 各窗口独立</span></div>
      <div className="my-4 flex flex-wrap gap-4 text-xs text-muted-foreground">{labels.map((label, i) => <span className="flex items-center gap-2" key={label}><span className="size-2 rounded-full" style={{ background: palette[i % palette.length] }} />{label}</span>)}</div>
      {chart.length ? <div className="h-72" data-testid="quota-history-chart"><ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 800, height: 288 }}><LineChart data={chart} margin={{ top: 12, right: 12, bottom: 8, left: 0 }}>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 6" vertical={false} /><XAxis dataKey="time" tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} tickFormatter={value => value.slice(5)} /><YAxis domain={[0, 100]} unit="%" tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} width={48} />
        <Tooltip contentStyle={{ background: "var(--card-solid)", borderColor: "var(--border)", borderRadius: 12 }} />
        {labels.map((label, i) => <Line key={label} dataKey={label} stroke={palette[i % palette.length]} strokeWidth={2.5} dot={{ r: 3 }} connectNulls={false} isAnimationActive={false} />)}
      </LineChart></ResponsiveContainer></div> : <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">{report.isFetching ? "正在读取快照…" : "此范围暂无快照，登录账号后同步官方额度即可开始记录"}</div>}
      <p className="mt-3 text-xs text-muted-foreground">额度恢复可能来自窗口重置或套餐变化；曲线差值不能当作消耗量。</p>
    </div>
    <p className="px-1 text-xs leading-relaxed text-muted-foreground">{report.data?.note}</p>
    <CliAuthorizationDialog auth={auth} />
  </section>;
}
