"use client";

import { Laptop, Server } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { LabContextLocation } from "@/types/labcontext";

const LOCATION_OPTIONS = [
  {
    value: "server" as const,
    label: "服务器",
    description: "远程计算与共享项目",
    icon: Server,
  },
  {
    value: "local" as const,
    label: "本地电脑",
    description: "当前设备上的项目目录",
    icon: Laptop,
  },
];

export function LocationSwitcher({
  location,
  localEnabled,
  onChange,
  expanded = false,
}: {
  location: LabContextLocation;
  localEnabled: boolean;
  onChange: (location: LabContextLocation) => void;
  expanded?: boolean;
}) {
  if (!expanded) {
    return (
      <div className="flex rounded-xl border bg-muted/35 p-1" role="group" aria-label="工作区位置">
        {LOCATION_OPTIONS.map((option) => {
          const Icon = option.icon;
          const disabled = option.value === "local" && !localEnabled;
          return (
            <Button
              key={option.value}
              size="sm"
              variant={location === option.value ? "secondary" : "ghost"}
              className="h-8"
              disabled={disabled}
              aria-pressed={location === option.value}
              title={disabled ? "本地工作区只能在 AImanager 桌面版中管理" : option.description}
              onClick={() => onChange(option.value)}
            >
              <Icon className="size-3.5" />
              {option.label}
            </Button>
          );
        })}
      </div>
    );
  }

  return (
    <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="工作区位置">
      {LOCATION_OPTIONS.map((option) => {
        const Icon = option.icon;
        const selected = location === option.value;
        const disabled = option.value === "local" && !localEnabled;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            className={cn(
              "flex min-w-0 items-center gap-3 rounded-xl border p-3 text-left outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50",
              selected
                ? "border-primary/55 bg-primary/8"
                : "border-border/70 bg-background/55 hover:border-primary/30 hover:bg-muted/45",
            )}
            onClick={() => onChange(option.value)}
          >
            <span className={cn(
              "flex size-9 shrink-0 items-center justify-center rounded-lg",
              selected ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
            )}>
              <Icon className="size-4" />
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-medium">{option.label}</span>
              <span className="block truncate text-xs text-muted-foreground">
                {disabled ? "需使用桌面版" : option.description}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
