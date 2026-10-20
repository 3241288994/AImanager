"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Clipboard, Database, FolderOpen, RefreshCw, Search } from "lucide-react";
import { toast } from "sonner";
import { sessionCatalogClient, type SessionCatalogItem } from "@/lib/api/session-catalog-client";
import { getAppErrorMessage } from "@/lib/api/transport";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

const VISIBILITY_LABELS: Record<SessionCatalogItem["visibility"], string> = {
  ready: "可恢复",
  missing_rollout: "正文缺失",
  provider_mismatch: "Provider 不匹配",
  missing_workspace: "工作区不存在",
};

function formatTime(value: number): string {
  if (!value) return "未知时间";
  return new Date(value).toLocaleString();
}

export function CodexSessions() {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(100);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const catalogQuery = useQuery({
    queryKey: ["session-catalog", query, limit],
    queryFn: () => sessionCatalogClient.list({ query, limit }),
  });
  const selected = useMemo(
    () => catalogQuery.data?.items.find((item) => item.id === selectedId) || catalogQuery.data?.items[0] || null,
    [catalogQuery.data, selectedId],
  );
  const repairMutation = useMutation({
    mutationFn: (sessionId: string) => sessionCatalogClient.repairProviderIndex(sessionId, catalogQuery.data?.codexHome),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["session-catalog"] });
      toast.success(`索引已修复，备份位于 ${result.backupPath}`);
    },
    onError: (error) => toast.error(`修复失败：${getAppErrorMessage(error)}`),
  });

  const copy = async (text: string, label: string) => {
    try { await navigator.clipboard.writeText(text); toast.success(`${label}已复制`); }
    catch { toast.error("复制失败，请手动复制命令"); }
  };

  return (
    <section className="flex flex-col gap-5 pt-5" aria-label="Codex 会话">
      <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-sm text-muted-foreground">从 Codex 本地索引读取会话，不扫描完整会话正文。</p><Button variant="outline" size="sm" disabled={catalogQuery.isFetching} onClick={() => void catalogQuery.refetch()}><RefreshCw className={catalogQuery.isFetching ? "animate-spin" : ""} />刷新会话</Button></div>
      {catalogQuery.error ? <p role="alert" className="rounded-xl border border-destructive/30 p-4 text-sm text-destructive">{getAppErrorMessage(catalogQuery.error)}</p> : null}

      {catalogQuery.data ? (
        <div className="grid gap-3 sm:grid-cols-3">
          <Card className="glass-card min-w-0"><CardContent className="p-4"><p className="text-xs text-muted-foreground">索引会话</p><p className="mt-1 text-2xl font-semibold">{catalogQuery.data.total}</p></CardContent></Card>
          <Card className="glass-card min-w-0"><CardContent className="p-4"><p className="text-xs text-muted-foreground">Provider 不匹配（已检查 {catalogQuery.data.diagnostics.checkedCount}）</p><p className="mt-1 text-2xl font-semibold">{catalogQuery.data.diagnostics.providerMismatchCount}</p></CardContent></Card>
          <Card className="glass-card min-w-0"><CardContent className="p-4"><p className="text-xs text-muted-foreground">文件/目录异常（已检查 {catalogQuery.data.diagnostics.checkedCount}）</p><p className="mt-1 text-2xl font-semibold">{catalogQuery.data.diagnostics.missingRolloutCount + catalogQuery.data.diagnostics.missingCwdCount}</p></CardContent></Card>
        </div>
      ) : null}

      <div className="grid min-h-[560px] gap-4 lg:grid-cols-[minmax(320px,0.82fr)_minmax(0,1.18fr)]">
        <Card className="glass-card min-w-0 overflow-hidden">
          <CardHeader className="border-b">
            <CardTitle className="text-base">本地会话</CardTitle>
            <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); setLimit(100); setQuery(draft.trim()); }}>
              <Input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="搜索标题、目录或 Session ID" />
              <Button type="submit" variant="outline" size="icon"><Search /></Button>
            </form>
          </CardHeader>
          <CardContent className="max-h-[620px] overflow-y-auto p-0">
            {catalogQuery.isLoading ? <p className="p-5 text-sm text-muted-foreground">正在读取本地索引…</p> : null}
            {catalogQuery.data?.items.map((item) => (
              <button key={item.id} type="button" onClick={() => setSelectedId(item.id)} className={`flex w-full flex-col gap-2 border-b px-4 py-3 text-left transition-colors hover:bg-muted/60 ${selected?.id === item.id ? "bg-primary/[0.06]" : ""}`}>
                <div className="flex w-full items-start justify-between gap-2"><span className="line-clamp-2 text-sm font-medium">{item.title}</span><Badge variant={item.visibility === "ready" ? "secondary" : "outline"}>{VISIBILITY_LABELS[item.visibility]}</Badge></div>
                <span className="max-w-full truncate text-xs text-muted-foreground">{item.cwd || "未知工作区"}</span>
                <span className="text-[11px] text-muted-foreground">{formatTime(item.updatedAtMs)}</span>
              </button>
            ))}
            {catalogQuery.data && catalogQuery.data.items.length === 0 ? <p className="p-5 text-sm text-muted-foreground">没有匹配的本地会话。</p> : null}
            {catalogQuery.data && catalogQuery.data.items.length < catalogQuery.data.total ? (
              <div className="p-4"><Button variant="outline" className="w-full" disabled={limit >= 500} onClick={() => setLimit((value) => Math.min(500, value + 100))}>加载更多（已显示 {catalogQuery.data.items.length}/{catalogQuery.data.total}）</Button></div>
            ) : null}
          </CardContent>
        </Card>

        <Card className="glass-card min-w-0">
          {selected ? (
            <>
              <CardHeader className="border-b"><div className="flex items-start justify-between gap-3"><div><CardTitle className="leading-snug">{selected.title}</CardTitle><CardDescription className="mt-2">{formatTime(selected.updatedAtMs)}</CardDescription></div>{selected.visibility === "ready" ? <CheckCircle2 className="size-5 text-emerald-500" /> : <AlertTriangle className="size-5 text-amber-500" />}</div></CardHeader>
              <CardContent className="grid gap-5 p-5">
                <div className="grid gap-3 text-sm">
                  <div className="rounded-lg border p-3"><p className="text-xs text-muted-foreground">Session ID</p><p className="mt-1 break-all font-mono text-xs">{selected.id}</p></div>
                  <div className="rounded-lg border p-3"><p className="flex items-center gap-1 text-xs text-muted-foreground"><FolderOpen className="size-3.5" />工作目录</p><p className="mt-1 break-all">{selected.cwd || "未知"}</p></div>
                  <div className="rounded-lg border p-3"><p className="flex items-center gap-1 text-xs text-muted-foreground"><Database className="size-3.5" />索引状态</p><p className="mt-1">{VISIBILITY_LABELS[selected.visibility]} · provider={selected.modelProvider || "未知"}</p><p className="mt-1 text-xs text-muted-foreground">rollout：{selected.rolloutExists ? "存在" : "缺失"}；工作区：{selected.cwdExists ? "存在" : "缺失或未知"}</p></div>
                </div>
                <div className="rounded-lg bg-muted p-4"><p className="text-xs text-muted-foreground">恢复命令</p><code className="mt-2 block break-all text-xs">{selected.resumeCommand}</code></div>
                <div className="flex flex-wrap gap-2"><Button onClick={() => copy(selected.resumeCommand, "恢复命令")}><Clipboard />复制恢复命令</Button>{selected.cwd ? <Button variant="outline" onClick={() => copy(selected.cwd || "", "工作目录")}><FolderOpen />复制工作目录</Button> : null}</div>
                {selected.visibility === "provider_mismatch" ? (
                  <div className="space-y-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm">
                    <p>该旧会话的 SQLite provider 索引与官方账号模式不一致。修复只更新当前这一行，先生成完整 SQLite 备份和 JSON 审计记录，不改写 rollout 正文。</p>
                    <Button
                      variant="outline"
                      disabled={repairMutation.isPending}
                      onClick={() => {
                        if (window.confirm(`确认修复会话 ${selected.id} 的 provider 索引？操作前会创建备份。`)) repairMutation.mutate(selected.id);
                      }}
                    >
                      <RefreshCw className={repairMutation.isPending ? "animate-spin" : ""} />修复该会话索引
                    </Button>
                  </div>
                ) : null}
              </CardContent>
            </>
          ) : <CardContent className="p-8 text-center text-sm text-muted-foreground">选择一个会话查看恢复信息。</CardContent>}
        </Card>
      </div>
    </section>
  );
}
