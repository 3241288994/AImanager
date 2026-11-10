"use client";
import { Laptop, Server, CheckCircle2, Clock3, AlertTriangle, ExternalLink } from "lucide-react";
import { useI18n } from "@/lib/i18n/provider";
import { Button } from "@/components/ui/button";
import type { Account } from "@/types/account";
import type { CodexDevice } from "@/types/codex-profile";
import type { CodexAccountSwitch } from "@/types/codex-profile";

export function deviceOnline(device:CodexDevice) { return Date.now()/1000-device.lastSeenAt<90; }
export function devicePending(device:CodexDevice) { return Boolean(device.task && ["pending","authorizing","needs_login"].includes(device.task.state)); }
export function deviceFeedback(device:CodexDevice):string {
  if (!deviceOnline(device)) return "Mac 离线，恢复连接后继续处理";
  const task=device.task;
  if (!task) return device.currentAccountId ? "已连接 · 等待切换指令" : "已连接 · 尚未识别本机登录";
  if (task.state==="needs_login") return "该账号首次在 Mac 使用，需要独立授权一次";
  if (task.state==="authorizing") return "请在官方页面完成这台 Mac 的设备码授权";
  if (task.state==="pending") return task.reason==="background_unverified" ? "凭据已更新，正在等待后台确认身份；任务空闲后会自动重试，无需重复登录。" : task.reason==="sessions_loaded" ? "等待本机任务结束，空闲会话无需退出" : task.reason==="background_unreachable" ? "暂时无法核实本机后台，尚未切换" : "等待 Mac 处理同步请求";
  if (task.state==="attention") return "本机凭据已更新，后台身份尚未确认";
  if (task.state==="failed") return task.reason==="identity_mismatch" ? "授权账号与目标不一致，未切换" : task.reason==="profile_changed" ? "本机身份已在其他入口改变，未覆盖" : "本机处理未完成，请检查网络与授权后重试";
  if (task.state==="cancelled") return "已取消尚未完成的步骤，不回退已完成的切换";
  return task.kind==="login" && !task.parentRequestId ? "本机授权已保存，默认账号未改变" : "本机同步已完成";
}

export function CodexDeviceStatus({devices,accounts,serverAccount,serverSwitch,onAuthorize,busy}:{devices:CodexDevice[];accounts:Account[];serverAccount:string|null;serverSwitch?:CodexAccountSwitch|null;onAuthorize:(deviceId:string,accountId:string)=>void;busy:boolean}) {
  const {t}=useI18n();
  const serverPending=serverSwitch?.state==="pending";
  const serverAttention=["failed","attention"].includes(serverSwitch?.state||"");
  const name=(id:string|null)=>accounts.find(a=>a.id===id)?.name || t("未识别账号");
  return <section aria-label={t("双端 Codex 状态")} className="grid gap-3 lg:grid-cols-2">
    <div className="glass-card flex items-start gap-3 rounded-2xl border border-border/60 p-4">
      <div className="rounded-xl bg-primary/10 p-2.5 text-primary"><Server className="size-4"/></div>
      <div className="min-w-0 flex-1"><p className="text-xs font-medium text-muted-foreground">{t("服务器 Codex")}</p><p className="mt-1 truncate text-sm font-semibold">{name(serverAccount)}</p><p className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">{serverPending ? <Clock3 className="size-3"/> : serverAttention || !serverAccount ? <AlertTriangle className="size-3 text-amber-500"/> : <CheckCircle2 className="size-3 text-emerald-600"/>}{serverPending ? t(serverSwitch?.reason==="background_unverified" ? "凭据已更新，正在等待后台确认身份；任务空闲后会自动重试，无需重复登录。" : "服务器切换已排队，保留现有任务") : serverAttention ? t("服务器切换未完成，请查看下方提示") : serverAccount ? t("服务器当前默认身份") : t("尚未识别服务器默认身份")}</p></div>
    </div>
    {devices.length ? devices.map(device=><div key={device.id} data-testid="codex-device-status" className="glass-card rounded-2xl border border-border/60 p-4">
      <div className="flex items-start gap-3"><div className="rounded-xl bg-sky-500/10 p-2.5 text-sky-600"><Laptop className="size-4"/></div><div className="min-w-0 flex-1"><p className="text-xs font-medium text-muted-foreground">{t("本机 Mac Codex")}{!deviceOnline(device) ? ` · ${t("上次身份")}` : ""}</p><p className="mt-1 truncate text-sm font-semibold">{name(device.currentAccountId)}</p><p className="mt-1 text-xs text-muted-foreground">{t(deviceFeedback(device))}</p></div>{devicePending(device) ? <Clock3 className="mt-1 size-4 text-amber-500"/> : !deviceOnline(device)||["failed","attention"].includes(device.task?.state||"") ? <AlertTriangle className="mt-1 size-4 text-amber-500"/> : <CheckCircle2 className="mt-1 size-4 text-emerald-600"/>}</div>
      {device.task && (devicePending(device) || device.task.state==="failed") ? <div className="mt-3 border-t border-border/50 pt-3 text-xs"><p className="truncate text-muted-foreground">{t("目标账号")}：{name(device.task.accountId)}</p>
        {["needs_login","failed"].includes(device.task.state) ? <Button size="sm" variant="outline" className="mt-2" disabled={busy||!deviceOnline(device)} onClick={()=>onAuthorize(device.id,device.task!.accountId)}>{device.task.state==="failed" ? t("重新授权此 Mac") : t("授权 Mac 后继续同步")}</Button> : null}
        {device.task.state==="authorizing" && device.task.userCode && device.task.verificationUrl==="https://auth.openai.com/codex/device" ? <div className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-xl bg-muted/50 p-3"><code className="font-mono text-lg font-semibold tracking-widest">{device.task.userCode}</code><Button size="sm" variant="outline" onClick={()=>window.open(device.task!.verificationUrl!,"_blank","noopener,noreferrer")}><ExternalLink className="size-3"/>{t("打开官方设备码页面")}</Button></div> : null}
      </div> : null}
    </div>) : <div className="glass-card flex gap-3 rounded-2xl border border-dashed border-border/60 p-4"><Laptop className="mt-1 size-4 text-muted-foreground"/><div><p className="text-sm font-medium">{t("Mac 同步组件尚未接入")}</p><p className="mt-1 text-xs text-muted-foreground">{t("未连接的设备不会被误报为已切换")}</p></div></div>}
  </section>;
}
