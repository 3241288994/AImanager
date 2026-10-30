import type { CodexProfileStatus, LoginStatusResult } from "@/types";

/** Login success and CLI activation are separate results; never claim both on
 * the basis of a stored OAuth credential or another session's current account. */
export async function activateCodexLogin(
  login: LoginStatusResult,
  apply: (accountId: string) => Promise<CodexProfileStatus>,
): Promise<CodexProfileStatus> {
  if (login.status !== "success" || !login.accountId) {
    throw new Error("授权已保存，但服务未返回本次登录的账号；请升级服务后在账号卡片中设为默认。");
  }
  const result = await apply(login.accountId);
  if (result.accountSwitch?.accountId === login.accountId) {
    if (result.accountSwitch.state === "pending") return result;
    if (["failed", "attention"].includes(result.accountSwitch.state)) {
      throw new Error("账号授权已保存，但切换尚未完成；请查看换号状态并重试，无需重复添加账号。");
    }
  }
  if (!result.identityConsistent || result.selectedAccountId !== login.accountId) {
    throw new Error("授权已保存，但 Codex 凭据同步校验未通过；请在账号卡片中重新设为默认。");
  }
  return result;
}
