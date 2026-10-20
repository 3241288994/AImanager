"use client";

import { useState } from "react";
import Link from "next/link";
import { Cable, Plus, RefreshCw, ShieldCheck, ArrowUpRight } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAiConnections } from "@/hooks/useAiConnections";
import type { AiConnection, AiConnectionProbe } from "@/lib/api/ai-connections-client";
import { getAppErrorMessage } from "@/lib/api/transport";
import { ManagedCliAccounts } from "@/components/ai/managed-cli-accounts";

const EMPTY: AiConnection = { id: "", name: "", baseUrl: "http://127.0.0.1:16969/v1", credentialSource: "aimanager-env", enabled: true };
const ACCOUNT_STATUS: Record<string, string> = { ready: "就绪", available: "可用", active: "活动", busy: "请求中", cooldown: "冷却中", needs_login: "需要登录", login_required: "需要登录", offline: "离线", unavailable: "不可用", error: "异常", recovering: "恢复中", unknown: "未知" };

export default function ConnectionsPage() {
  const { overview, save, remove, probe } = useAiConnections();
  const [draft, setDraft] = useState<AiConnection | null>(null);
  const [results, setResults] = useState<Record<string, AiConnectionProbe | string>>({});
  const [checkedAt, setCheckedAt] = useState<Record<string, string>>({});
  const busy = save.isPending || remove.isPending || probe.isPending;
  const error = (e: unknown) => toast.error(getAppErrorMessage(e));
  return <div className="mx-auto max-w-6xl space-y-6 p-4 xl:p-6">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="text-2xl font-semibold">AI 接入中心</h2><p className="mt-1 text-sm text-muted-foreground">统一查看官方 CLI 与私有 API 入口。检测与配置作用于服务主机，而非浏览器所在电脑。</p></div>
      <Button variant="outline" disabled={overview.isFetching} onClick={() => void overview.refetch()}><RefreshCw className="mr-2 size-4" />刷新</Button>
    </div>
    <div className="glass-card rounded-xl border p-4 text-sm text-muted-foreground"><ShieldCheck className="mr-2 inline size-4" />仅管理员可用。凭证保留在主机私有配置或环境变量中，不在网页中查看、复制或导出。CLI 订阅登录与网页反代 API 不混用。</div>
    {overview.isPending ? <p role="status">正在读取服务主机接入配置…</p> : null}
    {overview.error ? <div role="alert" className="rounded-xl border border-destructive p-4 text-sm">{getAppErrorMessage(overview.error)}<p className="mt-2">若提示不支持该命令，请升级 AImanager Service 与 Web，而不只是替换前端。</p></div> : null}
    <ManagedCliAccounts compact />
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border/60 px-4 py-3 text-xs text-muted-foreground">
      <span>服务主机：{overview.data?.host ?? "待检测"} · 官方账号与网页 API 独立管理</span>
      <Link href="/" className="inline-flex items-center gap-1 font-medium text-primary">管理 Codex 账号与所有平台额度<ArrowUpRight className="size-3.5" /></Link>
    </div>
    <section className="space-y-3" aria-label="API 入口">
      <div className="flex items-center justify-between"><h3 className="flex items-center gap-2 font-semibold"><Cable className="size-4" />网页账号池与反代 API</h3><Button size="sm" disabled={!overview.data || busy} onClick={() => setDraft({ ...EMPTY })}><Plus className="mr-1 size-4" />添加入口</Button></div>
      <p className="text-sm text-muted-foreground">仅连接主机回环地址；远端服务请先建立获授权的 SSH 通道。模型 ID 以实时目录为准，不将网页别名当作官方模型版本。</p>
      {draft ? <form className="glass-card space-y-4 rounded-xl border p-4" onSubmit={e => {
        e.preventDefault(); save.mutate(draft, { onSuccess: () => { setDraft(null); setResults({}); toast.success("入口已保存"); }, onError: error });
      }}>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="space-y-1 text-sm">入口 ID<Input required pattern="[A-Za-z0-9_-]{1,64}" value={draft.id} readOnly={overview.data?.items.some(i => i.id === draft.id)} onChange={e => setDraft({ ...draft, id: e.target.value })} /></label>
          <label className="space-y-1 text-sm">显示名称<Input required maxLength={80} value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} /></label>
          <label className="space-y-1 text-sm">服务主机 API 地址<Input required type="url" value={draft.baseUrl} onChange={e => setDraft({ ...draft, baseUrl: e.target.value })} /></label>
          <label className="space-y-1 text-sm">凭证来源<select className="h-9 w-full rounded-md border bg-background px-3" value={draft.credentialSource} onChange={e => setDraft({ ...draft, credentialSource: e.target.value as AiConnection["credentialSource"] })}><option value="gemini-web-client">Gemini 私有 client.env</option><option value="aimanager-env">AIMANAGER_UPSTREAM_API_KEY 环境变量</option></select></label>
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.enabled} onChange={e => setDraft({ ...draft, enabled: e.target.checked })} />启用管理检测（不会启动或停止上游账号池）</label>
        <p className="text-xs text-muted-foreground">Gemini 文件：Linux 使用 ~/.config/gemini-web-client/client.env；Mac 使用 ~/.local/share/gemini-web-pool/server-client/client.env。权限须为 0600。不会执行 env 文件内的脚本。</p>
        <div className="flex gap-2"><Button type="submit" disabled={busy}>保存</Button><Button type="button" variant="outline" onClick={() => setDraft(null)}>取消</Button></div>
      </form> : null}
      {overview.data?.items.length === 0 ? <p className="text-sm text-muted-foreground">尚无 API 入口，请添加。</p> : null}
      {overview.data?.items.map(item => {
        const result = results[item.id];
        return <Card key={item.id} className="glass-card"><CardHeader><CardTitle className="flex flex-wrap items-center gap-2 text-base">{item.name}<Badge variant="outline">{item.enabled ? "已启用" : "已停用"}</Badge></CardTitle><CardDescription>{item.baseUrl} · {item.credentialSource}</CardDescription></CardHeader>
          <CardContent className="space-y-3"><div className="flex flex-wrap gap-2"><Button size="sm" disabled={!item.enabled || probe.isPending || busy} onClick={() => {
            setResults(previous => { const next = { ...previous }; delete next[item.id]; return next; });
            probe.mutate(item.id, { onSuccess: data => { setResults(p => ({ ...p, [item.id]: data })); setCheckedAt(p => ({ ...p, [item.id]: new Date().toLocaleTimeString() })); }, onError: e => { setResults(p => ({ ...p, [item.id]: getAppErrorMessage(e) })); } });
          }}>{probe.isPending && probe.variables === item.id ? "检测中…" : "检测连接与模型"}</Button><Button size="sm" variant="outline" disabled={busy} onClick={() => setDraft({ ...item })}>编辑</Button><Button size="sm" variant="outline" disabled={busy} onClick={() => save.mutate({ ...item, enabled: !item.enabled }, { onSuccess: () => setResults({}), onError: error })}>{item.enabled ? "停用检测" : "启用检测"}</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => {
            if (window.confirm(`移除入口「${item.name}」？不会删除凭证或停止账号池。`)) remove.mutate(item.id, { onError: error });
          }}>移除</Button></div>
          {typeof result === "string" ? <p role="alert" className="text-sm text-destructive">{result}</p> : result ? <div role="status" className="space-y-2 rounded-lg border p-3 text-sm"><p>目录可达 · {result.latencyMs} ms · {checkedAt[item.id]} · 健康端点：{result.health}</p><div className="flex flex-wrap gap-2">{result.models.map(model => <Badge key={model} variant="secondary">{model}</Badge>)}</div>
            {result.healthError ? <p className="text-destructive">健康检查：{result.healthError}</p> : null}
            {result.healthSummary ? <div className="space-y-2"><p>上游报告可用账号：{result.healthSummary.readyAccounts ?? "未提供"}</p><div className="flex flex-wrap gap-2">{result.healthSummary.accounts?.map(account => <Badge key={account.index} variant="outline">账号 {account.index} · {ACCOUNT_STATUS[account.status] ?? "未知"}{account.cooldownSeconds ? ` · 冷却 ${account.cooldownSeconds}s` : ""}</Badge>)}</div></div> : null}
            <p className="text-xs text-muted-foreground">{result.note}</p></div> : <p className="text-xs text-muted-foreground">尚未检测。Mac 休眠、网页账号离线或 SSH 通道失效都可能导致不可用。</p>}
        </CardContent></Card>;
      })}
    </section>
  </div>;
}
