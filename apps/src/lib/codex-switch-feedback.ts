import type { CodexAccountSwitch } from "@/types/codex-profile";

/** Stable translation keys; never present a queued target as the current account. */
export function codexSwitchMessage(status?: CodexAccountSwitch | null): string | null {
  if (!status || status.state === "completed") return null;
  if (status.state === "attention") return "凭据已更新，但后台身份尚未核实。结束会话后点击重试，不要重复登录。";
  if (status.state === "failed") {
    if (status.reason === "expired") return "待切换已超过 24 小时，已停止自动尝试。需要时点击重试。";
    if (status.reason === "profile_changed") return "默认身份或配置已在其他入口改变，已停止本次切换以免覆盖。请核对后重试。";
    return "未完成切换。请检查目标账号授权、服务器网络和配置写入权限，再点击重试。";
  }
  if (status.reason === "background_unverified") return "凭据已更新，正在等待后台确认身份；任务空闲后会自动重试，无需重复登录。";
  return status.reason === "background_unreachable"
    ? "暂时无法核实 Codex 后台状态，尚未替换凭据。后台恢复后自动重试，也可取消。"
    : "正在等待执行中的任务结束，每 2 秒检查一次；空闲会话无需退出，确认无活跃任务后自动切换。";
}
