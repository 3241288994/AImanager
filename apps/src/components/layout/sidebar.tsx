"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, BookOpenCheck, Cable, ChevronLeft, ChevronRight, Gauge, History } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/lib/store/useAppStore";
import { useI18n } from "@/lib/i18n/provider";

const ROUTES = [
  { href: "/", label: "账号与额度", icon: Gauge },
  { href: "/connections", label: "AI 接入", icon: Cable },
  { href: "/analytics", label: "用量分析", icon: BarChart3 },
  { href: "/sessions", label: "会话与恢复", icon: History },
  { href: "/labcontext", label: "工作区", icon: BookOpenCheck },
] as const;

export function Sidebar() {
  const pathname = usePathname();
  const { isSidebarOpen, toggleSidebar } = useAppStore();
  const { t } = useI18n();
  return (
    <aside className={cn("glass-sidebar relative z-20 flex w-14 shrink-0 flex-col border-r bg-card transition-[width]", isSidebarOpen ? "md:w-56" : "md:w-16")}>
      <div className={cn("flex h-16 items-center justify-center border-b px-2", isSidebarOpen ? "md:justify-start md:px-4" : "justify-center px-2")}>
        <div className="flex items-center gap-2 overflow-hidden">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-sm font-bold text-primary-foreground">AI</div>
          {isSidebarOpen ? <div className="hidden min-w-0 md:block"><p className="truncate text-sm font-bold">AImanager</p><p className="truncate text-xs text-muted-foreground">CLI · API · Workspace</p></div> : null}
        </div>
      </div>
      <nav className="grid flex-1 content-start gap-1 p-2 pt-4">
        {ROUTES.map((route) => {
          const active = route.href === "/" ? pathname === "/" : pathname.startsWith(route.href);
          return (
            <Link key={route.href} href={route.href} title={t(route.label)} aria-label={t(route.label)} className={cn("flex h-10 items-center justify-center gap-3 rounded-lg px-3 text-sm text-muted-foreground hover:bg-accent hover:text-foreground", isSidebarOpen && "md:justify-start", active && "bg-accent font-medium text-foreground")}>
              <route.icon className="size-4 shrink-0" />{isSidebarOpen ? <span className="hidden md:inline">{t(route.label)}</span> : null}
            </Link>
          );
        })}
      </nav>
      <div className="hidden border-t p-2 md:block">
        <Button variant="ghost" size="sm" className={cn("h-10 w-full gap-3", isSidebarOpen ? "justify-start" : "justify-center")} onClick={toggleSidebar} aria-label={isSidebarOpen ? t("收起侧边栏") : t("展开侧边栏")}>
          {isSidebarOpen ? <><ChevronLeft className="size-4" /><span>{t("收起侧边栏")}</span></> : <ChevronRight className="size-4" />}
        </Button>
      </div>
    </aside>
  );
}
