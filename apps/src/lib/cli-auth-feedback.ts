import type { AiAuthSession } from "./api/ai-accounts-client";

type AuthFeedback = { title: string; description: string; nextStep: string; reasonCode: string };
const FAILURES: Record<string, Omit<AuthFeedback, "reasonCode">> = {
  authorization_code_invalid: { title: "返回码无效", description: "官方客户端拒绝了本次返回码，可能未完整复制。", nextStep: "复制官方页面的完整返回码，不是地址栏网址；已尝试过的码请不要重复提交。" },
  authorization_code_expired: { title: "返回码已过期", description: "官方客户端明确报告本次返回码已过期。", nextStep: "关闭旧授权页，重新发起网页登录，并及时把新码提交到同一个窗口。" },
  authorization_code_used: { title: "返回码已使用", description: "官方客户端明确报告本次返回码已使用。", nextStep: "重新发起网页登录，不要重复提交同一个码。" },
  authorization_state_mismatch: { title: "授权会话不匹配", description: "官方客户端报告返回码与当前登录会话不匹配。", nextStep: "关闭旧授权页，从当前 AImanager 窗口重新发起，只提交本次生成的返回码。" },
  authorization_rejected: { title: "返回码兑换被拒绝", description: "官方服务返回 invalid_grant，但没有细分原因；不能确定是过期、已使用还是会话不匹配。", nextStep: "重新发起网页登录，使用本次官方页面显示的完整返回码。" },
  authorization_denied: { title: "授权被拒绝或取消", description: "官方服务未批准本次授权，不代表账号已被封禁。", nextStep: "确认官方页面已完成授权；需要重试时重新发起，不要重复提交旧码。" },
  session_expired: { title: "授权会话已过期", description: "本次窗口已经超过等待时限，不能继续接收返回码。", nextStep: "重新点击网页登录；新码必须提交到生成该授权链接的同一个窗口。" },
  network_unavailable: { title: "服务主机连接认证服务失败", description: "官方客户端报告网络、代理、DNS 或 TLS 连接异常。", nextStep: "检查运行 AImanager Service 的机器，而不只是浏览器所在电脑；网络恢复后重新授权。" },
  auth_service_unavailable: { title: "官方认证服务暂不可用", description: "官方客户端报告服务异常或请求过于频繁。", nextStep: "稍后重新发起授权，不要连续重试旧码。" },
  credential_store_unavailable: { title: "授权凭证未能保存", description: "官方客户端报告凭证存储或目录权限错误。", nextStep: "检查服务主机配置目录的写权限、磁盘空间及钥匙串，不要删除已有凭证。" },
  cli_incompatible: { title: "官方 CLI 接口不兼容", description: "服务主机的 CLI 不支持当前登录或状态检查接口。", nextStep: "检查原生 CLI 的版本和配置路径，不要将托管启动器配置成原生 CLI。" },
  auth_status_unavailable: { title: "暂时无法确认登录状态", description: "状态检查未完成，授权可能已保存，不能直接认定登录失败。", nextStep: "先关闭窗口并同步登录状态；仍未登录时再重新授权，避免重复提交返回码。" },
  authorization_not_verified: { title: "登录尚未确认", description: "官方客户端未确认登录，也未返回可识别的具体原因。不能据此判断是账号、网络还是返回码问题。", nextStep: "先同步登录状态；仍未登录时重新发起，复制官方返回码而非回调网址，并提交到同一个窗口。" },
};

export function cliAuthFeedback(session?: Pick<AiAuthSession, "kind" | "phase" | "reasonCode">): AuthFeedback | null {
  if (!session || session.kind !== "login" || ["succeeded", "cancelled"].includes(session.phase)) return null;
  const reason = session.phase === "expired" ? "session_expired"
    : session.reasonCode && Object.hasOwn(FAILURES, session.reasonCode) ? session.reasonCode
      : session.phase === "failed" ? "authorization_not_verified" : null;
  return reason ? { ...FAILURES[reason], reasonCode: reason } : null;
}
