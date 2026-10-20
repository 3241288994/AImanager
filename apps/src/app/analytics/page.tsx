"use client";

import { useState } from "react";
import { ChartNoAxesCombined, Terminal, Sparkles, Orbit } from "lucide-react";
import { CodexAnalytics } from "@/components/analytics/codex-analytics";
import { ManagedCliAnalytics } from "@/components/analytics/managed-cli-analytics";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const platforms = [
  { id: "codex", name: "Codex", description: "Credits · Tokens · 交互", icon: Terminal, color: "text-emerald-600 bg-emerald-500/10" },
  { id: "claude", name: "Claude Code", description: "本机 Tokens · 额度趋势", icon: Sparkles, color: "text-amber-600 bg-amber-500/10" },
  { id: "antigravity", name: "Antigravity", description: "官方额度 · 历史快照", icon: Orbit, color: "text-sky-600 bg-sky-500/10" },
];

export default function AnalyticsPage() {
  const [platform, setPlatform] = useState("codex");
  return <main className="mx-auto max-w-[1600px] space-y-6 p-4 sm:p-6 xl:p-8">
    <header className="glass-card flex items-center gap-4 rounded-2xl border border-border/60 p-6">
      <span className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-emerald-500/10 text-emerald-600"><ChartNoAxesCombined className="size-6" /></span>
      <div><p className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">CLI insights</p><h1 className="mt-1 text-2xl font-semibold tracking-tight">用量分析</h1><p className="mt-2 text-sm text-muted-foreground">按 CLI 查看使用趋势，各平台独立统计。网页账号池额度请在「账号与额度」查看。</p></div>
    </header>
    <Tabs value={platform} onValueChange={value => setPlatform(String(value))}>
      <TabsList className="grid h-auto w-full grid-cols-1 gap-3 bg-transparent p-0 sm:grid-cols-3" aria-label="CLI 用量平台">
        {platforms.map(item => <TabsTrigger key={item.id} value={item.id} style={platform === item.id ? { borderColor: "var(--primary)" } : undefined} className="glass-card h-auto justify-start rounded-2xl border border-border/60 p-4 data-active:border-primary/50 data-active:ring-1 data-active:ring-primary/15">
          <span className={`flex size-10 shrink-0 items-center justify-center rounded-xl ${item.color}`}><item.icon className="size-5" /></span>
          <span className="ml-2 text-left"><span className="block font-semibold">{item.name}</span><span className="mt-1 block text-xs font-normal text-muted-foreground">{item.description}</span></span>
        </TabsTrigger>)}
      </TabsList>
      <TabsContent value="codex">{platform === "codex" ? <CodexAnalytics /> : null}</TabsContent>
      <TabsContent value="claude">{platform === "claude" ? <ManagedCliAnalytics key="claude" provider="claude" /> : null}</TabsContent>
      <TabsContent value="antigravity">{platform === "antigravity" ? <ManagedCliAnalytics key="antigravity" provider="antigravity" /> : null}</TabsContent>
    </Tabs>
  </main>;
}
