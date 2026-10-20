"use client";

import { useId, useState } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartNoAxesCombined } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { AnalyticsDay } from "@/lib/api/usage-analytics-client";
import styles from "@/app/analytics/analytics.module.css";

const series = [
  { key: "uncachedInputTokens", name: "未缓存输入", color: "#82B9E8" },
  { key: "cachedInputTokens", name: "缓存输入", color: "#77CDB5" },
  { key: "outputTokens", name: "输出", color: "#B3A6E8" },
];
const metrics = [{ key: "tokens", label: "Tokens 构成" }, { key: "credits", label: "Credits" }, { key: "turns", label: "交互轮数" }] as const;
const compact = (n: number) => new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(n);

export function UsageTrend({ days, loading, hasAccount, credits = true, turnsLabel = "交互轮数" }: { days: AnalyticsDay[]; loading: boolean; hasAccount: boolean; credits?: boolean; turnsLabel?: string }) {
  const [metric, setMetric] = useState<(typeof metrics)[number]["key"]>("tokens");
  const gradientId = useId().replaceAll(":", "");
  const visibleMetrics = metrics.filter(item => credits || item.key !== "credits").map(item => item.key === "turns" ? { ...item, label: turnsLabel } : item);
  const chart = days.map(d => ({ date: d.date, ...d.totals }));
  const axis = { axisLine: false, tickLine: false, tick: { fill: "var(--muted-foreground)", fontSize: 11 }, tickMargin: 12 };
  const tooltip = <Tooltip cursor={{ fill: "var(--muted)", opacity: 0.55 }} content={({ active, payload, label }) => active && payload?.length ? (
    <div className={styles.tooltip} data-slot="chart-tooltip">
      <p className="mb-3 font-medium">{String(label)}</p>
      {payload.map(item => <div key={String(item.dataKey)} className="mt-2 flex items-center justify-between gap-7 text-xs">
        <span className="flex items-center gap-2 text-muted-foreground"><i className="size-2 rounded-full" style={{ background: item.color }} />{item.name}</span>
        <span className="font-medium tabular-nums">{typeof item.value === "number" ? item.value.toLocaleString("zh-CN", { maximumFractionDigits: 3 }) : "未提供"}</span>
      </div>)}
    </div>
  ) : null} />;
  return <Card className={`glass-card ${styles.panel}`}>
    <CardHeader className="gap-4 px-5 pt-1 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div><CardTitle className="text-base font-semibold">每日趋势</CardTitle><CardDescription className="mt-1 text-xs">观察用量变化，了解每一天的使用构成</CardDescription></div>
        <div className={styles.segmented} role="group" aria-label="图表指标">{visibleMetrics.map(m => <button key={m.key} type="button" aria-pressed={metric === m.key} onClick={() => setMetric(m.key)}>{m.label}</button>)}</div>
      </div>
      <div className="flex min-h-5 flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted-foreground">
        {metric === "tokens" ? series.map(s => <span key={s.key} className="inline-flex items-center gap-2"><i className="size-2.5 rounded-sm" style={{ background: s.color }} />{s.name}</span>) : <span className="inline-flex items-center gap-2"><i className="size-2.5 rounded-sm" style={{ background: metric === "credits" ? "#77CDB5" : "#82B9E8" }} />{metric === "credits" ? "每日 Credits" : `每日${turnsLabel}`}</span>}
        <span className="sm:ml-auto">{days.length} 天记录</span>
      </div>
    </CardHeader>
    <CardContent className="px-2 sm:px-4">
      {chart.length ? <div className="h-72 w-full sm:h-80" data-testid="usage-chart"><ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 800, height: 320 }}>
        {metric === "tokens" ? <BarChart data={chart} maxBarSize={28} barCategoryGap="28%" margin={{ top: 12, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 6" vertical={false} />
          <XAxis {...axis} dataKey="date" tickFormatter={s => s.slice(5).replace("-", "/")} minTickGap={28} />
          <YAxis {...axis} tickFormatter={compact} width={62} />{tooltip}
          {series.map((s, i) => <Bar key={s.key} dataKey={s.key} name={s.name} stackId="tokens" fill={s.color} radius={i === 2 ? [4, 4, 0, 0] : undefined} isAnimationActive={false} />)}
        </BarChart> : <AreaChart data={chart} margin={{ top: 12, right: 16, bottom: 8, left: 0 }}>
          <defs><linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={metric === "credits" ? "#77CDB5" : "#82B9E8"} stopOpacity={0.35} /><stop offset="100%" stopColor={metric === "credits" ? "#77CDB5" : "#82B9E8"} stopOpacity={0.02} /></linearGradient></defs>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 6" vertical={false} />
          <XAxis {...axis} dataKey="date" tickFormatter={s => s.slice(5).replace("-", "/")} minTickGap={28} /><YAxis {...axis} tickFormatter={compact} width={62} />{tooltip}
          <Area dataKey={metric} name={metric === "credits" ? "Credits" : turnsLabel} type="linear" stroke={metric === "credits" ? "#49AF94" : "#679FD0"} strokeWidth={2.5} fill={`url(#${gradientId})`} connectNulls={false} isAnimationActive={false} />
        </AreaChart>}
      </ResponsiveContainer></div> : <div className="flex h-72 flex-col items-center justify-center gap-3 text-sm text-muted-foreground"><ChartNoAxesCombined className="size-9 opacity-40" /><p>{loading ? "正在读取用量…" : !hasAccount ? "请先在账号与额度页面添加账号" : "此范围暂无每日用量记录"}</p></div>}
      <p className="px-4 pt-2 text-[11px] text-muted-foreground">按接口原始日期展示 · 未提供的指标保留为空</p>
    </CardContent>
  </Card>;
}
