"use client";

import Link from "next/link";
import { Orbit, Sparkles, ArrowUpRight, CheckCircle2, RefreshCw, LogIn } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from "@/components/ui/card";
import { aiAccountsClient, type AiProvider, type ManagedAiAccount } from "@/lib/api/ai-accounts-client";
import { getAppErrorMessage } from "@/lib/api/transport";
import { useManagedAiAccounts, useManagedCliSession } from "@/hooks/useManagedAiAccounts";
import { CliAuthorizationDialog } from "./cli-authorization-dialog";
import { activeFirst } from "@/lib/account-order";

export const AI_PLATFORMS = {
  claude: { name: "Claude Code", icon: Sparkles, tint: "bg-amber-500/10 text-amber-700 dark:text-amber-300" },
  antigravity: { name: "Antigravity", icon: Orbit, tint: "bg-cyan-500/10 text-cyan-700 dark:text-cyan-300" },
};

function checkedTime(timestamp?: number) {
  if (!timestamp) return "等待同步";
  const minutes = Math.max(0, Math.floor((Date.now() / 1000 - timestamp) / 60));
  return minutes < 1 ? "刚刚同步" : `${minutes} 分钟前同步`;
}

function QuotaSnapshot({ account }: { account: ManagedAiAccount }) {
  const quota = account.quota;
  return <div className="space-y-3 border-t border-border/60 pt-4">
    {quota.state === "available" && quota.windows.length ? quota.windows.map((window, index) => (
      <div className="space-y-2" key={`${window.label}-${index}`}>
        <div className="flex items-center justify-between gap-3 text-sm">
          <span className="truncate text-muted-foreground">{window.label}</span>
          <span className="shrink-0 font-medium tabular-nums">剩余 {window.remainingPercent}%</span>
        </div>
        <div role="meter" aria-label={`${window.label} 剩余额度`} aria-valuenow={window.remainingPercent} aria-valuemin={0} aria-valuemax={100} className="h-1.5 overflow-hidden rounded-full bg-muted">
          <div className="h-full rounded-full bg-emerald-400 transition-[width]" style={{ width: `${window.remainingPercent}%` }} />
        </div>
        <p className="text-xs text-muted-foreground">{window.resetsAt ? `重置：${window.resetsAt}` : "重置时间未提供"}</p>
      </div>
    )) : <div className="rounded-xl border border-dashed border-border/80 px-4 py-5 text-center">
      <p className="text-sm font-medium">{account.authStatus === "authenticated" ? (quota.state === "unavailable" ? "暂时无法读取额度" : "额度尚未同步") : "登录后查看官方额度"}</p>
      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{quota.note || "仅展示官方提供的数据，不估算余额。"}</p>
    </div>}
    {quota.lastError && quota.state === "available" ? <p role="status" className="text-xs text-amber-700 dark:text-amber-300">本次刷新未成功：{quota.lastError}</p> : null}
    <div className="flex flex-wrap justify-between gap-2 text-[11px] text-muted-foreground">
      <span>{quota.source === "official_oauth_usage" ? "官方额度接口" : "官方 CLI /usage"}{quota.lastError ? " · 保留上次快照" : ""}</span><span>{quota.checkedAt ? new Date(quota.checkedAt * 1000).toLocaleString() : "尚无额度快照"}</span>
    </div>
  </div>;
}

