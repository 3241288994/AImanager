"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Clock3, ExternalLink, Loader2, Plus, RefreshCw, ShieldCheck, UserRound } from "lucide-react";
import { toast } from "sonner";
import { accountClient } from "@/lib/api/account-client";
import { attachUsagesToAccounts } from "@/lib/api/normalize";
import { codexProfileClient } from "@/lib/api/codex-profile-client";
import { getAppErrorMessage } from "@/lib/api/transport";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { getUsageDisplayBuckets } from "@/lib/utils/usage";
import type { Account, AccountUsage } from "@/types";

function formatReset(timestamp: number | null): string {
  if (!timestamp) return "重置时间未知";
  const delta = timestamp * 1000 - Date.now();
  if (delta <= 0) return "等待额度刷新";
  const hours = Math.floor(delta / 3_600_000);
  const minutes = Math.floor((delta % 3_600_000) / 60_000);
  const days = Math.floor(hours / 24);
  return days > 0 ? `${days} 天 ${hours % 24} 小时后重置` : `${hours} 小时 ${minutes} 分后重置`;
}

function formatFreshness(timestamp: number | null): string {
  if (!timestamp) return "尚无用量快照";
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - timestamp));
  if (seconds < 60) return `${seconds} 秒前更新`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前更新`;
  return `${Math.floor(seconds / 3600)} 小时前更新`;
}

function formatSubscriptionDate(timestamp: number | null | undefined): string {
  if (!timestamp) return "官方未提供";
  const millis = timestamp > 10_000_000_000 ? timestamp : timestamp * 1000;
  return new Date(millis).toLocaleString();
}

function formatPollingInterval(seconds?: number): string {
  if (!seconds) return "间隔未知";
  if (seconds % 60 === 0) return `${seconds / 60} 分钟`;
  return `${seconds} 秒`;
}

function snapshotIsStale(timestamp: number | null): boolean {
  return !timestamp || Date.now() / 1000 - timestamp > 10 * 60;
}

function normalizedPlan(account: Account): { label: string; conflict: boolean } {
  const effective = String(account.planType || "").trim().toLowerCase();
  const subscription = String(account.subscriptionPlan || "").trim().toLowerCase();
  const signals = new Set([effective, subscription].filter(Boolean));
  const conflict = signals.size > 1 || (account.hasSubscription === false && subscription !== "" && subscription !== "free");
  const plan = conflict ? "待确认" : (subscription || effective || "未知").toUpperCase();
  return { label: plan, conflict };
}

function UsageMeter({ label, remain, resetsAt }: { label: string; remain: number | null; resetsAt: number | null }) {
  const value = remain == null ? null : Math.max(0, Math.min(100, remain));
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="font-medium">{label}</span>
        <span className="tabular-nums text-muted-foreground">{value == null ? "未提供" : `${Math.round(value)}%`}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${value ?? 0}%` }} />
      </div>
      <p className="text-xs text-muted-foreground">{formatReset(resetsAt)}</p>
    </div>
  );
}

function usageWindowLabel(minutes: number | null | undefined, fallback: string): string {
  if (!minutes) return fallback;
  if (minutes % (24 * 60) === 0) return `${minutes / (24 * 60)} 天额度`;
  if (minutes % 60 === 0) return `${minutes / 60} 小时额度`;
  return `${minutes} 分钟额度`;
}

function UsageWindows({ usage }: { usage?: AccountUsage | null }) {
  const buckets = getUsageDisplayBuckets(usage);
  if (buckets.mode === "unknown") {
    return <p className="text-sm text-muted-foreground">尚无可用额度快照</p>;
  }
  if (buckets.mode === "secondary-only") {
    return <UsageMeter label={usageWindowLabel(usage?.windowMinutes, "长周期额度")} remain={buckets.secondaryRemainPercent} resetsAt={buckets.secondaryResetsAt} />;
  }
  if (buckets.mode === "primary-only") {
    return <UsageMeter label={usageWindowLabel(usage?.windowMinutes, "短周期额度")} remain={buckets.primaryRemainPercent} resetsAt={buckets.primaryResetsAt} />;
  }
  return (
    <>
      <UsageMeter label={usageWindowLabel(usage?.windowMinutes, "短周期额度")} remain={buckets.primaryRemainPercent} resetsAt={buckets.primaryResetsAt} />
      <UsageMeter label={usageWindowLabel(usage?.secondaryWindowMinutes, "长周期额度")} remain={buckets.secondaryRemainPercent} resetsAt={buckets.secondaryResetsAt} />
    </>
  );
}

