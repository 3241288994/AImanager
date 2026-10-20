"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { aiAccountsClient, type ManagedAiAccount } from "@/lib/api/ai-accounts-client";
import { invoke, withAddr, getAppErrorMessage } from "@/lib/api/transport";
import type { ManagedModelCatalog } from "@/types/model";

function ModelList({ items, note }: { items: { id: string; name: string }[]; note: string }) {
  return <div className="space-y-3"><div className="flex flex-wrap gap-2">{items.length ? items.map(model => <Badge key={model.id} variant="secondary" className="max-w-full whitespace-normal break-all rounded-md px-2.5 py-1 font-normal" title={model.id}>{model.name}</Badge>) : <span className="text-xs text-muted-foreground">尚无可验证的模型目录</span>}</div><p className="text-xs leading-relaxed text-muted-foreground">{note}</p></div>;
}

export function AccountModels({ account }: { account: ManagedAiAccount }) {
  const client = useQueryClient();
  const refresh = useMutation({ mutationFn: () => aiAccountsClient.models(account.id), onSuccess: () => client.invalidateQueries({ queryKey: ["ai-accounts"] }), onError: e => toast.error(getAppErrorMessage(e)) });
  return <section className="space-y-3 border-t border-border/60 pt-4" aria-label={`${account.label} 模型目录`}>
    <div className="flex flex-wrap items-center justify-between gap-2"><h4 className="flex items-center gap-2 text-sm font-medium"><Boxes className="size-4 text-muted-foreground" />可用模型</h4><Button size="sm" variant="ghost" disabled={refresh.isPending || account.authStatus !== "authenticated"} onClick={() => refresh.mutate()}><RefreshCw className={`size-3.5 ${refresh.isPending ? "animate-spin" : ""}`} />同步模型</Button></div>
    <ModelList items={account.models?.items ?? []} note={account.models?.note ?? "点击同步，读取此账号的官方 CLI 模型信息。"} />
    {account.models?.lastError ? <p role="status" className="text-xs text-amber-700 dark:text-amber-300">刷新失败，保留上次目录：{account.models.lastError}</p> : null}
    {account.models?.checkedAt ? <p className="text-[11px] text-muted-foreground">{account.models.source === "official_cli_cache" ? "读取缓存" : "目录更新"}：{new Date(account.models.checkedAt * 1000).toLocaleString()}</p> : null}
  </section>;
}

export function CodexModels() {
  const models = useQuery({ queryKey: ["personal", "models"], queryFn: () => invoke<ManagedModelCatalog>("service_model_catalog_list", withAddr({ refreshRemote: false })), staleTime: 60_000, retry: false });
  const client = useQueryClient();
  const refresh = useMutation({ mutationFn: () => invoke<ManagedModelCatalog>("service_model_catalog_list", withAddr({ refreshRemote: true }), { timeoutMs: 30_000 }), onSuccess: data => client.setQueryData(["personal", "models"], data), onError: e => toast.error(getAppErrorMessage(e)) });
  const items = (models.data?.items ?? []).filter(m => m.sourceKind === "remote" && m.visibility !== "hide");
  return <section className="glass-card space-y-4 rounded-2xl border border-border/70 p-5" aria-label="Codex 模型目录">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="flex items-center gap-2 font-medium"><Boxes className="size-4 text-emerald-600" />Codex 模型目录</h3><Button size="sm" variant="outline" disabled={refresh.isPending} onClick={() => refresh.mutate()}><RefreshCw className={`size-3.5 ${refresh.isPending ? "animate-spin" : ""}`} />同步模型</Button></div>
    {models.isPending ? <p role="status" className="text-sm text-muted-foreground">正在读取模型目录…</p> : <ModelList items={items.map(m => ({ id: m.slug, name: m.displayName || m.slug }))} note="来自服务保存的官方目录，可能使用缓存；并非逐账号授权验证，实际可用性取决于订阅和额度。" />}
    {models.error ? <p role="alert" className="text-xs text-destructive">{getAppErrorMessage(models.error)}</p> : null}
  </section>;
}
