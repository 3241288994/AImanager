"use client";

import {
  Activity, AlertTriangle, ArrowRight, Bot, CheckCircle2, FolderGit2,
  BrainCircuit, HardDrive, Laptop, MoreHorizontal, Pencil, Plus, RefreshCw, Server, Sparkles, Star, Trash2, Wrench,
} from "lucide-react";
import { getAppErrorMessage } from "@/lib/api/transport";
import type { LabContextHealthState, LabContextWorkspace } from "@/types/labcontext";
import { useRuntimeCapabilities } from "@/hooks/useRuntimeCapabilities";
import { useLabContextRouter } from "@/hooks/useLabContextRouter";
import {
  LABCONTEXT_LOCATION_LABELS,
  useLabContextWorkspace,
} from "@/hooks/useLabContextWorkspace";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { LocationSwitcher } from "@/components/labcontext/location-switcher";
import { ConnectionCenter } from "@/components/labcontext/connection-center";
import { ResearchMapPanel } from "@/components/labcontext/research-map-panel";

const HEALTH_LABELS: Record<LabContextHealthState, string> = {
  healthy: "正常", degraded: "部分降级", unknown: "无法观测", down: "异常",
};
const HEALTH_VARIANTS: Record<LabContextHealthState, "default" | "secondary" | "outline" | "destructive"> = {
  healthy: "default", degraded: "secondary", unknown: "outline", down: "destructive",
};
const TOOL_LATENCY = { instant: "即时", indexed: "索引查询", codex: "Codex 分析" } as const;

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${(value / 1024 ** 3).toFixed(1)} GB`;
}

function formatTime(value?: string | null): string {
  return value ? new Date(value).toLocaleString() : "未知";
}

function WorkspaceMenu({ workspace, onMap, onDefault, onRefresh, onGenerate, onDelete }: {
  workspace: LabContextWorkspace;
  onMap: () => void;
  onDefault: () => void;
  onRefresh: () => void;
  onGenerate: () => void;
  onDelete: () => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger><Button variant="ghost" size="icon-sm" aria-label={`${workspace.name} 操作`}><MoreHorizontal /></Button></DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-64">
        <DropdownMenuItem className="gap-2 whitespace-nowrap" onClick={onMap}><BrainCircuit className="size-4" />打开研究图</DropdownMenuItem>
        <DropdownMenuItem className="gap-2 whitespace-nowrap" onClick={onDefault} disabled={workspace.isDefault}><Star className="size-4" />设为当前连接默认</DropdownMenuItem>
        <DropdownMenuItem className="gap-2 whitespace-nowrap" onClick={onRefresh}><RefreshCw className="size-4" />刷新索引与覆盖</DropdownMenuItem>
        <DropdownMenuItem className="gap-2 whitespace-nowrap" onClick={onGenerate}><Sparkles className="size-4" />用 Codex 重新生成概述</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={onDelete} disabled={workspace.isDefault} className="gap-2 whitespace-nowrap text-destructive focus:text-destructive"><Trash2 className="size-4" />删除工作区注册</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export default function LabContextPage() {
  const { isDesktopRuntime } = useRuntimeCapabilities();
  const router = useLabContextRouter(!isDesktopRuntime);
  const localEnabled = isDesktopRuntime || router.localAvailable;
  const workspace = useLabContextWorkspace(localEnabled);
  const {
    location, switchLocation, overviewQuery, data, selected, setSelectedId,
    workspaceDialog, setWorkspaceDialog, workspaceForm, setWorkspaceForm,
    setWorkspaceFormLocation, openWorkspaceDialog, overviewEditor, setOverviewEditor,
    testResult, setTestResult, contextMenu, setContextMenu, openContextMenu,
    deleteTarget, setDeleteTarget, setToolEnabled, openResearchMap,
    defaultMutation, refreshMutation, policyMutation, testMutation,
    workspaceMutation, overviewMutation, generateOverviewMutation,
    deleteMutation, workerMutation, pickDirectoryMutation,
  } = workspace;

  return (
    <main className="mx-auto flex w-full max-w-[1500px] flex-col gap-6 px-4 py-6 md:px-8">
      <header>
        <Card className="glass-card overflow-hidden border-primary/15">
          <CardContent className="flex flex-col gap-5 p-5 sm:p-6 xl:flex-row xl:items-center xl:justify-between">
            <div className="flex min-w-0 items-start gap-4">
              <div className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-primary/10 text-primary ring-1 ring-primary/15">
                <BrainCircuit className="size-6" />
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">AImanager · LabContext</p>
                  <Badge variant="outline">{location === "local" ? "当前设备" : "远程连接"}</Badge>
                </div>
                <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">让 ChatGPT 读懂你的项目</h1>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                  绝对路径可以临时直读；长期项目可固定为工作区，持续维护概述、实验与研究图。
                </p>
              </div>
            </div>
            <div className="flex shrink-0 flex-col gap-2 sm:flex-row sm:items-center">
              <LocationSwitcher location={location} localEnabled={localEnabled} onChange={switchLocation} />
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => overviewQuery.refetch()} disabled={overviewQuery.isFetching}>
                  <RefreshCw className={overviewQuery.isFetching ? "animate-spin motion-reduce:animate-none" : ""} />
                  刷新
                </Button>
                <Button onClick={openWorkspaceDialog} disabled={overviewQuery.isError}>
                  <Plus />添加工作区
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </header>

      {!isDesktopRuntime ? (
        <ConnectionCenter
          status={router.data?.status}
          error={router.error}
          isLoading={router.isLoading}
          isFetching={router.isFetching}
          onRetry={() => { void router.refetch(); }}
        />
      ) : null}

      {data?.toolPolicy.tools.some((tool) => tool.name === "inspect_path" && tool.enabled) ? <div className="flex items-start gap-3 rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-4 py-3 text-sm">
        <FolderGit2 className="mt-0.5 size-4 shrink-0 text-emerald-600" />
        <p className="text-muted-foreground">
          <span className="font-medium text-foreground">路径直读无需注册：</span>
          在 ChatGPT 中粘贴当前连接可访问的绝对文件或文件夹路径，并说明“本地”或“服务器”。
          添加工作区仅用于需要长期上下文、实验索引和研究图的项目。
        </p>
      </div> : null}

      {overviewQuery.isError ? (
        <Card className="glass-card border-destructive/30">
          <CardContent className="grid gap-5 p-5 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
            <div className="flex min-w-0 items-start gap-3">
              <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-destructive/10 text-destructive">
                <AlertTriangle className="size-5" />
              </div>
              <div className="min-w-0">
                <p className="font-medium">无法连接{LABCONTEXT_LOCATION_LABELS[location]}的 LabContext 管理接口</p>
                <p className="mt-1 break-words text-sm text-muted-foreground">{getAppErrorMessage(overviewQuery.error)}</p>
                <p className="mt-3 text-xs leading-5 text-muted-foreground">
                  {location === "local"
                    ? "请确认本机 LabContext 已启动，并检查 CODEXMANAGER_LABCONTEXT_LOCAL_* 配置。管理连接仅允许回环地址。"
                    : "请检查服务器服务、SSH 端口转发与管理地址。Tunnel 是否可供 ChatGPT 访问需要在连接恢复后单独验证。"}
                </p>
              </div>
            </div>
            <div className="flex gap-2">
              {location === "local" ? <Button variant="outline" onClick={() => switchLocation("server")}><Server />切回服务器</Button> : null}
              <Button onClick={() => overviewQuery.refetch()} disabled={overviewQuery.isFetching}>
                <RefreshCw className={overviewQuery.isFetching ? "animate-spin motion-reduce:animate-none" : ""} />重试连接
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {data ? (
        <>
          <Card className="glass-card border-primary/20">
            <CardHeader className="pb-3"><div className="flex flex-wrap items-center justify-between gap-2"><div><CardTitle className="flex items-center gap-2 text-base">{location === "local" ? <Laptop className="size-4" /> : <Server className="size-4" />}{LABCONTEXT_LOCATION_LABELS[location]}服务链</CardTitle><CardDescription>只展示能够验证的环节；Tunnel 无 heartbeat 时不会伪装成健康。</CardDescription></div><Badge variant={HEALTH_VARIANTS[data.health.overall]}>{HEALTH_LABELS[data.health.overall]}</Badge></div></CardHeader>
            <CardContent className="space-y-3">
              <div className="grid gap-2 sm:grid-cols-3">
                <div className="rounded-xl border bg-background/45 p-3"><p className="text-2xl font-semibold tabular-nums">{data.workspaces.length}</p><p className="mt-1 text-xs text-muted-foreground">已注册工作区</p></div>
                <div className="rounded-xl border bg-background/45 p-3"><p className="text-2xl font-semibold tabular-nums">{data.toolPolicy.tools.filter((tool) => tool.enabled).length}</p><p className="mt-1 text-xs text-muted-foreground">已启用模型工具</p></div>
                <div className="rounded-xl border bg-background/45 p-3"><p className="text-2xl font-semibold tabular-nums">{data.jobs.jobs.filter((job) => job.status === "running").length}</p><p className="mt-1 text-xs text-muted-foreground">运行中分析任务</p></div>
              </div>
              {data.health.checks.length ? <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
                {data.health.checks.map((check) => <div key={check.id} className="rounded-xl border bg-background/45 p-3"><div className="flex items-center justify-between gap-2"><p className="text-sm font-medium">{check.label}</p><span className={`size-2 rounded-full ${check.status === "healthy" ? "bg-emerald-500" : check.status === "down" ? "bg-red-500" : "bg-amber-500"}`} /></div><p className="mt-2 line-clamp-2 text-xs text-muted-foreground" title={check.detail}>{check.detail}</p></div>)}
              </div> : null}
              <div className="flex flex-col gap-3 rounded-xl border border-primary/15 bg-primary/5 p-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex flex-wrap items-center gap-2 text-xs font-medium">
                  <span className="rounded-full bg-background px-2.5 py-1 ring-1 ring-border">1. 路径已授权或工作区已注册</span>
                  <ArrowRight className="size-3 text-muted-foreground" />
                  <span className="rounded-full bg-background px-2.5 py-1 ring-1 ring-border">2. MCP 工具可用</span>
                  <ArrowRight className="size-3 text-muted-foreground" />
                  <span className="rounded-full bg-background px-2.5 py-1 ring-1 ring-border">3. Secure MCP Tunnel</span>
                </div>
                <p className="text-xs text-muted-foreground">工作区健康不代表 ChatGPT Tunnel 已注册，请以工具实测为准。</p>
              </div>
            </CardContent>
          </Card>

          <section className="space-y-3">
            <div className="flex items-center justify-between"><div><h2 className="text-lg font-semibold">{LABCONTEXT_LOCATION_LABELS[location]}工作区</h2><p className="text-xs text-muted-foreground">选择一个项目查看研究图；默认工作区仅作用于当前连接。</p></div><Badge variant="outline">{data.workspaces.length} 个</Badge></div>
            <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
              {!data.workspaces.length ? (
                <Card className="glass-card border-dashed lg:col-span-2 xl:col-span-3">
                  <CardContent className="flex flex-col items-center px-6 py-12 text-center">
                    <div className="flex size-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                      {location === "local" ? <HardDrive className="size-7" /> : <FolderGit2 className="size-7" />}
                    </div>
                    <h3 className="mt-4 text-base font-semibold">还没有固定工作区</h3>
                    <p className="mt-2 max-w-lg text-sm leading-6 text-muted-foreground">
                      {location === "local"
                        ? "临时查看可以直接在 ChatGPT 粘贴本机绝对路径；固定后可获得项目概述、实验索引与研究图。"
                        : "临时查看可以直接在 ChatGPT 粘贴服务器绝对路径；固定后 LabContext 会维护长期项目上下文。"}
                    </p>
                    <Button className="mt-5" onClick={openWorkspaceDialog}><Plus />固定第一个工作区<ArrowRight /></Button>
                  </CardContent>
                </Card>
              ) : null}
              {data.workspaces.map((workspace, workspaceIndex) => (
                <Card
                  key={workspace.workspaceId}
                  className={`glass-card relative min-w-0 cursor-pointer transition-[border-color,box-shadow,transform] motion-reduce:transform-none hover:-translate-y-0.5 hover:shadow-md ${selected?.workspaceId === workspace.workspaceId ? "border-primary/55 bg-primary/[0.035]" : "border-border/70 hover:border-primary/30"}`}
                  onClick={() => setSelectedId(workspace.workspaceId)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelectedId(workspace.workspaceId);
                    }
                  }}
                  role="button"
                  tabIndex={0}
                  aria-pressed={selected?.workspaceId === workspace.workspaceId}
                  onContextMenu={(event) => { event.preventDefault(); openContextMenu(workspace, { x: event.clientX, y: event.clientY }); }}
                >
                  <CardContent className="grid min-h-64 min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-4 overflow-hidden p-5">
                    <div className="peer/workspace-header flex items-start justify-between gap-3"><div className="flex min-w-0 gap-3"><div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/8 text-primary ring-1 ring-primary/10">{workspace.location === "local" ? <HardDrive className="size-5" /> : <FolderGit2 className="size-5" />}</div><div className="min-w-0"><div className="flex items-center gap-2"><p className="truncate font-semibold">{workspace.name}</p><Badge variant="outline" className="shrink-0">{LABCONTEXT_LOCATION_LABELS[workspace.location]}</Badge>{workspace.isDefault ? <Star className="size-4 fill-amber-400 text-amber-500" aria-label="默认工作区" /> : null}</div><p className="mt-1 truncate font-mono text-xs text-muted-foreground">{workspace.workspaceId} · {workspace.root}</p></div></div><WorkspaceMenu workspace={workspace} onMap={() => openResearchMap(workspace.workspaceId)} onDefault={() => defaultMutation.mutate(workspace)} onRefresh={() => refreshMutation.mutate(workspace)} onGenerate={() => generateOverviewMutation.mutate({ target: workspace, refresh: true })} onDelete={() => setDeleteTarget(workspace)} /></div>
                    <div className="min-w-0 overflow-hidden">
                      <Tooltip>
                        <TooltipTrigger
                          className="line-clamp-4 w-full min-w-0 max-w-full cursor-help break-words text-left text-sm leading-6 text-muted-foreground [overflow-wrap:anywhere]"
                          aria-label={`${workspace.name} 完整概述`}
                        >
                          {workspace.description}
                        </TooltipTrigger>
                        <TooltipContent
                          side="top"
                          align={workspaceIndex === 0 ? "start" : "end"}
                          sideOffset={8}
                          collisionPadding={16}
                          className="block max-h-[min(24rem,70vh)] w-[min(36rem,calc(100vw-2rem))] max-w-none overflow-y-auto whitespace-normal p-4 text-left text-sm leading-6 [overflow-wrap:anywhere]"
                        >
                          <p className="mb-1 font-medium text-foreground">{workspace.name} · 完整概述</p>
                          <p className="text-muted-foreground">{workspace.description}</p>
                        </TooltipContent>
                      </Tooltip>
                      <div className="mt-1 flex min-w-0 flex-wrap items-center gap-2 text-[11px] text-muted-foreground"><span className="min-w-0 break-words [overflow-wrap:anywhere]">{workspace.overviewSource === "reviewed" ? "人工维护概述" : workspace.overviewSource === "codex" ? "Codex 基于项目与最近会话生成" : workspace.context.generation?.status === "running" || workspace.context.generation?.status === "not_started" ? "等待 Codex 生成首版概述" : "根据项目文件自动提取"}</span>{workspace.context.generation?.status === "running" ? <Badge variant="outline" className="shrink-0 gap-1"><RefreshCw className="size-3 animate-spin" />生成中</Badge> : workspace.context.generation?.status === "failed" ? <Badge variant="destructive" className="shrink-0" title={workspace.context.generation.error || "Codex 概述生成失败，请重试"}>生成失败</Badge> : null}</div>
                    </div>
                    <div className="flex flex-wrap gap-1.5">{workspace.readableAssets.filter((asset) => asset.fileCount > 0).map((asset) => <Badge key={asset.kind} variant="secondary">{asset.label} {asset.fileCount}</Badge>)}</div>
                    <button className="min-w-0 rounded-lg border bg-muted/25 px-3 py-2 text-left transition-colors hover:bg-muted/50" onClick={(event) => { event.stopPropagation(); openResearchMap(workspace.workspaceId); }}><div className="flex items-center justify-between gap-2"><span className="flex items-center gap-1.5 text-xs font-medium"><BrainCircuit className="size-3.5 text-primary" />研究图</span><span className="text-[10px] text-muted-foreground">{workspace.researchMap.status === "ready" ? `${workspace.researchMap.counts.nodes} 节点` : "待初始化"}</span></div><p className="mt-1 truncate text-[11px] text-muted-foreground">{workspace.researchMap.currentTarget?.title || workspace.researchMap.coreIdea?.title || "建立项目的目标、分支与证据关系"}</p>{workspace.researchMap.pendingProposals ? <Badge variant="secondary" className="mt-1.5">{workspace.researchMap.pendingProposals} 个待审提案</Badge> : null}</button>
                    <div className="mt-auto flex min-w-0 items-center justify-between gap-2 border-t pt-3"><p className="min-w-0 truncate text-xs text-muted-foreground">{workspace.git.dirty ? `${workspace.git.changedPathCount} 项未提交变更` : "Git 工作树干净"}</p><Button className="shrink-0" size="sm" variant="ghost" onClick={(event) => { event.stopPropagation(); setOverviewEditor({ location: workspace.location, workspaceId: workspace.workspaceId, name: workspace.name, overview: workspace.description }); }}><Pencil />编辑概述</Button></div>
                  </CardContent>
                  <div className="pointer-events-none absolute inset-x-3 top-[calc(100%-10px)] z-30 hidden rounded-lg border bg-popover p-4 text-popover-foreground shadow-xl peer-focus-within/workspace-header:block peer-hover/workspace-header:block">
                    <p className="font-medium">模型可以了解什么</p>
                    <div className="mt-2 grid gap-2">{workspace.readableAssets.map((asset) => <div key={asset.kind} className="flex items-start justify-between gap-4 text-xs"><div><p className="font-medium">{asset.label}</p><p className="text-muted-foreground">{asset.meaning}</p></div><span className="shrink-0">{asset.fileCount ? `${asset.fileCount} 项` : "未发现"}</span></div>)}</div>
                    <div className="mt-3 min-w-0 border-t pt-3 text-xs text-muted-foreground"><p className="break-all">路径：{workspace.root}</p><p className="mt-1 break-all">Git：{workspace.git.branch || "不可用"} · {workspace.git.commit || workspace.git.headState}</p><p className="mt-1 break-all">概述文件：{workspace.context.path}</p></div>
                  </div>
                </Card>
              ))}
            </div>
          </section>

          {selected ? (
            <>
            <section className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
              <Card className="glass-card"><CardHeader><div className="flex flex-wrap items-center justify-between gap-3"><div><CardTitle className="text-base">当前查看：{selected.name}</CardTitle><CardDescription>测试可确认当前 {LABCONTEXT_LOCATION_LABELS[selected.location]} 连接实际向 ChatGPT 返回的项目背景。</CardDescription></div><div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={() => testMutation.mutate({ tool: "workspace_overview", target: selected })} disabled={testMutation.isPending}><CheckCircle2 />测试 ChatGPT 所见内容</Button><Button variant="outline" size="sm" onClick={() => refreshMutation.mutate(selected)} disabled={refreshMutation.isPending}><RefreshCw className={refreshMutation.isPending ? "animate-spin motion-reduce:animate-none" : ""} />重新扫描项目</Button></div></div></CardHeader></Card>
              <Card className="glass-card"><CardHeader className="pb-3"><CardTitle className="flex items-center gap-2 text-base"><Bot className="size-4" />Codex analysis worker</CardTitle><CardDescription>仅影响当前 {LABCONTEXT_LOCATION_LABELS[location]} 连接之后新建的深度分析任务。</CardDescription></CardHeader><CardContent className="grid grid-cols-2 gap-3"><div className="grid gap-1.5"><Label htmlFor="worker-model">模型</Label><select id="worker-model" className="h-9 rounded-lg border bg-background px-3 text-sm" value={data.workerConfig.model} disabled={workerMutation.isPending} onChange={(event) => { const model = event.target.value; const efforts = data.workerConfig.availableEfforts[model] || ["medium"]; const effort = efforts.includes(data.workerConfig.reasoningEffort) ? data.workerConfig.reasoningEffort : "medium"; workerMutation.mutate({ location, model, reasoningEffort: effort }); }}>{data.workerConfig.availableModels.map((model) => <option key={model} value={model}>{model}</option>)}</select></div><div className="grid gap-1.5"><Label htmlFor="worker-effort">思考强度</Label><select id="worker-effort" className="h-9 rounded-lg border bg-background px-3 text-sm" value={data.workerConfig.reasoningEffort} disabled={workerMutation.isPending} onChange={(event) => workerMutation.mutate({ location, model: data.workerConfig.model, reasoningEffort: event.target.value })}>{(data.workerConfig.availableEfforts[data.workerConfig.model] || []).map((effort) => <option key={effort} value={effort}>{effort}</option>)}</select></div></CardContent></Card>
            </section>
            <ResearchMapPanel workspace={selected} />
            </>
          ) : null}

          <section className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
            <Card className="glass-card">
              <CardHeader><div className="flex flex-wrap items-center justify-between gap-3"><div><CardTitle className="flex items-center gap-2 text-base"><Wrench className="size-4" />模型可见工具</CardTitle><CardDescription>工具名与 schema 保持稳定；开关由当前 {LABCONTEXT_LOCATION_LABELS[location]} 连接的策略执行。</CardDescription></div><div className="flex gap-2"><Button size="sm" variant="outline" disabled={policyMutation.isPending} onClick={() => policyMutation.mutate({ location, profile: "fast", disabledTools: ["request_analysis"] })}>快速只读</Button><Button size="sm" variant="outline" disabled={policyMutation.isPending} onClick={() => policyMutation.mutate({ location, profile: "research", disabledTools: [] })}>科研讨论</Button></div></div></CardHeader>
              <CardContent className="grid gap-2 md:grid-cols-2">{data.toolPolicy.tools.map((tool) => <div key={tool.name} className="flex items-start justify-between gap-3 rounded-lg border p-3"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><code className="text-xs font-semibold">{tool.name}</code><Badge variant="outline">{TOOL_LATENCY[tool.latencyClass]}</Badge>{tool.computeCost === "codex_tokens" ? <Badge variant="secondary">消耗 Codex 额度</Badge> : null}</div><p className="mt-2 text-xs text-muted-foreground">{tool.description}</p>{tool.dependencies.length ? <p className="mt-1 text-[11px] text-muted-foreground">依赖：{tool.dependencies.join(", ")}</p> : null}</div><Switch checked={tool.enabled} disabled={["list_workspaces", "get_job"].includes(tool.name) || policyMutation.isPending} onCheckedChange={(checked) => setToolEnabled(tool.name, checked)} aria-label={`${tool.name} 启用状态`} /></div>)}</CardContent>
            </Card>

            <Card className="glass-card">
              <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Bot className="size-4" />Analysis Job Center</CardTitle><CardDescription>跟踪异步 Codex 分析，不再依赖网页反复猜测状态。</CardDescription></CardHeader>
              <CardContent className="max-h-[440px] space-y-2 overflow-y-auto">{data.jobs.jobs.length ? data.jobs.jobs.map((job) => <div key={job.jobId} className="rounded-lg border p-3"><div className="flex items-center justify-between gap-2"><code className="truncate text-xs">{job.jobId}</code><Badge variant={job.status === "completed" ? "secondary" : job.status === "failed" ? "destructive" : "outline"}>{job.status}</Badge></div><p className="mt-2 text-xs">{job.progress || "没有进度信息"}</p><div className="mt-2 flex flex-wrap gap-x-3 text-[11px] text-muted-foreground"><span>{job.workspaceId}</span><span>{formatTime(job.updatedAt)}</span>{job.errorType ? <span>{job.errorType}</span> : null}</div></div>) : <p className="text-sm text-muted-foreground">尚无分析任务。</p>}</CardContent>
            </Card>
          </section>

          <Card className="glass-card">
            <CardHeader><div className="flex items-center justify-between"><div><CardTitle className="flex items-center gap-2 text-base"><Activity className="size-4" />最近工具调用</CardTitle><CardDescription>审计元数据不保存问题正文、证据内容或原始 Codex 会话。</CardDescription></div><Badge variant="outline">最近 {data.activity.records.length} 条</Badge></div></CardHeader>
            <CardContent><div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="border-b text-xs text-muted-foreground"><tr><th className="pb-2 font-medium">时间</th><th className="pb-2 font-medium">工具</th><th className="pb-2 font-medium">工作区</th><th className="pb-2 font-medium">状态/结果</th><th className="pb-2 font-medium">Job</th></tr></thead><tbody>{data.activity.records.map((record, index) => <tr key={`${record.timestamp}-${index}`} className="border-b last:border-0"><td className="py-2 pr-4 whitespace-nowrap text-xs">{formatTime(record.timestamp)}</td><td className="py-2 pr-4"><code className="text-xs">{record.event}</code></td><td className="py-2 pr-4 text-xs">{record.workspaceId || "-"}</td><td className="py-2 pr-4 text-xs">{record.status || (record.resultCount != null ? `${record.resultCount} 条` : record.experimentCount != null ? `${record.experimentCount} 个实验` : "成功")}</td><td className="py-2 text-xs">{record.jobId || "-"}</td></tr>)}</tbody></table></div></CardContent>
          </Card>
        </>
      ) : !overviewQuery.isError ? <Card className="glass-card"><CardContent className="grid gap-3 p-6" aria-live="polite"><div className="h-4 w-44 animate-pulse rounded bg-muted motion-reduce:animate-none" /><div className="h-20 animate-pulse rounded-xl bg-muted/70 motion-reduce:animate-none" /><p className="text-sm text-muted-foreground">正在读取 {LABCONTEXT_LOCATION_LABELS[location]} LabContext 控制面…</p></CardContent></Card> : null}

      {contextMenu ? <div className="fixed z-50 min-w-64 rounded-lg border bg-popover p-1 text-sm shadow-lg" style={{ left: contextMenu.x, top: contextMenu.y }} onClick={(event) => event.stopPropagation()}><button className="flex w-full items-center gap-2 whitespace-nowrap rounded px-3 py-2 text-left hover:bg-muted" onClick={() => { openResearchMap(contextMenu.workspace.workspaceId); setContextMenu(null); }}><BrainCircuit className="size-4" />打开研究图</button><button className="flex w-full items-center gap-2 whitespace-nowrap rounded px-3 py-2 text-left hover:bg-muted disabled:opacity-50" disabled={contextMenu.workspace.isDefault} onClick={() => { defaultMutation.mutate(contextMenu.workspace); setContextMenu(null); }}><Star className="size-4" />设为当前连接默认</button><button className="flex w-full items-center gap-2 whitespace-nowrap rounded px-3 py-2 text-left hover:bg-muted" onClick={() => { refreshMutation.mutate(contextMenu.workspace); setContextMenu(null); }}><RefreshCw className="size-4" />刷新索引与覆盖</button><button className="flex w-full items-center gap-2 whitespace-nowrap rounded px-3 py-2 text-left hover:bg-muted" onClick={() => { generateOverviewMutation.mutate({ target: contextMenu.workspace, refresh: true }); setContextMenu(null); }}><Sparkles className="size-4" />用 Codex 重新生成概述</button><div className="my-1 border-t" /><button className="flex w-full items-center gap-2 whitespace-nowrap rounded px-3 py-2 text-left text-destructive hover:bg-destructive/10 disabled:opacity-50" disabled={contextMenu.workspace.isDefault} onClick={() => { setDeleteTarget(contextMenu.workspace); setContextMenu(null); }}><Trash2 className="size-4" />删除工作区注册</button></div> : null}

      <Dialog open={workspaceDialog} onOpenChange={setWorkspaceDialog}>
        <DialogContent className="md:max-w-2xl">
          <DialogHeader><DialogTitle>添加工作区</DialogTitle><DialogDescription>两步完成注册：先选择项目位置，再确认名称与目录。添加后会自动扫描项目并生成首版概述。</DialogDescription></DialogHeader>
          <div className="grid gap-5 py-2">
            <div className="grid gap-2">
              <Label><span className="mr-2 inline-flex size-5 items-center justify-center rounded-full bg-primary text-[11px] text-primary-foreground">1</span>项目位于哪里？</Label>
              <LocationSwitcher expanded location={workspaceForm.location} localEnabled={localEnabled} onChange={setWorkspaceFormLocation} />
              {!isDesktopRuntime ? <p className="text-xs text-muted-foreground">Web 版通过本机 Router 管理目录；只有 Router 已启动且配置了 local Provider 时才能选择本地电脑。</p> : null}
            </div>
            <div className="grid gap-4 rounded-xl border bg-muted/20 p-4">
              <Label><span className="mr-2 inline-flex size-5 items-center justify-center rounded-full bg-primary text-[11px] text-primary-foreground">2</span>确认项目信息</Label>
              <div className="grid gap-2"><Label htmlFor="workspace-name" className="text-xs text-muted-foreground">工作区名称</Label><Input id="workspace-name" autoFocus value={workspaceForm.name} onChange={(event) => setWorkspaceForm((value) => ({ ...value, name: event.target.value }))} placeholder="例如：蛋白质结构预测" /></div>
              <div className="grid gap-2"><Label htmlFor="workspace-root" className="text-xs text-muted-foreground">{workspaceForm.location === "local" ? "本地项目目录" : "服务器绝对路径"}</Label><div className="flex flex-col gap-2 sm:flex-row"><Input id="workspace-root" readOnly={workspaceForm.location === "local" && isDesktopRuntime} value={workspaceForm.root} onChange={(event) => setWorkspaceForm((value) => ({ ...value, root: event.target.value }))} placeholder={workspaceForm.location === "local" ? (isDesktopRuntime ? "点击选择一个项目文件夹" : "/Users/you/research/project") : "/srv/research/project"} />{workspaceForm.location === "local" && isDesktopRuntime ? <Button type="button" variant="outline" className="sm:shrink-0" disabled={pickDirectoryMutation.isPending} onClick={() => pickDirectoryMutation.mutate()}><HardDrive />{pickDirectoryMutation.isPending ? "选择中…" : "选择文件夹"}</Button> : null}</div>{workspaceForm.location === "local" ? <p className="text-xs leading-5 text-muted-foreground">{isDesktopRuntime ? "目录会由系统选择器显式授权，选择后将自动使用文件夹名；不会开放整个磁盘或用户目录。" : "填写运行本机 LabContext 的电脑能够访问的绝对路径；Router 只会把它交给 local Provider。"}</p> : <p className="text-xs leading-5 text-muted-foreground">填写 LabContext 服务所在服务器能够访问的绝对路径，不是浏览器或本机路径。</p>}</div>
            </div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setWorkspaceDialog(false)}>取消</Button><Button disabled={workspaceMutation.isPending || !workspaceForm.name.trim() || !workspaceForm.root.trim()} onClick={() => workspaceMutation.mutate(workspaceForm)}>{workspaceMutation.isPending ? "正在识别项目…" : "添加并自动配置"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(overviewEditor)} onOpenChange={(open) => { if (!open) setOverviewEditor(null); }}>
        <DialogContent>
          <DialogHeader><DialogTitle>编辑工作区概述</DialogTitle><DialogDescription>这段内容会写入工作区的 context.yaml，并作为 ChatGPT 理解项目的优先背景。建议写清研究目标、当前阶段和主要对象。</DialogDescription></DialogHeader>
          {overviewEditor ? <div className="grid gap-2 py-2"><Label htmlFor="workspace-overview">{overviewEditor.name}</Label><Textarea id="workspace-overview" className="min-h-36" maxLength={1200} value={overviewEditor.overview} onChange={(event) => setOverviewEditor((value) => value ? { ...value, overview: event.target.value } : value)} /><p className="text-right text-xs text-muted-foreground">{overviewEditor.overview.length}/1200</p></div> : null}
          <DialogFooter className="sm:justify-between"><Button variant="outline" disabled={generateOverviewMutation.isPending} onClick={() => { const workspace = data?.workspaces.find((item) => item.workspaceId === overviewEditor?.workspaceId); if (workspace) generateOverviewMutation.mutate({ target: workspace, refresh: true }); }}><Sparkles />{generateOverviewMutation.isPending ? "正在启动…" : "让 Codex 重新生成"}</Button><div className="flex gap-2"><Button variant="outline" onClick={() => setOverviewEditor(null)}>取消</Button><Button disabled={!overviewEditor?.overview.trim() || overviewMutation.isPending} onClick={() => overviewEditor && overviewMutation.mutate(overviewEditor)}>{overviewMutation.isPending ? "正在保存…" : "保存概述"}</Button></div></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(deleteTarget)} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}>
        <DialogContent>
          <DialogHeader><DialogTitle>删除工作区注册？</DialogTitle><DialogDescription>将从{deleteTarget ? LABCONTEXT_LOCATION_LABELS[deleteTarget.location] : "当前连接"}的 LabContext 中移除“{deleteTarget?.name}”。项目目录、代码、实验结果和 context.yaml 都不会被删除。</DialogDescription></DialogHeader>
          <DialogFooter><Button variant="outline" onClick={() => setDeleteTarget(null)}>取消</Button><Button variant="destructive" disabled={!deleteTarget || deleteTarget.isDefault || deleteMutation.isPending} onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget)}><Trash2 />{deleteMutation.isPending ? "正在移除…" : "仅移除注册"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(testResult)} onOpenChange={(open) => { if (!open) setTestResult(null); }}>
        <DialogContent className="md:max-w-3xl">
          <DialogHeader><DialogTitle>模型可见结果验证</DialogTitle><DialogDescription>这是 LabContext 工具实际返回给模型的结构化内容，不是控制台重新生成的摘要。</DialogDescription></DialogHeader>
          {testResult ? <div className="grid min-h-0 gap-3"><div className="flex flex-wrap gap-2 text-xs"><Badge variant="outline">{testResult.tool}</Badge><Badge variant="secondary">{testResult.elapsedMs} ms</Badge><Badge variant="secondary">{formatBytes(testResult.responseBytes)}</Badge><span className="text-muted-foreground">{formatTime(testResult.testedAt)}</span></div><pre className="max-h-[60vh] overflow-auto rounded-lg bg-muted p-4 text-xs">{JSON.stringify(testResult.result, null, 2)}</pre></div> : null}
        </DialogContent>
      </Dialog>
    </main>
  );
}
