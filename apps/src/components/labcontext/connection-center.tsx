"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, CircleDashed,
  Copy, Laptop, Network, RefreshCw, Server, ShieldCheck, Terminal, Wrench,
} from "lucide-react";
import { getAppErrorMessage } from "@/lib/api/transport";
import { buildLabContextRecoveryPlan } from "@/lib/labcontext-recovery";
import type {
  LabContextConnectionStatus,
  LabContextRecoveryStatus,
  LabContextRouterProvider,
} from "@/lib/api/labcontext-router-client";
import {
  getLabContextRecoveryStatus,
  requestLabContextRepair,
} from "@/lib/api/labcontext-router-client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type ConnectionCenterProps = {
  status?: LabContextConnectionStatus;
  error?: unknown;
  isLoading: boolean;
  isFetching: boolean;
  onRetry: () => void;
};

type CheckState = "ready" | "checking" | "degraded" | "unavailable" | "disabled";

type ConnectionCheck = {
  id: string;
  label: string;
  detail: string;
  state: CheckState;
  meta?: string;
  icon: typeof Network;
};

const STATE_LABELS: Record<CheckState, string> = {
  ready: "正常",
  checking: "检查中",
  degraded: "需处理",
  unavailable: "不可用",
  disabled: "未启用",
};

function providerCheck(provider: LabContextRouterProvider): ConnectionCheck {
  const ready = provider.status === "ready" && ["ready", "disabled"].includes(provider.adminStatus);
  const identity = [provider.serverName, provider.serverVersion ? `v${provider.serverVersion}` : null]
    .filter(Boolean)
    .join(" ");
  const facts = [
    identity,
    provider.toolCount != null ? `${provider.toolCount} 个工具` : null,
    provider.workspaceCount != null ? `${provider.workspaceCount} 个工作区` : null,
    provider.latencyMs != null ? `${provider.latencyMs} ms` : null,
  ].filter(Boolean).join(" · ");
  return {
    id: `provider-${provider.id}`,
    label: provider.id === "local" ? "本地 Provider" : "服务器 Provider",
    detail: provider.error || provider.adminError || (ready ? "MCP 初始化、工具列表与真实调用均已通过" : "等待能力验证"),
    state: ready ? "ready" : "unavailable",
    meta: facts || undefined,
    icon: provider.id === "local" ? Laptop : Server,
  };
}

function StateIcon({ state }: { state: CheckState }) {
  if (state === "ready") return <CheckCircle2 className="size-4 text-emerald-600" />;
  if (state === "checking") return <CircleDashed className="size-4 animate-spin text-primary motion-reduce:animate-none" />;
  if (state === "disabled") return <CircleDashed className="size-4 text-muted-foreground" />;
  return <AlertTriangle className="size-4 text-amber-600" />;
}

