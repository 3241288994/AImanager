"use client";

import { useI18n } from "@/lib/i18n/provider";
import { translate } from "@/lib/i18n/messages";
import { DEFAULT_LOCALE, type AppLocale } from "@/lib/i18n/config";

import { activeFirst } from "@/lib/account-order";
import { activateCodexLogin } from "@/lib/codex-login-activation";
import { codexSwitchMessage } from "@/lib/codex-switch-feedback";
import { codexPlanDisplay } from "@/lib/codex-plan-display";
import { codexDevicesClient } from "@/lib/api/codex-devices-client";
import { CodexDeviceStatus, deviceOnline, devicePending } from "./codex-device-status";
import { codexLoginError, codexLoginOptions, DEFAULT_CODEX_LOGIN_METHOD, validateCodexLoginStart, type CodexLoginMethod } from "@/lib/codex-login-method";
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
import type { AccountUsage } from "@/types";
function formatReset(timestamp: number | null, locale: AppLocale = DEFAULT_LOCALE): string {
    if (!timestamp)
        return translate(locale, "重置时间未知");
    const delta = timestamp * 1000 - Date.now();
    if (delta <= 0)
        return translate(locale, "等待额度刷新");
    const hours = Math.floor(delta / 3600000);
    const minutes = Math.floor((delta % 3600000) / 60000);
    const days = Math.floor(hours / 24);
    return days > 0 ? translate(locale, "{value0} 天 {value1} 小时后重置", { value0: days, value1: hours % 24 }) : translate(locale, "{value0} 小时 {value1} 分后重置", { value0: hours, value1: minutes });
}
function formatFreshness(timestamp: number | null, locale: AppLocale = DEFAULT_LOCALE): string {
    if (!timestamp)
        return translate(locale, "尚无用量快照");
    const seconds = Math.max(0, Math.floor(Date.now() / 1000 - timestamp));
    if (seconds < 60)
        return translate(locale, "{value0} 秒前更新", { value0: seconds });
    if (seconds < 3600)
        return translate(locale, "{value0} 分钟前更新", { value0: Math.floor(seconds / 60) });
    return translate(locale, "{value0} 小时前更新", { value0: Math.floor(seconds / 3600) });
}
function formatSubscriptionDate(timestamp: number | null | undefined, locale: AppLocale = DEFAULT_LOCALE): string {
    if (!timestamp)
        return translate(locale, "官方未提供");
    const millis = timestamp > 10000000000 ? timestamp : timestamp * 1000;
    return new Date(millis).toLocaleString(locale);
}
function formatPollingInterval(seconds?: number, locale: AppLocale = DEFAULT_LOCALE): string {
    if (!seconds)
        return translate(locale, "间隔未知");
    if (seconds % 60 === 0)
        return translate(locale, "{value0} 分钟", { value0: seconds / 60 });
    return translate(locale, "{value0} 秒", { value0: seconds });
}
function snapshotIsStale(timestamp: number | null): boolean {
    return !timestamp || Date.now() / 1000 - timestamp > 10 * 60;
}
function UsageMeter({ label, remain, resetsAt }: {
    label: string;
    remain: number | null;
    resetsAt: number | null;
}) {
    const { t, locale } = useI18n();
    const value = remain == null ? null : Math.max(0, Math.min(100, remain));
    return (<div className="space-y-2">
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="font-medium">{t(label)}</span>
        <span className="tabular-nums text-muted-foreground">{value == null ? t("未提供") : `${Math.round(value)}%`}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-emerald-400 transition-[width]" style={{ width: `${value ?? 0}%` }}/>
      </div>
      <p className="text-xs text-muted-foreground">{formatReset(resetsAt, locale)}</p>
    </div>);
}
function usageWindowLabel(minutes: number | null | undefined, fallback: string, locale: AppLocale = DEFAULT_LOCALE): string {
    if (!minutes)
        return fallback;
    if (minutes % (24 * 60) === 0)
        return translate(locale, "{value0} 天额度", { value0: minutes / (24 * 60) });
    if (minutes % 60 === 0)
        return translate(locale, "{value0} 小时额度", { value0: minutes / 60 });
    return translate(locale, "{value0} 分钟额度", { value0: minutes });
}
function UsageWindows({ usage }: {
    usage?: AccountUsage | null;
}) {
    const { t, locale } = useI18n();
    const buckets = getUsageDisplayBuckets(usage);
    if (buckets.mode === "unknown") {
        return <p className="text-sm text-muted-foreground">{t("尚无可用额度快照")}</p>;
    }
    if (buckets.mode === "secondary-only") {
        return <UsageMeter label={usageWindowLabel(usage?.windowMinutes, t("长周期额度"), locale)} remain={buckets.secondaryRemainPercent} resetsAt={buckets.secondaryResetsAt}/>;
    }
    if (buckets.mode === "primary-only") {
        return <UsageMeter label={usageWindowLabel(usage?.windowMinutes, t("短周期额度"), locale)} remain={buckets.primaryRemainPercent} resetsAt={buckets.primaryResetsAt}/>;
    }
    return (<>
      <UsageMeter label={usageWindowLabel(usage?.windowMinutes, t("短周期额度"), locale)} remain={buckets.primaryRemainPercent} resetsAt={buckets.primaryResetsAt}/>
      <UsageMeter label={usageWindowLabel(usage?.secondaryWindowMinutes, t("长周期额度"), locale)} remain={buckets.secondaryRemainPercent} resetsAt={buckets.secondaryResetsAt}/>
    </>);
}
function AddAccountDialog({ open, onOpenChange, onCompleted }: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onCompleted: () => Promise<void>;
}) {
    const { t } = useI18n();
    const [starting, setStarting] = useState(false);
    const [polling, setPolling] = useState(false);
    const [verificationUrl, setVerificationUrl] = useState("");
    const [userCode, setUserCode] = useState("");
    const [message, setMessage] = useState("点击下方按钮生成 OpenAI 设备登录信息。");
    const [activateAfterLogin, setActivateAfterLogin] = useState(false);
    const [loginMethod, setLoginMethod] = useState<CodexLoginMethod>(DEFAULT_CODEX_LOGIN_METHOD);
    const [loginError, setLoginError] = useState(false);
    const pollGeneration = useRef(0);
    useEffect(() => () => { pollGeneration.current += 1; }, []);
    const close = (next: boolean) => {
        if (!next) {
            pollGeneration.current += 1;
            setStarting(false);
            setPolling(false);
            setActivateAfterLogin(false);
            setLoginMethod(DEFAULT_CODEX_LOGIN_METHOD);
            setLoginError(false);
            setVerificationUrl("");
            setUserCode("");
            setMessage("点击下方按钮生成 OpenAI 设备登录信息。");
        }
        onOpenChange(next);
    };
    const startLogin = async () => {
        const generation = pollGeneration.current + 1;
        pollGeneration.current = generation;
        setStarting(true);
        setLoginError(false);
        setVerificationUrl("");
        setUserCode("");
        setMessage("正在创建登录任务…");
        try {
            const options = codexLoginOptions(loginMethod);
            const result = await accountClient.startLogin({ loginType: options.loginType, openBrowser: options.openBrowser });
            if (pollGeneration.current !== generation) return;
            setVerificationUrl(validateCodexLoginStart(result, loginMethod));
            setUserCode(result.userCode || "");
            setPolling(true);
            setMessage("请在 OpenAI 页面完成授权，本页会自动检测结果。");
            const deadline = Date.now() + options.waitMs;
            while (pollGeneration.current === generation && Date.now() < deadline) {
                const status = await accountClient.getLoginStatus(result.loginId);
                if (pollGeneration.current !== generation) return;
                const normalized = status.status.trim().toLowerCase();
                if (normalized === "success") {
                    setPolling(false);
                    if (!activateAfterLogin) {
                        await onCompleted();
                        toast.success(t("账号已添加，当前默认账号保持不变"));
                        close(false);
                        return;
                    }
                    setMessage("授权成功，正在配置运行 AImanager 的主机上的 Codex…");
                    try {
                        const profile = await activateCodexLogin(status, accountId => codexProfileClient.applyDirectAccount({ accountId }));
                        if (profile.accountSwitch?.syncDevices) {
                            await onCompleted(); toast.info(t("账号已添加，双端同步请求已提交，请查看各端状态")); close(false); return;
                        }
                        if (profile.accountSwitch?.state === "pending") {
                            await onCompleted();
                            toast.info(t("账号已添加，切换已排队"));
                            close(false);
                            return;
                        }
                        if (profile.warnings.length) {
                            await onCompleted();
                            setMessage(`授权已保存；${profile.warnings.join(" ")}`);
                            toast.warning(t("凭据已保存，后台生效仍需处理，请查看提示"));
                            return;
                        }
                        toast.success(t("账号已添加，Codex 凭据已同步至 {value0}", { value0: profile.codexHome }));
                    } catch (error) {
                        await onCompleted();
                        setMessage(`授权成功，但 CLI 尚未生效：${getAppErrorMessage(error)}`);
                        toast.warning(t("账号已保存，CLI 配置未完成，请查看具体原因"));
                        return;
                    }
                    await onCompleted();
                    close(false);
                    return;
                }
                if (normalized === "failed")
                    throw new Error(status.error || t("OpenAI 授权失败"));
                await new Promise((resolve) => window.setTimeout(resolve, 1500));
            }
            if (pollGeneration.current === generation) {
                setLoginError(true);
                setMessage(loginMethod === "device" ? "设备码已过期，请重新生成；不要重复使用旧码。当前默认账号未改变。" : "登录等待超时，请重新发起授权。");
                setVerificationUrl("");
                setUserCode("");
            }
        }
        catch (error) {
            if (pollGeneration.current === generation) {
                const feedback = codexLoginError(getAppErrorMessage(error));
                setLoginError(true);
                setMessage(feedback);
                setVerificationUrl("");
                setUserCode("");
                toast.error(t(feedback));
            }
        }
        finally {
            if (pollGeneration.current === generation) {
                setStarting(false);
                setPolling(false);
            }
        }
    };
    return (<Dialog open={open} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("添加 OpenAI 账号")}</DialogTitle>
          <DialogDescription>{t("仅需首次官方授权，之后可一键切换。默认只添加账号，不改变当前任务；不保存密码或二次验证密钥。")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 rounded-xl border bg-muted/30 p-4">
          <label className="grid gap-2 text-sm font-medium">{t("授权方式")}<select aria-label={t("授权方式")} className="h-10 rounded-lg border border-input bg-background px-3 font-normal" value={loginMethod} disabled={starting || polling} onChange={event => {
            const method = event.target.value as CodexLoginMethod;
            setLoginMethod(method); setVerificationUrl(""); setUserCode(""); setLoginError(false);
            setMessage(method === "device" ? "点击下方按钮生成 OpenAI 设备登录信息。" : "点击下方按钮生成浏览器授权链接。");
          }}><option value="device">{t("设备码登录（推荐）")}</option><option value="browser">{t("浏览器回调登录（备用）")}</option></select></label>
          <p className="text-xs leading-relaxed text-muted-foreground">{loginMethod === "device" ? t("无需 localhost 回调，不占用 1455 端口。先在目标账号的 ChatGPT 安全设置中允许设备码登录，再打开官方页面输入下方设备码；请在 15 分钟内完成，并保持本窗口打开。") : t("此方式需要可用的 localhost 回调。远程部署若 1455 已用于 LabContext，不能直接使用；请先配置独立回调通道，或改用设备码登录。")}</p>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={activateAfterLogin} disabled={starting || polling} onChange={event => setActivateAfterLogin(event.target.checked)} />{t("授权后同时切换到此账号")}</label>
          {userCode ? <div><p className="text-xs text-muted-foreground">{t("设备验证码")}</p><p className="mt-1 font-mono text-2xl font-semibold tracking-[0.18em]">{userCode}</p></div> : null}
          <p role={loginError ? "alert" : "status"} className={`text-sm ${loginError ? "text-destructive" : "text-muted-foreground"}`}>{t(message)}</p>
          {verificationUrl ? (<Button variant="outline" className="w-full" onClick={() => window.open(verificationUrl, "_blank", "noopener,noreferrer")}>
              <ExternalLink />{t("打开 OpenAI 授权页面")}</Button>) : null}
          <Button className="w-full" onClick={() => void startLogin()} disabled={starting || polling}>
            {starting || polling ? <Loader2 className="animate-spin"/> : <Plus />}
            {polling ? t("等待授权完成") : verificationUrl ? t("重新生成登录信息") : activateAfterLogin ? t("授权并设为默认") : t("开始授权")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>);
}
export function CodexAccountsPanel({ view = "usage" }: {
    view?: "connections" | "usage";
}) {
    const { t, locale } = useI18n();
    const managing = view === "connections";
    const queryClient = useQueryClient();
    const [addAccountOpen, setAddAccountOpen] = useState(false);
    const accountsQuery = useQuery({ queryKey: ["personal", "accounts"], queryFn: accountClient.list, refetchInterval: 60000, refetchIntervalInBackground: false });
    const usageQuery = useQuery({
        queryKey: ["personal", "usage"],
        queryFn: accountClient.listUsage,
        refetchInterval: 60000,
        refetchIntervalInBackground: false,
    });
    const profileQuery = useQuery({
        queryKey: ["personal", "profile"],
        queryFn: () => codexProfileClient.get(),
        refetchInterval: query => query.state.data?.accountSwitch?.state === "pending" ? 2000 : 15000,
        refetchIntervalInBackground: false,
    });
    const autoRefreshQuery = useQuery({
        queryKey: ["personal", "auto-refresh"],
        queryFn: accountClient.autoRefreshStatus,
        staleTime: 60000,
    });
    const devicesQuery = useQuery({queryKey:["personal","codex-devices"],queryFn:codexDevicesClient.status,refetchInterval:query=>Array.isArray(query.state.data)&&query.state.data.some(devicePending)?2000:15000,refetchIntervalInBackground:false});
    const devices = Array.isArray(devicesQuery.data) ? devicesQuery.data : [];
    const authorizeMac = useMutation({mutationFn:({deviceId,accountId}:{deviceId:string;accountId:string})=>codexDevicesClient.login(deviceId,accountId),onSuccess:async()=>{await queryClient.invalidateQueries({queryKey:["personal"]});toast.info(t("已请求 Mac 授权，请稍候查看设备码"));},onError:error=>toast.error(getAppErrorMessage(error))});
    const accounts = useMemo(() => attachUsagesToAccounts(accountsQuery.data?.items || [], usageQuery.data || []), [accountsQuery.data, usageQuery.data]);
    const sortedAccounts = activeFirst(accounts, account => Boolean(profileQuery.data?.identityConsistent && account.id === profileQuery.data?.selectedAccountId));
    const active = accounts.find((account) => account.id === profileQuery.data?.selectedAccountId) || null;
    const activeSnapshotStale = snapshotIsStale(active?.lastRefreshAt ?? null);
    const switchStatus = profileQuery.data?.accountSwitch;
    const syncedDevicesPending = Boolean(switchStatus?.syncDevices && devices.some(d=>d.task?.parentRequestId===switchStatus.requestId && devicePending(d)));
    const switchMessage = codexSwitchMessage(switchStatus) || (syncedDevicesPending ? "双端同步进行中，各端独立处理；完成前不会显示全部成功。" : null);
    const switchTarget = accounts.find(account => account.id === switchStatus?.accountId);
    const cancelSwitchMutation = useMutation({
        mutationFn: (requestId: string) => codexProfileClient.cancelSwitch(requestId),
        onSuccess: async () => { await queryClient.invalidateQueries({queryKey: ["personal"]}); toast.success(t("已取消尚未完成的步骤，已完成的切换不会回退")); },
        onError: (error) => toast.error(getAppErrorMessage(error)),
    });
    const refreshMutation = useMutation({
        mutationFn: (id?: string) => {
            if (!id && !active?.id)
                throw new Error(t("当前生效账号尚未识别"));
            return accountClient.refreshUsage(id || active!.id);
        },
        onSuccess: async (result) => {
            await queryClient.invalidateQueries({ queryKey: ["personal"] });
            toast.success(result.credentialsSyncedFromProfile ? t("已同步 Codex 最新凭据并刷新额度") : t("当前账号额度已刷新"));
        },
        onError: (error) => toast.error(t("刷新失败：{value0}", { value0: getAppErrorMessage(error) })),
    });
    const switchMutation = useMutation({
        mutationFn: (accountId: string) => codexProfileClient.applyDirectAccount({ accountId }),
        onSuccess: async (status) => {
            await queryClient.invalidateQueries({ queryKey: ["personal"] });
            if (status.accountSwitch?.syncDevices && devices.length) {
                toast.info(t("双端同步请求已提交，请查看各端状态"));
            }
            else if (status.accountSwitch?.state === "pending") {
                toast.info(t("切换已排队，当前账号保持不变"));
            }
            else if (codexSwitchMessage(status.accountSwitch)) {
                toast.warning(t(codexSwitchMessage(status.accountSwitch)!));
            }
            else if (!status.identityConsistent) {
                toast.warning(t("凭证已写入，但实际身份与管理记录不一致，请查看诊断"));
            }
            else if (status.warnings.length) {
                toast.warning(status.warnings.join(" "), { duration: 12000 });
            }
            else {
                toast.success(t("账号已切换；新启动的 Codex 会话将使用该账号"));
            }
        },
        onError: (error) => toast.error(t("切换失败：{value0}", { value0: getAppErrorMessage(error) })),
    });
    const loading = accountsQuery.isLoading || usageQuery.isLoading || profileQuery.isLoading;
    return (<div className="flex flex-col gap-5">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">{t("Codex 账号")}</h2>
          <p className="mt-1 text-xs text-muted-foreground">{t("一键同步服务器与已接入 Mac 的 Codex 默认账号。各端独立授权、忙时排队；不改变浏览器 ChatGPT 登录。")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!managing ? <Badge variant="outline"><RefreshCw />{autoRefreshQuery.data?.usagePollingEnabled ? t("全部账号每 {value0}自动刷新", { value0: formatPollingInterval(autoRefreshQuery.data.usagePollIntervalSecs, locale) }) : t("自动刷新未启用")}</Badge> : null}
          {managing ? <Button size="sm" variant="outline" onClick={() => setAddAccountOpen(true)}><Plus />{t("添加 Codex 账号")}</Button> : null}
          {!managing ? <Button size="sm" variant="outline" onClick={() => refreshMutation.mutate(undefined)} disabled={refreshMutation.isPending || !active}>
            <RefreshCw className={refreshMutation.isPending ? "animate-spin" : ""}/>{t("刷新当前额度")}</Button> : null}
        </div>
      </header>

      {[accountsQuery.error, usageQuery.error, profileQuery.error, devicesQuery.error].filter(Boolean).map((error, i) => <p role="alert" key={i} className="rounded-xl border border-destructive/20 bg-destructive/5 p-4 text-sm text-destructive">{getAppErrorMessage(error)}</p>)}
      <CodexDeviceStatus devices={devices} accounts={accounts} serverAccount={profileQuery.data?.identityConsistent ? profileQuery.data.selectedAccountId : null} serverSwitch={switchStatus} busy={authorizeMac.isPending} onAuthorize={(deviceId,accountId)=>authorizeMac.mutate({deviceId,accountId})}/>
      {switchMessage && switchStatus ? <div role="status" data-testid="codex-switch-status" className="flex flex-wrap items-center gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm">
        <Clock3 className="size-4 shrink-0" /><div className="min-w-0 flex-1"><p className="font-medium">{t("目标账号")}：{switchTarget?.name || switchStatus.accountId}</p><p className="mt-1 text-muted-foreground">{t(switchMessage)}</p></div>
        {switchStatus.state !== "pending" ? <Button size="sm" disabled={switchMutation.isPending} onClick={() => switchMutation.mutate(switchStatus.accountId)}>{t("重试切换")}</Button> : null}
        <Button size="sm" variant="outline" disabled={cancelSwitchMutation.isPending || switchMutation.isPending} onClick={() => cancelSwitchMutation.mutate(switchStatus.requestId)}>{t("取消待切换")}</Button>
      </div> : null}
      {managing && profileQuery.data && !profileQuery.data.identityConsistent ? (<div className="flex gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600"/>
          <div><p className="font-medium">{t("账号身份状态不一致")}</p><p className="mt-1 text-muted-foreground">{t("auth.json 实际账号与 AImanager 记录不一致。切换前请先确认当前运行中的 Codex 任务。")}</p></div>
        </div>) : null}

      {!managing && activeSnapshotStale && active?.usage ? (<div className="flex gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600"/>
          <div><p className="font-medium">{t("当前额度快照可能已经过期")}</p><p className="mt-1 text-muted-foreground">{t("快照于")}{formatFreshness(active.lastRefreshAt, locale)}{t("生成。点击“刷新当前额度”后才应作为最新额度使用。")}</p></div>
        </div>) : null}

      {managing ? <Card className="glass-card rounded-2xl border-primary/25 bg-primary/[0.04]">
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardDescription>{t("Codex 默认账号")}</CardDescription>
              <CardTitle className="mt-1 text-xl">{active?.name || (loading ? t("读取中…") : t("未识别账号"))}</CardTitle>
            </div>
            <Badge variant={profileQuery.data?.identityConsistent ? "default" : "secondary"}>
              {profileQuery.data?.identityConsistent ? <CheckCircle2 /> : <AlertTriangle />}
              {profileQuery.data?.identityConsistent ? t("凭据一致") : t("需要核验")}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="grid gap-5 md:grid-cols-2">
          <p className="text-sm text-muted-foreground">{t("已连接的账号可在下方设为默认。额度详情请前往“账号与额度”。")}</p>
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-xs text-muted-foreground md:col-span-2">
            <span className="inline-flex items-center gap-1"><Clock3 className="size-3.5"/>{formatFreshness(active?.lastRefreshAt ?? null, locale)}</span>
            <span>Profile：{profileQuery.data?.codexHome || "-"}</span>
            <span>{t("实际 ID：")}{profileQuery.data?.actualAccountId ? `${profileQuery.data.actualAccountId.slice(0, 8)}…` : t("未知")}</span>
            {active && codexPlanDisplay(active).paid && active.hasSubscription ? <><span>{t("套餐到期：")}{formatSubscriptionDate(active.subscriptionExpiresAt, locale)}</span><span>{t("下次续订：")}{formatSubscriptionDate(active.subscriptionRenewsAt, locale)}</span></> : <span>{active ? t(codexPlanDisplay(active).description) : t("等待官方套餐数据")}</span>}
          </div>
        </CardContent>
      </Card> : null}

      <section className="space-y-3">
        <div className="flex items-center justify-between"><h2 className="text-base font-semibold">{managing ? t("已接入账号") : t("账号额度")}</h2><span className="text-sm text-muted-foreground">{accounts.length}{t("个")}</span></div>
        <div className="grid gap-3 lg:grid-cols-2">
          {sortedAccounts.map((account) => {
            const plan = codexPlanDisplay(account);
            const isActive = Boolean(profileQuery.data?.identityConsistent && account.id === profileQuery.data?.selectedAccountId);
            const allHostsCurrent = isActive && devices.every(d=>deviceOnline(d) && d.currentAccountId===account.id && !["attention","failed"].includes(d.task?.state||""));
            const canSwitch = account.status === "active" && account.hasToken;
            const isQueued = (switchStatus?.state === "pending" && switchStatus.accountId === account.id) || devices.some(d=>d.task?.accountId===account.id && devicePending(d));
            const needsRetry = (switchStatus?.accountId === account.id && ["failed", "attention"].includes(switchStatus.state)) || devices.some(d=>d.task?.accountId===account.id && ["failed","attention"].includes(d.task.state));
            return (<Card key={account.id} data-testid="codex-quota-card" data-active-account={isActive} style={isActive ? { borderColor: "#4dbb9c" } : undefined} className={`glass-card rounded-2xl ${isActive ? "border-emerald-500/50 ring-1 ring-emerald-500/15 bg-emerald-500/[0.045]" : "border-border/70"}`}>
                <CardContent className="grid gap-4 p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 gap-3"><div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-muted"><UserRound className="size-5"/></div><div className="min-w-0"><p className="truncate font-semibold" title={account.name}>{account.name}</p><p className="mt-1 text-xs text-muted-foreground">{formatFreshness(account.lastRefreshAt, locale)}</p></div></div>
                    <div className="flex flex-wrap justify-end gap-2"><Badge title={plan.priceNote ? t(plan.priceNote) : undefined} variant="secondary" className={plan.free ? "border-slate-200 bg-slate-100/80 text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300" : ""}>{t(plan.label)}</Badge>{isQueued ? <Badge variant="outline"><Clock3 className="size-3"/>{t("待切换")}</Badge> : null}{isActive ? <Badge className="bg-emerald-600 text-white"><CheckCircle2 className="size-3"/>{devices.length ? allHostsCurrent ? t("双端默认") : t("服务器默认") : t("当前默认")}</Badge> : null}{devices.some(d=>deviceOnline(d)&&d.currentAccountId===account.id) && !allHostsCurrent ? <Badge variant="outline">{t("Mac 默认")}</Badge> : null}</div>
                  </div>
                  {!managing ? <div className="grid gap-4 sm:grid-cols-2"><UsageWindows usage={account.usage}/></div> : null}
                  <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">{plan.free ? <span>{t(plan.description)}</span> : plan.paid && account.hasSubscription ? <><span>{t("套餐到期：")}{formatSubscriptionDate(account.subscriptionExpiresAt, locale)}</span><span>{t("下次续订：")}{formatSubscriptionDate(account.subscriptionRenewsAt, locale)}</span></> : <span>{t(plan.description)}</span>}</div>
                  {devices.filter(d=>!d.knownAccountIds.includes(account.id)).map(d=><Button key={d.id} size="sm" variant="ghost" className="h-auto justify-start px-0 text-xs text-muted-foreground" disabled={authorizeMac.isPending || !deviceOnline(d) || d.task?.state==="authorizing"} onClick={()=>authorizeMac.mutate({deviceId:d.id,accountId:account.id})}>{t("首次在 Mac 使用？完成一次本机授权")}</Button>)}
                  <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-3">
                    {managing ? <span className="text-xs text-muted-foreground">{t("状态：")}{account.status} · {account.hasToken ? t("凭证可用") : t("缺少凭证")}</span> : <Button size="sm" variant="outline" disabled={refreshMutation.isPending || !account.hasToken} onClick={() => refreshMutation.mutate(account.id)}><RefreshCw className="size-3.5"/>{t("刷新此账号额度")}</Button>}
                    <Button size="sm" variant={allHostsCurrent ? "outline" : "default"} onClick={() => switchMutation.mutate(account.id)} disabled={isQueued || (allHostsCurrent && !needsRetry) || !canSwitch || switchMutation.isPending || cancelSwitchMutation.isPending}>
                      {switchMutation.isPending && switchMutation.variables === account.id ? <Loader2 className="animate-spin"/> : <ShieldCheck />}{isQueued ? t("等待切换") : needsRetry ? t("重试切换") : allHostsCurrent ? t("当前默认") : t("切换到此账号")}
                    </Button>
                  </div>
                </CardContent>
              </Card>);
        })}
        </div>
      </section>
      {managing ? <AddAccountDialog open={addAccountOpen} onOpenChange={setAddAccountOpen} onCompleted={async () => { await queryClient.invalidateQueries({ queryKey: ["personal"] }); }}/> : null}
    </div>);
}
