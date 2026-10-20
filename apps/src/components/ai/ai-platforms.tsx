"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Terminal, CheckCircle2 } from "lucide-react";
import { accountClient } from "@/lib/api/account-client";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CodexAccountsPanel } from "@/components/ai/codex-accounts-panel";
import { AI_PLATFORMS, ManagedCliAccounts } from "@/components/ai/managed-cli-accounts";
import { useManagedAiAccounts } from "@/hooks/useManagedAiAccounts";

export function AiPlatforms({ view }: { view: "connections" | "usage" }) {
  const [platform, setPlatform] = useState("codex");
  const { accounts } = useManagedAiAccounts();
  const codex = useQuery({ queryKey: ["personal", "accounts"], queryFn: accountClient.list, refetchInterval: 60_000, refetchIntervalInBackground: false });
  useEffect(() => {
    const selectHash = () => { const value = window.location.hash.slice(1); if (["codex", "claude", "antigravity"].includes(value)) setPlatform(value); };
    selectHash(); window.addEventListener("hashchange", selectHash);
    return () => window.removeEventListener("hashchange", selectHash);
  }, []);
  const platforms = [
    { id: "codex", name: "Codex", icon: Terminal, tint: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300", count: codex.data?.items.length, connected: codex.data?.items.filter(item => item.hasToken && item.status === "active").length },
    ...(["claude", "antigravity"] as const).map(id => ({ id, ...AI_PLATFORMS[id], count: accounts.data?.items.filter(item => item.provider === id).length, connected: accounts.data?.items.filter(item => item.provider === id && item.authStatus === "authenticated").length })),
  ];
  return <section className="space-y-6">
    <Tabs value={platform} onValueChange={value => setPlatform(String(value))} className="gap-6">
      <TabsList className="grid w-full grid-cols-1 gap-3 bg-transparent p-0 sm:grid-cols-3" aria-label="AI 平台">
        {platforms.map(meta => {
          const Icon = meta.icon;
          return <TabsTrigger value={meta.id} key={meta.id} style={platform === meta.id ? { borderColor: "var(--primary)" } : undefined} className="glass-card h-auto justify-start rounded-2xl border border-border/70 p-4 text-left data-active:shadow-sm hover:-translate-y-0.5 transition-all">
            <div className={`flex size-10 shrink-0 items-center justify-center rounded-xl ${meta.tint}`}><Icon className="size-5" /></div>
            <div className="ml-2 min-w-0 flex-1"><p className="text-sm font-semibold text-foreground">{meta.name}</p><p className="mt-1 text-xs font-normal text-muted-foreground">{meta.count == null ? "正在同步…" : `${meta.count} 个账号`}</p></div>
            <span className={`flex items-center gap-1 text-xs ${meta.connected ? "text-emerald-700 dark:text-emerald-300" : "text-muted-foreground"}`}>{meta.connected ? <><CheckCircle2 className="size-3.5" />已连接</> : "待连接"}</span>
          </TabsTrigger>;
        })}
      </TabsList>
      <TabsContent value="codex"><CodexAccountsPanel view={view} /></TabsContent>
      <TabsContent value="claude"><ManagedCliAccounts provider="claude" view={view} /></TabsContent>
      <TabsContent value="antigravity"><ManagedCliAccounts provider="antigravity" view={view} /></TabsContent>
    </Tabs>
  </section>;
}