export function ConnectionCenter({ status, error, isLoading, isFetching, onRetry }: ConnectionCenterProps) {
  const [expanded, setExpanded] = useState(true);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const [repairCopyState, setRepairCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const [repairStatus, setRepairStatus] = useState<LabContextRecoveryStatus | null>(null);
  const [repairError, setRepairError] = useState<string | null>(null);
  const readySeen = useRef(false);
  const overall = status?.overall;

  useEffect(() => {
    if (overall !== "ready") {
      readySeen.current = false;
      return;
    }
    if (readySeen.current) return;
    readySeen.current = true;
    const timer = window.setTimeout(() => setExpanded(false), 1400);
    return () => window.clearTimeout(timer);
  }, [overall]);

  const displayExpanded = overall !== "ready" || expanded;
  const recoveryPlan = useMemo(() => buildLabContextRecoveryPlan(status), [status]);
  const repairInProgress = ["queued", "diagnosing", "restarting", "verifying"].includes(repairStatus?.phase || "");

  useEffect(() => {
    if (!repairInProgress) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      void getLabContextRecoveryStatus()
        .then((next) => {
          if (cancelled) return;
          setRepairStatus(next);
          setRepairError(null);
          if (["succeeded", "failed"].includes(next.phase)) onRetry();
        })
        .catch(() => {
          // Router 会在受控重启期间短暂离线；保持当前阶段并继续轮询。
        });
    }, 1_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [repairInProgress, onRetry]);

  const checks = useMemo<ConnectionCheck[]>(() => {
    if (!status) return [];
    const launcherComponents = status.launcher.components || [];
    const ssh = launcherComponents.find((item) => item.id === "ssh-bridge");
    const launcherReady = status.launcher.status === "running"
      && launcherComponents.every((item) => item.status === "running");
    return [
      {
        id: "router",
        label: "统一 Router",
        detail: `LabContext Router v${status.router.version} 正在响应能力检查`,
        state: status.router.status === "ready" ? "ready" : "unavailable",
        meta: `PID ${status.router.pid}`,
        icon: Network,
      },
      ...(status.launcher.status !== "unknown" ? [{
        id: "launcher",
        label: "进程监督器",
        detail: status.launcher.detail || (launcherReady
          ? "启动器与所有托管子进程均已稳定"
          : "子进程正在启动、重试，或启动器记录已经失效"),
        state: launcherReady
          ? "ready" as const
          : status.launcher.status === "running"
            ? "checking" as const
            : "unavailable" as const,
        meta: status.launcher.launcherPid ? `PID ${status.launcher.launcherPid}` : undefined,
        icon: CircleDashed,
      }] : []),
      ...status.providers.map(providerCheck),
      ...(ssh ? [{
        id: "ssh-bridge",
        label: "SSH 桥接",
        detail: ssh.status === "running"
          ? "转发进程已稳定；服务器 Provider 的真实 MCP 调用决定最终可用性"
          : ssh.status === "starting"
            ? "转发进程正在进行稳定性检查"
            : ssh.status === "retrying"
              ? `转发失败，启动器将在 ${ssh.retryInSeconds ?? 0} 秒后自动重试`
              : `转发进程已退出${ssh.exitCode != null ? `，退出码 ${ssh.exitCode}` : ""}`,
        state: ssh.status === "running"
          ? "ready" as const
          : ssh.status === "starting" || ssh.status === "retrying"
            ? "checking" as const
            : "unavailable" as const,
        meta: ssh.pid ? `PID ${ssh.pid}` : undefined,
        icon: Terminal,
      }] : []),
      {
        id: "tunnel",
        label: "OpenAI Tunnel",
        detail: status.tunnel.detail,
        state: status.tunnel.enabled
          ? (status.tunnel.status === "ready" ? "ready" : "unavailable")
          : "disabled",
        meta: status.tunnel.latencyMs != null ? `${status.tunnel.latencyMs} ms` : undefined,
        icon: ShieldCheck,
      },
    ];
  }, [status]);

  const copyDiagnostics = async () => {
    const value = status
      ? JSON.stringify(status, null, 2)
      : `LabContext Router unavailable\n${getAppErrorMessage(error)}`;
    try {
      await navigator.clipboard.writeText(value);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
    window.setTimeout(() => setCopyState("idle"), 1800);
  };

  const copyRepairCommand = async () => {
    const command = repairStatus?.command || recoveryPlan?.command;
    if (!command) return;
    try {
      await navigator.clipboard.writeText(command);
      setRepairCopyState("copied");
    } catch {
      setRepairCopyState("failed");
    }
    window.setTimeout(() => setRepairCopyState("idle"), 1800);
  };

  const runRepair = async () => {
    setRepairError(null);
    try {
      const next = await requestLabContextRepair();
      setRepairStatus(next);
      if (["succeeded", "failed"].includes(next.phase)) onRetry();
    } catch (repairRequestError) {
      setRepairError(getAppErrorMessage(repairRequestError));
    }
  };

  const headline = isLoading
    ? "正在建立 LabContext 连接"
    : overall === "ready"
      ? "LabContext 本机链路已就绪"
      : overall === "degraded"
        ? "LabContext 当前为降级可用"
        : "LabContext 连接需要处理";
  const summary = isLoading
    ? "正在逐层验证 Router、Provider、SSH 与 OpenAI Tunnel。"
    : overall === "ready"
      ? "Router、Provider 与已启用传输检查通过；ChatGPT 插件的实际可用性以工具调用结果为准。"
      : status
        ? "至少一个环节未通过真实调用验证；下方会保留诊断信息。"
        : "本机 Router 无法访问。若后台服务已配置，请运行 labcontext status 查看原因。";

  return (
    <Card className={`glass-card overflow-hidden ${overall === "ready" ? "border-emerald-500/25" : "border-amber-500/30"}`} aria-live="polite">
      <CardHeader className="gap-3 pb-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className={`mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-xl ${overall === "ready" ? "bg-emerald-500/10" : "bg-amber-500/10"}`}>
              {isLoading || isFetching ? <CircleDashed className="size-5 animate-spin text-primary motion-reduce:animate-none" /> : overall === "ready" ? <CheckCircle2 className="size-5 text-emerald-600" /> : <AlertTriangle className="size-5 text-amber-600" />}
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <CardTitle className="text-base">{headline}</CardTitle>
                <Badge variant={overall === "ready" ? "secondary" : "outline"}>
                  {overall === "ready" ? "本机检查通过" : overall === "degraded" ? "降级可用" : isLoading ? "检查中" : "需要处理"}
                </Badge>
              </div>
              <CardDescription className="mt-1 break-words">{summary}</CardDescription>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={copyDiagnostics}>
              <Copy />{copyState === "copied" ? "已复制" : copyState === "failed" ? "复制失败" : "复制诊断"}
            </Button>
            <Button variant="outline" size="sm" onClick={onRetry} disabled={isFetching}>
              <RefreshCw className={isFetching ? "animate-spin motion-reduce:animate-none" : ""} />重新检测
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setExpanded((value) => !value)} aria-expanded={displayExpanded} disabled={overall !== "ready"}>
              {displayExpanded ? <ChevronUp /> : <ChevronDown />}{displayExpanded ? "收起" : "详情"}
            </Button>
          </div>
        </div>
      </CardHeader>

      {displayExpanded ? (
        <CardContent className="grid gap-4 border-t bg-background/20 pt-4">
          {!status ? (
            <div className="rounded-xl border border-dashed p-4">
              <p className="text-sm font-medium">本机统一 Router 未响应</p>
              <p className="mt-1 break-words text-xs leading-5 text-muted-foreground">{error ? getAppErrorMessage(error) : "正在等待 http://127.0.0.1:1460/api/status"}</p>
              <code className="mt-3 block w-fit rounded-md bg-muted px-2.5 py-1.5 text-xs">labcontext status</code>
            </div>
          ) : (
            <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {checks.map((check) => {
                const Icon = check.icon;
                return (
                  <div key={check.id} className="rounded-xl border bg-background/55 p-3.5">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-2">
                        <Icon className="size-4 shrink-0 text-muted-foreground" />
                        <p className="truncate text-sm font-medium">{check.label}</p>
                      </div>
                      <div className="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
                        <StateIcon state={check.state} />{STATE_LABELS[check.state]}
                      </div>
                    </div>
                    <p className="mt-2 break-words text-xs leading-5 text-muted-foreground">{check.detail}</p>
                    {check.meta ? <p className="mt-2 font-mono text-[11px] text-muted-foreground">{check.meta}</p> : null}
                  </div>
                );
              })}
            </div>
          )}
          {recoveryPlan || (repairStatus && repairStatus.phase !== "idle") || repairError ? (
            <div className={`grid gap-3 rounded-xl border p-3.5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center ${repairStatus?.phase === "succeeded" ? "border-emerald-500/25 bg-emerald-500/5" : repairStatus?.phase === "failed" || repairError ? "border-destructive/25 bg-destructive/5" : "border-amber-500/25 bg-amber-500/5"}`}>
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-sm font-medium">
                  {repairStatus?.phase === "succeeded" ? <CheckCircle2 className="size-4 text-emerald-600" /> : <Wrench className="size-4 text-amber-600" />}
                  {repairStatus?.summary || recoveryPlan?.title || "一键修复未能启动"}
                </div>
                <p className="mt-1.5 whitespace-pre-wrap break-words text-xs leading-5 text-muted-foreground">
                  {repairError || repairStatus?.detail || recoveryPlan?.summary}
                </p>
                {repairStatus?.suggestions?.length ? (
                  <ol className="mt-2 grid gap-1 text-xs leading-5 text-muted-foreground">
                    {repairStatus.suggestions.map((step, index) => <li key={step}>{index + 1}. {step}</li>)}
                  </ol>
                ) : !repairStatus && recoveryPlan ? (
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">点击后会先做安全诊断；只有检查通过才会重启，无法处理时会直接显示具体原因。</p>
                ) : null}
                {repairStatus?.reasonCode ? <p className="mt-2 font-mono text-[11px] text-muted-foreground">原因代码：{repairStatus.reasonCode}</p> : null}
              </div>
              <div className="flex flex-wrap gap-2 lg:justify-end">
                {repairStatus?.command || recoveryPlan?.command ? (
                  <Button variant="outline" size="sm" onClick={copyRepairCommand}>
                    <Copy />
                    {repairCopyState === "copied" ? "已复制" : repairCopyState === "failed" ? "复制失败" : "复制命令"}
                  </Button>
                ) : null}
                {repairStatus?.phase !== "succeeded" ? (
                  <Button size="sm" onClick={runRepair} disabled={repairInProgress}>
                    {repairInProgress ? <CircleDashed className="animate-spin motion-reduce:animate-none" /> : <Wrench />}
                    {repairInProgress ? "正在修复" : repairStatus?.phase === "failed" || repairError ? "再次修复" : "一键修复"}
                  </Button>
                ) : null}
              </div>
            </div>
          ) : null}
          <div className="flex flex-col gap-2 rounded-xl border border-primary/15 bg-primary/5 px-3.5 py-3 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
            <span>“端口存在”不等于“连接成功”：Provider 身份、版本、工具和真实调用通过后才显示本机检查通过；ChatGPT 插件需单独验证。</span>
            {status?.checkedAt ? <span className="shrink-0">检查于 {new Date(status.checkedAt).toLocaleTimeString()}</span> : null}
          </div>
        </CardContent>
      ) : null}
    </Card>
  );
}
