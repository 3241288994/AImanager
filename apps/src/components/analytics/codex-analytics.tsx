"use client";

import { useState, type CSSProperties } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowUpRight, CalendarDays, ChartNoAxesCombined, Clock3, Coins, Database, Download, Leaf, MessageSquare, RefreshCw, ShieldCheck, Wallet } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { UsageTrend } from "@/components/analytics/usage-trend";
import { useUsageAnalytics } from "@/hooks/useUsageAnalytics";
import { cacheRatio, downloadReport, offsetDate, sumMetrics, valuation, referenceAmount } from "@/lib/usage-analytics";
import { usageAnalyticsClient } from "@/lib/api/usage-analytics-client";
import { getAppErrorMessage } from "@/lib/api/transport";
import styles from "@/app/analytics/analytics.module.css";

const number = (v: number | null | undefined, digits = 0) => v == null ? "未提供" : v.toLocaleString("zh-CN", { maximumFractionDigits: digits });
const compact = (v: number | null) => v == null ? "未提供" : new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 2 }).format(v);
const time = (v: number | null | undefined) => v ? new Date(v * 1000).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "尚未同步";

function RateSetting({ rate }: { rate: number | null }) {
  const [draft, setDraft] = useState(rate == null ? "" : String(rate));
  const client = useQueryClient();
  const save = useMutation({ mutationFn: usageAnalyticsClient.setRate, onSuccess: async () => {
    await client.invalidateQueries({ queryKey: ["usage-analytics"] }); toast.success("折算系数已保存");
  }, onError: e => toast.error(getAppErrorMessage(e)) });
  const value = draft.trim() === "" ? null : Number(draft);
  const valid = value == null || (Number.isFinite(value) && value >= 0 && value <= 1000);
  return <div className="space-y-2 border-t pt-4">
    <div className="flex flex-wrap items-center gap-3 text-xs">
      <label htmlFor="usd-rate">手动覆盖 USD / Credit</label>
      <div className="w-32"><input id="usd-rate" className={styles.input} type="number" min="0" max="1000" step="any" placeholder="自动定价" value={draft} onChange={e => setDraft(e.target.value)} /></div>
      <Button size="sm" variant="outline" disabled={!valid || save.isPending} onClick={() => save.mutate(value)}>{save.isPending ? "保存中…" : "保存系数"}</Button>
    </div>
    <p className="text-xs text-muted-foreground">留空使用自动参考系数；手动值优先，所有账号共用。</p>
  </div>;
}