function AddAccountDialog({ open, onOpenChange, onCompleted }: { open: boolean; onOpenChange: (open: boolean) => void; onCompleted: () => Promise<void> }) {
  const [starting, setStarting] = useState(false);
  const [polling, setPolling] = useState(false);
  const [verificationUrl, setVerificationUrl] = useState("");
  const [userCode, setUserCode] = useState("");
  const [message, setMessage] = useState("点击下方按钮生成 OpenAI 设备登录信息。");
  const pollGeneration = useRef(0);

  useEffect(() => () => { pollGeneration.current += 1; }, []);

  const close = (next: boolean) => {
    if (!next) pollGeneration.current += 1;
    onOpenChange(next);
  };

  const startLogin = async () => {
    const generation = pollGeneration.current + 1;
    pollGeneration.current = generation;
    setStarting(true);
    setMessage("正在创建登录任务…");
    try {
      const result = await accountClient.startLogin({ loginType: "chatgpt", openBrowser: false });
      setVerificationUrl(result.verificationUrl || result.authUrl || "");
      setUserCode(result.userCode || "");
      setPolling(true);
      setMessage("请在 OpenAI 页面完成授权，本页会自动检测结果。");
      const deadline = Date.now() + 5 * 60_000;
      while (pollGeneration.current === generation && Date.now() < deadline) {
        const status = await accountClient.getLoginStatus(result.loginId);
        const normalized = status.status.trim().toLowerCase();
        if (normalized === "success") {
          setPolling(false);
          setMessage("登录成功，正在同步账号…");
          await onCompleted();
          toast.success("新账号已添加");
          close(false);
          return;
        }
        if (normalized === "failed") throw new Error(status.error || "OpenAI 授权失败");
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
      }
      if (pollGeneration.current === generation) setMessage("登录等待超时，请重新发起授权。");
    } catch (error) {
      if (pollGeneration.current === generation) {
        setMessage(`登录失败：${getAppErrorMessage(error)}`);
        toast.error(`登录失败：${getAppErrorMessage(error)}`);
      }
    } finally {
      if (pollGeneration.current === generation) {
        setStarting(false);
        setPolling(false);
      }
    }
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>添加 OpenAI 账号</DialogTitle>
          <DialogDescription>使用官方设备授权流程。控制台不要求你粘贴 access token。</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 rounded-xl border bg-muted/30 p-4">
          {userCode ? <div><p className="text-xs text-muted-foreground">设备验证码</p><p className="mt-1 font-mono text-2xl font-semibold tracking-[0.18em]">{userCode}</p></div> : null}
          <p className="text-sm text-muted-foreground">{message}</p>
          {verificationUrl ? (
            <Button variant="outline" className="w-full" onClick={() => window.open(verificationUrl, "_blank", "noopener,noreferrer")}>
              <ExternalLink />打开 OpenAI 授权页面
            </Button>
          ) : null}
          <Button className="w-full" onClick={() => void startLogin()} disabled={starting || polling}>
            {starting || polling ? <Loader2 className="animate-spin" /> : <Plus />}
            {polling ? "等待授权完成" : verificationUrl ? "重新生成登录信息" : "开始设备登录"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function CodexAccountsPanel() {
  const queryClient = useQueryClient();
  const [addAccountOpen, setAddAccountOpen] = useState(false);
  const accountsQuery = useQuery({ queryKey: ["personal", "accounts"], queryFn: accountClient.list, refetchInterval: 60_000, refetchIntervalInBackground: false });
  const usageQuery = useQuery({
    queryKey: ["personal", "usage"],
    queryFn: accountClient.listUsage,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  });
  const profileQuery = useQuery({
    queryKey: ["personal", "profile"],
    queryFn: () => codexProfileClient.get(),
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
  });
  const autoRefreshQuery = useQuery({
    queryKey: ["personal", "auto-refresh"],
    queryFn: accountClient.autoRefreshStatus,
    staleTime: 60_000,
  });
  const accounts = useMemo(
    () => attachUsagesToAccounts(accountsQuery.data?.items || [], usageQuery.data || []),
    [accountsQuery.data, usageQuery.data],
  );
  const active = accounts.find((account) => account.id === profileQuery.data?.selectedAccountId) || null;
  const activeSnapshotStale = snapshotIsStale(active?.lastRefreshAt ?? null);

  const refreshMutation = useMutation({
    mutationFn: () => {
      if (!active?.id) throw new Error("当前生效账号尚未识别");
      return accountClient.refreshUsage(active.id);
    },
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["personal"] });
      toast.success(result.credentialsSyncedFromProfile ? "已同步 Codex 最新凭据并刷新额度" : "当前账号额度已刷新");
    },
    onError: (error) => toast.error(`刷新失败：${getAppErrorMessage(error)}`),
  });
  const switchMutation = useMutation({
    mutationFn: (accountId: string) => codexProfileClient.applyDirectAccount({ accountId }),
    onSuccess: async (status) => {
      await queryClient.invalidateQueries({ queryKey: ["personal"] });
      if (!status.identityConsistent) {
        toast.warning("凭证已写入，但实际身份与管理记录不一致，请查看诊断");
      } else {
        toast.success("账号已切换；新启动的 Codex 会话将使用该账号");
      }
    },
    onError: (error) => toast.error(`切换失败：${getAppErrorMessage(error)}`),
  });

  const loading = accountsQuery.isLoading || usageQuery.isLoading || profileQuery.isLoading;
  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Codex 账号</h2>
          <p className="mt-1 text-xs text-muted-foreground">实际生效身份、订阅信号与官方额度快照。</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline"><RefreshCw />{autoRefreshQuery.data?.usagePollingEnabled ? `全部账号每 ${formatPollingInterval(autoRefreshQuery.data.usagePollIntervalSecs)}自动刷新` : "自动刷新未启用"}</Badge>
          <Button size="sm" variant="outline" onClick={() => setAddAccountOpen(true)}><Plus />添加账号</Button>
          <Button size="sm" variant="outline" onClick={() => refreshMutation.mutate()} disabled={refreshMutation.isPending || !active}>
            <RefreshCw className={refreshMutation.isPending ? "animate-spin" : ""} />刷新当前额度
          </Button>
        </div>
      </header>

      {profileQuery.data && !profileQuery.data.identityConsistent ? (
        <div className="flex gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" />
          <div><p className="font-medium">账号身份状态不一致</p><p className="mt-1 text-muted-foreground">auth.json 实际账号与 AImanager 记录不一致。切换前请先确认当前运行中的 Codex 任务。</p></div>
        </div>
      ) : null}

      {activeSnapshotStale && active?.usage ? (
        <div className="flex gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" />
          <div><p className="font-medium">当前额度快照可能已经过期</p><p className="mt-1 text-muted-foreground">快照于 {formatFreshness(active.lastRefreshAt)}生成。点击“刷新当前额度”后才应作为最新额度使用。</p></div>
        </div>
      ) : null}

      <Card className="glass-card rounded-2xl border-primary/25 bg-primary/[0.04]">
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardDescription>当前生效账号</CardDescription>
              <CardTitle className="mt-1 text-xl">{active?.name || (loading ? "读取中…" : "未识别账号")}</CardTitle>
            </div>
            <Badge variant={profileQuery.data?.identityConsistent ? "default" : "secondary"}>
              {profileQuery.data?.identityConsistent ? <CheckCircle2 /> : <AlertTriangle />}
              {profileQuery.data?.identityConsistent ? "已验证生效" : "需要核验"}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="grid gap-5 md:grid-cols-2">
          <UsageWindows usage={active?.usage} />
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-xs text-muted-foreground md:col-span-2">
            <span className="inline-flex items-center gap-1"><Clock3 className="size-3.5" />{formatFreshness(active?.lastRefreshAt ?? null)}</span>
            <span>Profile：{profileQuery.data?.codexHome || "-"}</span>
            <span>实际 ID：{profileQuery.data?.actualAccountId ? `${profileQuery.data.actualAccountId.slice(0, 8)}…` : "未知"}</span>
            {active?.hasSubscription ? <><span>套餐到期：{formatSubscriptionDate(active.subscriptionExpiresAt)}</span><span>下次续订：{formatSubscriptionDate(active.subscriptionRenewsAt)}</span></> : <span>未检测到付费套餐</span>}
          </div>
        </CardContent>
      </Card>

      <section className="space-y-3">
        <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">可用账号</h2><span className="text-sm text-muted-foreground">{accounts.length} 个</span></div>
        <div className="grid gap-3 lg:grid-cols-2">
          {accounts.map((account) => {
            const plan = normalizedPlan(account);
            const isActive = account.id === profileQuery.data?.selectedAccountId;
            const canSwitch = account.status === "active" && account.hasToken;
            return (
              <Card key={account.id} className={`glass-card rounded-2xl ${isActive ? "border-primary/45" : "border-border/70"}`}>
                <CardContent className="grid gap-4 p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 gap-3"><div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-muted"><UserRound className="size-5" /></div><div className="min-w-0"><p className="truncate font-semibold" title={account.name}>{account.name}</p><p className="mt-1 text-xs text-muted-foreground">{formatFreshness(account.lastRefreshAt)}</p></div></div>
                    <div className="flex gap-2"><Badge variant={plan.conflict ? "outline" : "secondary"}>{plan.label}</Badge>{isActive ? <Badge>当前</Badge> : null}</div>
                  </div>
                  <div className="grid gap-4 sm:grid-cols-2"><UsageWindows usage={account.usage} /></div>
                  {plan.conflict ? <p className="text-xs text-amber-600">套餐来源冲突：effective={account.planType || "未知"}，subscription={account.subscriptionPlan || "未知"}，暂不自动判定。</p> : null}
                  <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">{account.hasSubscription ? <><span>套餐到期：{formatSubscriptionDate(account.subscriptionExpiresAt)}</span><span>下次续订：{formatSubscriptionDate(account.subscriptionRenewsAt)}</span></> : <span>未检测到付费套餐</span>}</div>
                  <div className="flex items-center justify-between gap-3 border-t pt-3">
                    <span className="text-xs text-muted-foreground">状态：{account.status} · {account.hasToken ? "凭证可用" : "缺少凭证"}</span>
                    <Button size="sm" onClick={() => switchMutation.mutate(account.id)} disabled={isActive || !canSwitch || switchMutation.isPending}>
                      <ShieldCheck />{isActive ? "正在使用" : "切换到此账号"}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </section>
      <AddAccountDialog
        open={addAccountOpen}
        onOpenChange={setAddAccountOpen}
        onCompleted={async () => { await queryClient.invalidateQueries({ queryKey: ["personal"] }); }}
      />
    </div>
  );
}
