"use client";

import { useState } from "react";
import { CheckCircle2, ExternalLink, Loader2, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { aiAccountsClient, officialAuthUrl } from "@/lib/api/ai-accounts-client";
import { getAppErrorMessage } from "@/lib/api/transport";
import type { useManagedCliSession } from "@/hooks/useManagedAiAccounts";

const PHASES: Record<string, string> = { starting: "正在连接官方客户端", awaiting_browser: "请在官方页面授权", awaiting_code: "提交官方授权返回码", needs_confirmation: "继续官方客户端设置", verifying: "正在确认登录", reading_usage: "正在同步官方额度", succeeded: "已完成同步", failed: "本次操作未完成", cancelled: "本次操作已取消", expired: "授权已过期" };
const DESCRIPTIONS: Record<string, string> = {
  starting: "在服务主机的独立配置中启动，不影响正在运行的任务。",
  awaiting_browser: "完成官方授权后回到这里，登录状态会自动更新。请勿分享临时链接。",
  awaiting_code: "在官方页面完成登录，将返回码粘贴到下方。这里不需要账号密码。",
  needs_confirmation: "官方客户端等待确认。继续将选择当前默认选项，不会发送模型问题。",
  verifying: "返回码已交给官方客户端，正在同步登录结果。",
  reading_usage: "只读取官方额度接口或 /usage 面板，不提交生成请求。",
  succeeded: "操作结果已同步，账号与额度页面会自动更新。",
  cancelled: "已停止本次会话，保留已保存的账号授权。",
  expired: "本次授权窗口已过期，请重新点击网页登录。",
};

export function CliAuthorizationDialog({ auth }: { auth: ReturnType<typeof useManagedCliSession> }) {
  return <SessionDialog key={`${auth.id}:${auth.session.data?.phase}`} auth={auth} />;
}

function SessionDialog({ auth }: { auth: ReturnType<typeof useManagedCliSession> }) {
  const [code, setCode] = useState("");
  const value = auth.session.data;
  const phase = value?.phase ?? "starting";
  const link = officialAuthUrl(value?.authorizationUrl ?? null);
  return <Dialog open={Boolean(auth.id)} onOpenChange={open => { if (!open) auth.close(); }}>
    <DialogContent className="sm:max-w-lg">
      <DialogHeader>
        <div className="mb-2 flex size-11 items-center justify-center rounded-2xl bg-primary/10 text-primary">{phase === "succeeded" ? <CheckCircle2 className="size-5" /> : auth.live ? <Loader2 className="size-5 animate-spin" /> : <ShieldCheck className="size-5" />}</div>
        <DialogTitle>{PHASES[phase] ?? "官方账号连接"}</DialogTitle>
        <DialogDescription>{auth.session.error ? getAppErrorMessage(auth.session.error) : DESCRIPTIONS[phase] ?? value?.message ?? "正在读取会话状态。"}</DialogDescription>
      </DialogHeader>
      <div className="space-y-4 pt-2">
        {link && auth.live ? <Button className="w-full" render={<a href={link} target="_blank" rel="noreferrer noopener" />}><ExternalLink className="size-4" />打开官方授权页面</Button> : null}
        {phase === "awaiting_code" && auth.id ? <form className="space-y-3" onSubmit={event => {
          event.preventDefault(); const submitted = code; setCode("");
          void auth.run(async () => { await aiAccountsClient.sendCode(auth.id!, submitted); await auth.session.refetch(); });
        }}>
          <Input required aria-label="官方授权返回码" maxLength={2048} type="password" autoComplete="off" placeholder="粘贴官方返回码，不是密码" value={code} onChange={event => setCode(event.target.value)} />
          <Button type="submit" className="w-full" disabled={auth.busy || !code}>提交返回码</Button>
        </form> : null}
        {phase === "needs_confirmation" ? <Button className="w-full" disabled={auth.busy} onClick={() => void auth.run(async () => { await aiAccountsClient.confirm(auth.id!); await auth.session.refetch(); })}>继续官方 CLI 确认</Button> : null}
        <div className="flex items-center justify-between gap-3 border-t pt-4">
          <span className="text-xs text-muted-foreground">凭证仅保留在服务主机</span>
          {auth.live ? <Button size="sm" variant="ghost" disabled={auth.busy} onClick={() => void auth.run(async () => { await aiAccountsClient.cancel(auth.id!); await auth.session.refetch(); })}>取消本次会话</Button> : <Button size="sm" variant="outline" onClick={auth.close}>关闭结果</Button>}
        </div>
      </div>
    </DialogContent>
  </Dialog>;
}
