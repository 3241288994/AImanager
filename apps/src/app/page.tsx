"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Terminal, RefreshCw, ShieldCheck, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { accountClient } from "@/lib/api/account-client";
import { getAppErrorMessage } from "@/lib/api/transport";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CodexAccountsPanel } from "@/components/ai/codex-accounts-panel";
import { AI_PLATFORMS, ManagedCliAccounts } from "@/components/ai/managed-cli-accounts";
import { useManagedAiAccounts } from "@/hooks/useManagedAiAccounts";

export default function AccountsAndUsagePage() {
  const [platform, setPlatform] = useState("codex");
  const client = useQueryClient();
  const { accounts, synchronize } = useManagedAiAccounts();
  const codex = useQuery({ queryKey: ["personal", "accounts"], queryFn: accountClient.list, refetchInterval: 60_000, refetchIntervalInBackground: false });
  useEffect(() => {
    const selectHash = () => { const value = window.location.hash.slice(1); if (["codex", "claude", "antigravity"].includes(value)) setPlatform(value); };
    selectHash(); window.addEventListener("hashchange", selectHash);
    return () => window.removeEventListener("hashchange", selectHash);
  }, []);
  const refresh = useMutation({
    mutationFn: async () => { await synchronize(); await client.invalidateQueries({ queryKey: ["personal"] }); },
    onSuccess: () => toast.success("各平台登录状态已同步"),
    onError: error => toast.error(getAppErrorMessage(error)),
  });
  const platforms = [
    { id: "codex", name: "Codex", icon: Terminal, tint: "bg-primary/10 text-primary", count: codex.data?.items.length, connected: codex.data?.items.filter(item => item.hasToken && item.status === "active").length },
    ...(["claude", "antigravity"] as const).map(id => ({ id, ...AI_PLATFORMS[id], count: accounts.data?.items.filter(item => item.provider === id).length, connected: accounts.data?.items.filter(item => item.provider === id && item.authStatus === "authenticated").length })),
  ];
  return <main className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6 md:px-8">
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="text-2xl font-semibold tracking-tight">账号与额度</h1><p className="mt-2 text-sm text-muted-foreground">你的 AI 账号，一处查看。登录状态与官方额度分开确认。</p></div>
      <Button variant="outline" size="sm" disabled={refresh.isPending} onClick={() => refresh.mutate()}><RefreshCw className={`size-3.5 ${refresh.isPending ? "animate-spin" : ""}`} />同步登录状态</Button>
    </header>
    <Tabs value={platform} onValueChange={value => setPlatform(String(value))} className="gap-6">
      <TabsList className="grid w-full grid-cols-1 gap-3 bg-transparent p-0 sm:grid-cols-3" aria-label="AI 平台">
        {platforms.map(meta => {
          const Icon = meta.icon;
          return <TabsTrigger value={meta.id} key={meta.id} style={platform === meta.id ? { borderColor: "var(--primary)" } : undefined} className="glass-card h-auto justify-start rounded-2xl border border-border/70 p-4 text-left data-active:shadow-none">
            <div className={`flex size-10 shrink-0 items-center justify-center rounded-xl ${meta.tint}`}><Icon className="size-5" /></div>
            <div className="ml-2 min-w-0 flex-1"><p className="text-sm font-semibold text-foreground">{meta.name}</p><p className="mt-1 text-xs font-normal text-muted-foreground">{meta.count == null ? "正在同步…" : `${meta.count} 个账号`}</p></div>
            <span className={`flex items-center gap-1 text-xs ${meta.connected ? "text-emerald-700 dark:text-emerald-300" : "text-muted-foreground"}`}>{meta.connected ? <><CheckCircle2 className="size-3.5" />已连接</> : "待连接"}</span>
          </TabsTrigger>;
        })}
      </TabsList>
      <TabsContent value="codex"><CodexAccountsPanel /></TabsContent>
      <TabsContent value="claude"><ManagedCliAccounts provider="claude" /></TabsContent>
      <TabsContent value="antigravity"><ManagedCliAccounts provider="antigravity" /></TabsContent>
    </Tabs>
    <p className="flex items-start gap-2 text-xs leading-relaxed text-muted-foreground"><ShieldCheck className="mt-0.5 size-3.5 shrink-0" />凭证仅保留在服务主机。不同平台与时间窗口的额度不会相加；未提供的 Token、费用和余额保持未知。</p>
  </main>;
}
