"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Clipboard, Clock3, FolderOpen, History, RefreshCw, Search, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { aiAccountsClient, type AiProvider } from "@/lib/api/ai-accounts-client";
import { getAppErrorMessage } from "@/lib/api/transport";
import { activeFirst } from "@/lib/account-order";
import { useManagedAiAccounts } from "@/hooks/useManagedAiAccounts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const time = (ms: number) => ms ? new Date(ms).toLocaleString() : "未知时间";
const visibility = { ready: "目录可用", missing_workspace: "目录已不存在", unknown_workspace: "目录未记录" };

async function copy(value: string) {
  try { await navigator.clipboard.writeText(value); toast.success("恢复命令已复制"); }
  catch { toast.error("复制失败，请手动复制命令"); }
}

export function ManagedCliSessions({ provider }: { provider: AiProvider }) {
  const { accounts } = useManagedAiAccounts();
  const [accountId, setAccountId] = useState("");
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(100);
  const [selectedId, setSelectedId] = useState("");
  const items = activeFirst(accounts.data?.items.filter(item => item.provider === provider) ?? [], item => item.active);
  const account = items.find(item => item.id === accountId) ?? items[0];
  const catalog = useQuery({
    queryKey: ["cli-session-catalog", provider, account?.id, query, limit],
    queryFn: () => aiAccountsClient.sessions(account!.id, query, limit),
    enabled: Boolean(account), retry: false, staleTime: 30_000,
  });
  const selected = catalog.data?.items.find(item => item.id === selectedId) ?? catalog.data?.items[0];
  const name = provider === "claude" ? "Claude Code" : "Antigravity";
  const error = accounts.error || catalog.error;
  return <section className="space-y-5 pt-5" aria-label={`${name} 会话`}>
    <div className="glass-card flex flex-wrap items-end justify-between gap-4 rounded-2xl border border-border/60 p-5">
      <label className="grid min-w-0 flex-1 gap-2 text-xs text-muted-foreground sm:max-w-sm">会话所属账号
        <select aria-label={`${name} 会话账号`} className="h-10 w-full min-w-0 rounded-lg border bg-background px-3 text-sm text-foreground" value={account?.id ?? ""} onChange={event => { setAccountId(event.target.value); setSelectedId(""); setLimit(100); }}>
          {!items.length ? <option value="">尚无托管账号</option> : items.map(item => <option key={item.id} value={item.id}>{item.active ? "● 当前默认 · " : ""}{item.label}</option>)}
        </select>
      </label>
      <p className="flex items-center gap-2 text-xs text-muted-foreground"><ShieldCheck className="size-4 text-emerald-600" />恢复命令绑定此账号，保留当前默认账号</p>
      <Button variant="outline" size="sm" disabled={catalog.isFetching || accounts.isFetching} onClick={() => { void accounts.refetch(); if (account) void catalog.refetch(); }}><RefreshCw className={catalog.isFetching ? "animate-spin" : ""} />刷新会话</Button>
    </div>
    {error ? <p role="alert" className="rounded-xl border border-destructive/30 p-4 text-sm text-destructive">{getAppErrorMessage(error)}</p> : null}
    {catalog.data?.coverage.partial ? <p role="alert" className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm">已达到读取边界或部分文件不可读。以下仅为部分会话，不代表完整历史。</p> : null}
    {!accounts.isPending && !account && !accounts.error ? <div className="glass-card rounded-2xl border p-8 text-center text-sm text-muted-foreground">请先在「AI 接入」添加 {name} 账号，会话将在该账号独立配置下读取。</div> : null}
    {account ? <>
      <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
        <div className="glass-card min-w-0 overflow-hidden rounded-2xl border border-border/60">
          <div className="space-y-4 border-b p-5">
            <div className="flex items-center justify-between"><h2 className="font-semibold">本地会话</h2><Badge variant="secondary">{catalog.data?.total ?? "—"} 条{catalog.data?.coverage.partial ? " · 部分" : ""}</Badge></div>
            <form className="flex gap-2" onSubmit={event => { event.preventDefault(); setLimit(100); setQuery(draft.trim()); setSelectedId(""); }}>
              <Input aria-label={`${name} 搜索会话`} maxLength={200} value={draft} onChange={event => setDraft(event.target.value)} placeholder="标题、工作目录或 Session ID" />
              <Button aria-label="搜索会话" type="submit" variant="outline" size="icon"><Search /></Button>
            </form>
          </div>
          <div className="max-h-[600px] overflow-y-auto">
            {catalog.isPending ? <p className="p-6 text-sm text-muted-foreground">正在读取账号会话…</p> : null}
            {catalog.data?.items.map(item => <button type="button" key={item.id} onClick={() => setSelectedId(item.id)} aria-pressed={selected?.id === item.id} className={`flex w-full min-w-0 flex-col gap-2 border-b px-5 py-4 text-left transition-colors hover:bg-muted/60 ${selected?.id === item.id ? "bg-primary/[0.06]" : ""}`}>
              <span className="line-clamp-2 break-all text-sm font-medium">{item.title}</span>
              <span className="w-full truncate text-xs text-muted-foreground">{item.cwd ?? "未记录工作目录"}</span>
              <span className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground"><Clock3 className="size-3" />{time(item.updatedAtMs)}<span>· {visibility[item.visibility]}</span></span>
            </button>)}
            {catalog.data && !catalog.data.items.length ? <div className="space-y-3 p-8 text-center text-sm text-muted-foreground"><History className="mx-auto size-8 opacity-40" /><p>{query ? "没有匹配的会话，请尝试其他关键词。" : "此账号暂无已保存的会话。"}</p><p className="text-xs">请使用此账号的官方 CLI 开始对话，保存后刷新。</p></div> : null}
            {catalog.data && catalog.data.items.length < catalog.data.total ? <div className="p-4"><Button className="w-full" variant="outline" disabled={limit >= 500} onClick={() => setLimit(value => Math.min(500, value + 100))}>{limit >= 500 ? "已显示前 500 条，请搜索缩小范围" : "加载更多"}</Button></div> : null}
          </div>
        </div>
        <div className="glass-card min-w-0 space-y-5 rounded-2xl border border-border/60 p-5">
          {selected ? <>
            <div><Badge variant="outline">{name}</Badge><h2 className="mt-3 break-all text-lg font-semibold">{selected.title}</h2><p className="mt-2 text-xs text-muted-foreground">{time(selected.updatedAtMs)}</p></div>
            <div className="space-y-4 rounded-xl border p-4">
              <div><p className="text-xs text-muted-foreground">Session ID</p><p className="mt-1 break-all font-mono text-xs">{selected.id}</p></div>
              <div><p className="flex items-center gap-1 text-xs text-muted-foreground"><FolderOpen className="size-3.5" />工作目录</p><p className="mt-1 break-all text-sm">{selected.cwd ?? "未记录，恢复时请先进入原项目目录"}</p></div>
              <p className={`text-xs ${selected.cwdExists ? "text-emerald-600" : "text-amber-600"}`}>{visibility[selected.visibility]}</p>
            </div>
            {selected.visibility === "missing_workspace" ? <p className="text-xs text-amber-600">原目录已不存在。请先恢复该目录，或手动进入迁移后的项目目录再执行命令中 CLI 部分。</p> : null}
            <div className="rounded-xl bg-muted/70 p-4"><p className="text-xs text-muted-foreground">在服务所在电脑的终端执行</p><code className="mt-3 block whitespace-pre-wrap break-all text-xs leading-relaxed">{selected.resumeCommand}</code></div>
            <Button onClick={() => void copy(selected.resumeCommand)}><Clipboard className="size-4" />复制恢复命令</Button>
          </> : <div className="flex min-h-48 items-center justify-center text-sm text-muted-foreground">选择会话，查看上下文位置与恢复命令。</div>}
          {catalog.data ? <div className="space-y-3 border-t pt-5"><h3 className="text-sm font-medium">继续此账号最近一次会话</h3><p className="text-xs leading-relaxed text-muted-foreground">先在终端进入原项目目录。由官方 CLI 查找最近会话；没有历史时可能无法继续。</p><code className="block break-all rounded-lg bg-muted/50 p-3 text-xs">{catalog.data.continueCommand}</code><Button size="sm" variant="outline" onClick={() => void copy(catalog.data!.continueCommand)}><Clipboard className="size-3.5" />复制继续命令</Button></div> : null}
        </div>
      </div>
      {catalog.data ? <p className="text-xs leading-relaxed text-muted-foreground">{catalog.data.note} · 最近读取 {time(catalog.data.checkedAt * 1000)}</p> : null}
    </> : null}
  </section>;
}