export function ManagedCliAccounts({ provider, view = "connections" }: { provider?: AiProvider; view?: "connections" | "usage" }) {
  const compact = view === "connections";
  const { accounts, synchronize } = useManagedAiAccounts();
  const auth = useManagedCliSession();
  const platforms: AiProvider[] = provider ? [provider] : ["claude", "antigravity"];
  const connect = (platform: AiProvider) => void auth.run(async () => auth.start(await aiAccountsClient.connect(platform)));
  const login = (id: string) => void auth.run(async () => auth.start(await aiAccountsClient.login(id)));
  const usage = (id: string) => void auth.run(async () => auth.start(await aiAccountsClient.usage(id)));

  return <section className="space-y-4" aria-label={compact ? "官方账号管理" : "官方账号额度"}>
    {!provider ? <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h3 className="font-semibold">官方账号连接</h3><p className="mt-1 text-xs text-muted-foreground">登录状态自动同步，凭证仅保留在服务主机。</p></div>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" disabled={auth.busy || accounts.isFetching} onClick={() => void auth.run(synchronize)}><RefreshCw className="size-3.5" />同步登录状态</Button>
        {compact ? <Button size="sm" variant="ghost" render={<Link href="/" />}>账号与额度<ArrowUpRight className="size-3.5" /></Button> : null}
      </div>
    </div> : null}
    {accounts.error ? <p role="alert" className="rounded-xl border border-destructive/20 bg-destructive/5 p-4 text-sm text-destructive">{getAppErrorMessage(accounts.error)}</p> : null}
    {accounts.isPending ? <div role="status" className="glass-card rounded-2xl border p-6 text-sm text-muted-foreground">正在同步官方登录状态…</div> : null}
    <div className={provider ? "space-y-4" : "grid gap-4 xl:grid-cols-2"}>
      {platforms.map(platform => {
        const meta = AI_PLATFORMS[platform];
        const Icon = meta.icon;
        const items = activeFirst(accounts.data?.items.filter(item => item.provider === platform) ?? [], item => item.active);
        const connected = items.filter(item => item.authStatus === "authenticated").length;
        return <Card key={platform} className="glass-card overflow-hidden rounded-2xl border-border/70" aria-label={`${meta.name} 账号`}>
          <CardHeader className="pb-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className={`flex size-10 shrink-0 items-center justify-center rounded-xl ${meta.tint}`}><Icon className="size-5" /></div>
                <div><CardTitle className="text-base">{meta.name}</CardTitle><CardDescription className="mt-1 text-xs">{connected ? `${connected} 个账号已登录` : "通过官方页面安全授权"}</CardDescription></div>
              </div>
              {compact ? <Button size="sm" variant={connected ? "outline" : "default"} disabled={auth.busy || auth.live || !accounts.data} onClick={() => connect(platform)} aria-label={connected ? `登录其他 ${meta.name} 账号` : `登录 ${meta.name}`}><LogIn className="size-3.5" />{connected ? "登录其他账号" : "网页登录"}</Button> : <Badge variant="outline">官方额度</Badge>}
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {items.length ? items.map(account => <div key={account.id} className={`space-y-4 rounded-xl border ${account.active ? "border-emerald-500/50 bg-emerald-500/[0.045] ring-1 ring-emerald-500/15" : "border-border/60 bg-background/35"} ${compact ? "p-4" : "p-5"}`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><p className="truncate text-sm font-medium">{account.label}</p>{account.active ? <Badge className="bg-emerald-600 text-white"><CheckCircle2 className="size-3" />当前默认</Badge> : null}</div><p className="mt-1 text-xs text-muted-foreground">{checkedTime(account.checkedAt)}{account.active ? " · 新任务默认账号" : ""}</p></div>
                <Badge variant="outline" className={account.authStatus === "authenticated" ? "border-emerald-500/20 bg-emerald-500/5 text-emerald-700 dark:text-emerald-300" : "text-muted-foreground"}>{account.authStatus === "authenticated" ? <><CheckCircle2 className="size-3" />已登录</> : account.authStatus === "signed_out" ? "未登录" : "待同步"}</Badge>
              </div>
              {!compact && account.authNote ? <p className="text-xs leading-relaxed text-muted-foreground">{account.authNote}</p> : null}
              {!compact ? <QuotaSnapshot account={account} /> : null}
              <div className="flex flex-wrap items-center gap-2">
                {account.authStatus === "authenticated" ? <>
                  {compact ? <Button size="sm" variant={account.active ? "secondary" : "outline"} disabled={auth.busy || account.active} onClick={() => void auth.run(async () => { await aiAccountsClient.select(account.id); toast.success("默认账号已切换，仅影响新启动的托管 CLI"); })}>{account.active ? "当前默认" : "设为默认"}</Button> : null}
                  {!compact ? <Button size="sm" variant="outline" disabled={auth.busy || auth.live} onClick={() => usage(account.id)}><RefreshCw className="size-3.5" />刷新官方额度</Button> : null}
                </> : compact ? <Button size="sm" variant="outline" disabled={auth.busy || auth.live} onClick={() => login(account.id)}>继续登录</Button> : <Link href="/connections/" className="text-xs text-primary">前往 AI 接入完成登录</Link>}
              </div>
            </div>) : <p className="rounded-xl border border-dashed py-6 text-center text-sm text-muted-foreground">尚无账号，请在 AI 接入中心连接。</p>}
            {compact ? <p className="text-xs leading-relaxed text-muted-foreground">新任务使用 <code className="rounded bg-muted px-1 py-0.5">aimanager-cli {platform}</code> 启动。不同平台额度独立计算，已有任务不受账号切换影响。</p> : null}
          </CardContent>
        </Card>;
      })}
    </div>
    <CliAuthorizationDialog auth={auth} />
  </section>;
}
