import type { LoginStartResult } from "@/types/auth";

export type CodexLoginMethod = "device" | "browser";
export const DEFAULT_CODEX_LOGIN_METHOD: CodexLoginMethod = "device";

export function codexLoginOptions(method: CodexLoginMethod) {
  return {
    loginType: method === "device" ? "chatgptDeviceCode" : "chatgpt",
    openBrowser: false,
    waitMs: (method === "device" ? 15 : 5) * 60_000,
  };
}

export function validateCodexLoginStart(result: LoginStartResult, method: CodexLoginMethod) {
  const url = method === "device" ? result.verificationUrl : result.authUrl;
  if (!result.loginId || !url || (method === "device" && !result.userCode)) {
    throw new Error("登录响应缺少设备码或授权地址，请检查服务版本后重试。");
  }
  if (new URL(url).protocol !== "https:") {
    throw new Error("官方授权地址必须使用 HTTPS，请检查服务配置。");
  }
  return url;
}

/** Translation keys only: never render upstream HTML, codes or tokens as errors. */
export function codexLoginError(message: string): string {
  const error = message.toLowerCase();
  if (/cloudflare|just a moment|cf-mitigated|verification_required|device_authorization_verification/.test(error)) {
    return "OpenAI 返回安全验证页，授权尚未完成。请检查浏览器及服务主机的网络；这不代表账号被封禁，设备码也不能绕过安全验证。";
  }
  if (/device code login is not enabled|device code endpoint unavailable|device[_ ]auth.*disabled|device[_ ]code.*disabled/.test(error)) {
    return "设备码登录暂不可用。请在目标账号的 ChatGPT 安全设置中允许设备码登录；若仍不可用，请检查工作区权限及服务端认证地址。";
  }
  if (/device auth timed out|expired_token|expired.*device|device.*expired/.test(error)) {
    return "设备码已过期，请重新生成；不要重复使用旧码。当前默认账号未改变。";
  }
  if (/access_denied|authorization_denied|user.*denied/.test(error)) {
    return "官方页面拒绝或取消了本次授权，当前默认账号未改变。需要时重新生成设备码。";
  }
  if (/403|forbidden/.test(error)) {
    return "OpenAI 拒绝了认证请求（403）。请检查服务主机网络与账号的设备码登录权限；仅凭此状态不能判定具体原因。";
  }
  if (/429|too many requests|rate.limit/.test(error)) {
    return "认证请求过于频繁，请稍后重新发起，不要连续重试旧码。";
  }
  if (/timeout|timed out|connect|dns|tls|certificate|network|sending request|连接|网络/.test(error)) {
    return "服务主机连接 OpenAI 认证服务失败。请检查服务器代理、DNS 和 TLS，网络恢复后重新授权。";
  }
  if (["登录响应缺少设备码或授权地址，请检查服务版本后重试。", "官方授权地址必须使用 HTTPS，请检查服务配置。"].includes(message)) return message;
  return "本次授权未完成，官方服务未返回可识别原因。请重新生成登录信息；若持续失败，请检查服务端认证日志。当前默认账号未改变。";
}