export function CodexAnalytics() {
  const a = useUsageAnalytics();
  const report = a.report.data ? { ...a.report.data, pricing: a.pricing.data ?? a.report.data.pricing } : undefined;
  const price = report?.pricing ?? a.pricing.data;
  const value = valuation(report);
  const money = (credits: number | null | undefined) => {
    const usd = referenceAmount(credits, value.rate);
    return credits == null ? "未提供" : usd == null ? "待同步定价" : `$ ${usd.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };
  const totals = sumMetrics(report?.days || []);
  const ratio = cacheRatio(totals);
  const error = a.report.error || a.accounts.error || (a.refresh.variables?.accountId === a.accountId ? a.refresh.error : null);
  const pricingError = price?.error || a.pricing.error || a.refreshPricing.error;
  const cards = [
    { label: "累计 Credits", value: number(totals.credits, 2), full: number(totals.credits, 3), note: "所选 Codex 账号用量", icon: Coins, tone: "#77CDB5" },
    { label: "总 Tokens", value: compact(totals.totalTokens), full: number(totals.totalTokens), note: "输入、缓存输入与输出", icon: Database, tone: "#82B9E8" },
    { label: "输入缓存命中率", value: ratio == null ? "未提供" : `${(ratio * 100).toFixed(1)}%`, note: "按输入 Token 加权", icon: Leaf, tone: "#8ACBA4" },
    { label: "交互轮数", value: number(totals.turns), note: "所选日期内的累计轮数", icon: MessageSquare, tone: "#B3A6E8" },
    { label: "参考金额 · USD", value: money(totals.credits), note: "Credits 折算 · 非实际账单", icon: Wallet, tone: "#8FCBCD" },
  ];
  return <div className={`${styles.page} space-y-5 pt-5 xl:space-y-6`}>
    <div className="flex flex-wrap items-center justify-between gap-4">
      <div className="flex items-center gap-3.5">
        <span className={`${styles.icon} size-11`}><ChartNoAxesCombined className="size-5" /></span>
        <div><h2 className="text-xl font-semibold tracking-tight">Codex 用量</h2><p className="mt-1 text-xs text-muted-foreground">用量、缓存与参考价值，一目了然。</p></div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button className="h-9 rounded-xl" variant="outline" disabled={!report?.days.length || !a.validRange} onClick={() => report && downloadReport(report, "json")}><Download className="size-3.5" />JSON</Button>
        <Button className="h-9 rounded-xl" variant="outline" disabled={!report?.days.length || !a.validRange} onClick={() => report && downloadReport(report, "csv")}><Download className="size-3.5" />CSV</Button>
        <Button className="h-9 rounded-xl px-4" disabled={!a.accountId || !a.validRange || a.refresh.isPending} onClick={() => a.refresh.mutate(a.params)}><RefreshCw className={`size-3.5 ${a.refresh.isPending ? "animate-spin motion-reduce:animate-none" : ""}`} />{a.refresh.isPending ? "同步中…" : "刷新用量"}</Button>
      </div>
    </div>

    <Card className={`glass-card ${styles.panel}`}><CardContent className="space-y-4 px-5 py-1 sm:px-6">
      <div className="flex flex-wrap items-end gap-4">
        <label className="grid min-w-0 flex-1 basis-52 gap-2 text-xs text-muted-foreground">统计账号<select aria-label="统计账号" className={styles.input} value={a.accountId} onChange={e => a.setSelectedAccount(e.target.value)}>
          {!a.accounts.data?.items.length && <option value="">暂无账号</option>}
          {a.accounts.data?.items.map(account => <option key={account.id} value={account.id}>{account.label || account.name || account.id}</option>)}
        </select></label>
        <div className="grid w-full grid-cols-2 gap-3 sm:w-auto">
          <label className="grid min-w-0 gap-2 text-xs text-muted-foreground">开始日期<input aria-label="开始日期" type="date" className={styles.input} max={a.today} value={a.startDate} onChange={e => a.setStartDate(e.target.value)} /></label>
          <label className="grid min-w-0 gap-2 text-xs text-muted-foreground">结束日期（含）<input aria-label="结束日期" type="date" className={styles.input} max={a.today} value={a.lastDate} onChange={e => a.setLastDate(e.target.value)} /></label>
        </div>
        <div className={styles.segmented} role="group" aria-label="快捷日期">{[7, 30, 90].map(days => <button key={days} type="button" aria-pressed={a.lastDate === a.today && a.startDate === offsetDate(a.today, 1 - days)} onClick={() => { a.setStartDate(offsetDate(a.today, 1 - days)); a.setLastDate(a.today); }}>近 {days} 天</button>)}</div>
      </div>
      {!a.validRange && <p role="alert" className="text-xs text-destructive">请选择有效日期范围，最多 366 天。</p>}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t pt-3 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5"><Clock3 className="size-3.5" />同步于 {time(report?.sync?.succeededAt)}</span>
        <span className="inline-flex items-center gap-1.5"><CalendarDays className="size-3.5" />{report?.days.length ?? 0} 天记录</span>
        <span className="inline-flex items-center gap-1.5 sm:ml-auto"><span className="size-1.5 rounded-full bg-[#77CDB5]" />页面可见时每 10 分钟自动同步</span>
      </div>
      {report?.days.some(d => a.now / 1000 - d.capturedAt > 600) && <p className="text-xs text-amber-600">部分日期为历史快照，刷新可获取最新数据。</p>}
    </CardContent></Card>

    {(error || report?.sync?.error) && <div role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{error ? getAppErrorMessage(error) : report?.sync?.error}</div>}

    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">{cards.map(c => <Card key={c.label} className={`glass-card ${styles.panel} ${styles.stat}`} style={{ "--tone": c.tone } as CSSProperties}>
      <div className="flex items-center justify-between gap-2"><span className="text-xs text-muted-foreground">{c.label}</span><span className={`${styles.icon} size-8`}><c.icon className="size-4" /></span></div>
      <div><p title={c.full ?? c.value} className="truncate text-[clamp(1.25rem,1.8vw,1.8rem)] font-semibold tracking-tight tabular-nums">{c.value}</p><p className="mt-2 text-[11px] text-muted-foreground">{c.note}</p></div>
    </Card>)}</div>

    <UsageTrend days={report?.days || []} loading={a.report.isFetching || a.refresh.isPending} hasAccount={Boolean(a.accountId)} />

    <Card className={`glass-card ${styles.panel}`}><CardContent className="space-y-4 px-5 py-1 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3"><span className={`${styles.icon} size-10`}><ShieldCheck className="size-5" /></span><div><h3 className="text-sm font-semibold">自动定价 · 参考价值</h3><p className="mt-1 text-xs text-muted-foreground">Credits × 参考系数，仅作估算，不代表实际账单。</p></div></div>
        <div className="flex flex-wrap items-center gap-3">
          <span className={`${styles.pill} tabular-nums`}>{value.rate == null ? "尚无可用定价" : `$${number(value.rate, 6)} / Credit`}</span>
          <span className="text-xs text-muted-foreground">{value.method === "manual-credit-rate" ? "手动覆盖" : "官方表格推导"}</span>
          <Button variant="outline" size="sm" className="rounded-lg" disabled={a.pricing.isFetching || a.refreshPricing.isPending} onClick={() => a.refreshPricing.mutate()}><RefreshCw className={`size-3 ${a.pricing.isFetching || a.refreshPricing.isPending ? "animate-spin motion-reduce:animate-none" : ""}`} />{a.pricing.isFetching || a.refreshPricing.isPending ? "同步定价中…" : "同步官方定价"}</Button>
        </div>
      </div>
      {price?.snapshot && a.now / 1000 - price.snapshot.fetchedAt >= 86400 && <p className="text-xs text-amber-600">当前使用超过 24 小时的缓存价格，金额可能已过时。</p>}
      {pricingError && <p role="alert" className="text-xs text-amber-600">{typeof pricingError === "string" ? pricingError : getAppErrorMessage(pricingError)}；{price?.snapshot ? "继续使用上次验证的价格。" : "自动参考金额暂不可用。"}</p>}
      <details className={`${styles.details} border-t pt-3`}><summary>查看计算依据与价格设置</summary>
        <div className="space-y-4 text-xs leading-relaxed text-muted-foreground">
          <p>自动系数取官方标准短上下文 API 输入单价 ÷ 对应 Credits 消耗量的中位数，并交叉核对缓存输入与输出比例（允许 1% 的表格舍入差异）。这不是官方 Credits 售价，也不是按模型 Tokens 计算的 API 账单。</p>
          <p>历史日期按最新参考系数重估。套餐内用量也可能计入 Credits；实际扣款取决于套餐、购买协议和折扣。Fast 模式及长上下文的等价 API 费用可能不同。</p>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2"><span>价格同步于 {time(price?.snapshot?.fetchedAt)} · 已核对 {price?.snapshot?.evidence.length ?? 0} 个模型</span><span>缓存 24 小时 · 失败后至少间隔 1 小时重试</span></div>
          <div className="flex flex-wrap gap-4"><a className="inline-flex items-center gap-1 underline underline-offset-4" href="https://developers.openai.com/api/docs/pricing" target="_blank" rel="noreferrer">官方 API 定价<ArrowUpRight className="size-3" /></a><a className="inline-flex items-center gap-1 underline underline-offset-4" href="https://learn.chatgpt.com/docs/pricing" target="_blank" rel="noreferrer">官方 Codex Credits 表<ArrowUpRight className="size-3" /></a></div>
          {report && <RateSetting key={String(report.usdPerCredit)} rate={report.usdPerCredit} />}
        </div>
      </details>
    </CardContent></Card>

    <Card className={`glass-card ${styles.panel} pb-0`}><CardHeader className="px-5 pt-1 sm:px-6"><div className="flex items-center justify-between gap-3"><div><CardTitle className="font-semibold">每日明细</CardTitle><CardDescription className="mt-1 text-xs">按日期倒序排列，保留完整用量数据</CardDescription></div><span className={styles.pill}>{report?.days.length ?? 0} 条记录</span></div></CardHeader>
      <CardContent className="px-0"><div className="max-h-[480px] overflow-auto"><table className={styles.table}><thead><tr>{["日期", "Credits", "未缓存输入", "缓存输入", "输出", "总 Tokens", "轮数", "参考金额 USD", "采集时间"].map(h => <th key={h} scope="col">{h}</th>)}</tr></thead><tbody>
        {[...(report?.days || [])].reverse().map(d => <tr key={d.date}><td className="font-medium tabular-nums">{d.date}</td>{[d.totals.credits, d.totals.uncachedInputTokens, d.totals.cachedInputTokens, d.totals.outputTokens, d.totals.totalTokens, d.totals.turns].map((v, i) => <td key={i} className="tabular-nums">{number(v, i === 0 ? 3 : 0)}</td>)}<td className="font-medium tabular-nums">{money(d.totals.credits)}</td><td className="text-muted-foreground" title={new Date(d.capturedAt * 1000).toLocaleString()}>{time(d.capturedAt)}</td></tr>)}
        {!report?.days.length && <tr><td colSpan={9} className="h-28 !text-center text-muted-foreground">{a.report.isFetching || a.refresh.isPending ? "正在读取每日明细…" : "暂无记录，选择账号与日期后同步用量"}</td></tr>}
      </tbody></table></div></CardContent>
    </Card>
    <p className="flex items-start gap-2 px-1 text-[11px] leading-relaxed text-muted-foreground"><Activity className="mt-0.5 size-3 shrink-0" />来源：ChatGPT Codex analytics · 按账号工作区隔离，包含多设备记录；不与网关统计叠加，也不推算滚动周期额度。</p>
  </div>;
}
