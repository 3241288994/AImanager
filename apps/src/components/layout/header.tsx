"use client";

import { usePathname } from "next/navigation";
import { LogOut } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { LanguageSwitcher } from "@/components/layout/language-switcher";
import { useAppStore } from "@/lib/store/useAppStore";
import { useRuntimeCapabilities } from "@/hooks/useRuntimeCapabilities";
import { useI18n } from "@/lib/i18n/provider";

export function Header() {
  const pathname = usePathname();
  const { appSettings, serviceStatus } = useAppStore();
  const { t } = useI18n();
  const { mode } = useRuntimeCapabilities();
  const title = pathname.startsWith("/connections")
    ? "AI 接入"
    : pathname.startsWith("/analytics")
    ? "用量分析"
    : pathname.startsWith("/labcontext")
      ? "工作区"
      : pathname.startsWith("/sessions")
        ? "会话与恢复"
        : "账号与额度";
  const canLogout = mode === "web-gateway" && appSettings.webAuthMode !== "none";

  return (
    <header className="glass-header sticky top-0 z-30 flex h-16 items-center gap-3 border-b px-4 xl:px-6">
      <h1 className="min-w-0 truncate text-sm font-semibold sm:text-lg">{t(title)}</h1>
      <Badge variant={serviceStatus.connected ? "default" : "secondary"} className="h-5">
        {serviceStatus.connected ? t("服务已连接") : t("服务未连接")}
      </Badge>
      {serviceStatus.version ? <span className="text-xs text-muted-foreground">v{serviceStatus.version}</span> : null}
      <div className="ml-auto flex shrink-0 items-center gap-2">
        <LanguageSwitcher compact triggerClassName="w-[104px] sm:w-[124px]" />
        {canLogout ? (
          <Button variant="ghost" size="sm" className="gap-2 text-muted-foreground hover:text-destructive" onClick={() => window.location.assign("/__logout")} aria-label={t("退出登录")}>
            <LogOut className="size-3.5" /><span className="hidden sm:inline">{t("退出登录")}</span>
          </Button>
        ) : null}
      </div>
    </header>
  );
}
