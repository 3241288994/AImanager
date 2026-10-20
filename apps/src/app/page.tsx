"use client";

import Link from "next/link";
import { ArrowUpRight, Gauge } from "lucide-react";
import { ApiModels } from "@/components/ai/api-models";
import { AiPlatforms } from "@/components/ai/ai-platforms";
import { Button } from "@/components/ui/button";

export default function AccountsAndUsagePage() {
  return <main className="mx-auto w-full max-w-6xl space-y-7 px-4 py-6 md:px-8">
    <header className="glass-card flex flex-wrap items-center justify-between gap-5 rounded-2xl border border-border/60 p-6">
      <div className="flex items-start gap-4"><div className="rounded-2xl bg-emerald-500/10 p-3 text-emerald-700 dark:text-emerald-300"><Gauge className="size-6" /></div><div><p className="mb-1 text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">Usage & models</p><h1 className="text-2xl font-semibold tracking-tight">账号与额度</h1><p className="mt-2 text-sm text-muted-foreground">查看各账号剩余额度、重置时间与模型目录。</p></div></div>
      <Button variant="outline" size="sm" render={<Link href="/connections/" />}>管理 AI 接入<ArrowUpRight className="size-4" /></Button>
    </header>
    <AiPlatforms view="usage" />
    <ApiModels />
    <p className="text-xs leading-relaxed text-muted-foreground">额度按平台和时间窗口分别展示，不跨平台累加。模型目录不等于调用保证；官方未提供的数据保持未知。</p>
  </main>;
}
