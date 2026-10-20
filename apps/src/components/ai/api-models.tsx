"use client";

import { useQuery } from "@tanstack/react-query";
import { Boxes, RefreshCw } from "lucide-react";
import { aiConnectionsClient, type AiConnection } from "@/lib/api/ai-connections-client";
import { getAppErrorMessage } from "@/lib/api/transport";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

function ApiModelCard({ connection }: { connection: AiConnection }) {
  const models = useQuery({ queryKey: ["ai-connection-models", connection.id], queryFn: () => aiConnectionsClient.probe(connection.id), enabled: false, retry: false });
  return <article className="glass-card space-y-4 rounded-2xl border border-border/70 p-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="font-medium">{connection.name}</h3><p className="mt-1 text-xs text-muted-foreground">{connection.enabled ? "API 入口" : "已停用"} · 上游未提供额度接口</p></div><Button size="sm" variant="outline" disabled={!connection.enabled || models.isFetching} onClick={() => void models.refetch()}><RefreshCw className={`size-3.5 ${models.isFetching ? "animate-spin" : ""}`} />同步模型</Button></div>
    {models.error ? <p role="alert" className="text-xs text-destructive">{getAppErrorMessage(models.error)}</p> : null}
    <div className="flex flex-wrap gap-2">{models.data?.models.length ? models.data.models.map(model => <Badge key={model} variant="secondary" className="whitespace-normal break-all font-normal">{model}</Badge>) : <p className="text-xs text-muted-foreground">尚无模型目录，点击同步读取上游 /v1/models。</p>}</div>
    {models.dataUpdatedAt ? <p className="text-[11px] text-muted-foreground">目录更新时间：{new Date(models.dataUpdatedAt).toLocaleString()} · 未执行生成验证</p> : null}
  </article>;
}

export function ApiModels() {
  const connections = useQuery({ queryKey: ["ai-connections"], queryFn: aiConnectionsClient.list, retry: false });
  if (!connections.data?.items.length && !connections.error) return null;
  return <section className="space-y-4 border-t border-border/60 pt-6" aria-label="API 模型目录"><h2 className="flex items-center gap-2 text-base font-semibold"><Boxes className="size-4 text-cyan-600" />API 模型目录</h2>{connections.error ? <p role="alert" className="text-sm text-destructive">{getAppErrorMessage(connections.error)}</p> : <div className="grid gap-4 lg:grid-cols-2">{connections.data?.items.map(item => <ApiModelCard connection={item} key={item.id} />)}</div>}</section>;
}
