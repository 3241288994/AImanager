import { invoke, withAddr } from "./transport";
import { normalizeAccountList, normalizeLoginStartResult, normalizeUsageList } from "./normalize";
import type { AccountListResult, AccountUsage, LoginStartResult, LoginStatusResult } from "../../types";

interface LoginStartPayload {
  loginType?: string;
  openBrowser?: boolean;
}

export interface UsageRefreshResult {
  accountId: string;
  credentialsSyncedFromProfile: boolean;
  availabilityStatus: string;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

export const accountClient = {
  autoRefreshStatus(): Promise<{ usagePollingEnabled: boolean; usagePollIntervalSecs: number }> {
    return invoke("service_usage_polling_status", withAddr());
  },
  async list(): Promise<AccountListResult> {
    return normalizeAccountList(await invoke<unknown>("service_account_list", withAddr()));
  },

  async listUsage(): Promise<AccountUsage[]> {
    return normalizeUsageList(await invoke<unknown>("service_usage_list", withAddr()));
  },

  refreshUsage(accountId: string): Promise<UsageRefreshResult> {
    const target = accountId?.trim();
    return invoke(
      "service_usage_refresh",
      withAddr(target ? { accountId: target, account_id: target } : {}),
    );
  },

  async startLogin(params: LoginStartPayload = {}): Promise<LoginStartResult> {
    const result = await invoke<unknown>(
      "service_login_start",
      withAddr({
        loginType: params.loginType || "chatgpt",
        openBrowser: params.openBrowser ?? false,
      }),
      { timeoutMs: 90_000, retries: 0 },
    );
    return normalizeLoginStartResult(result);
  },

  async getLoginStatus(loginId: string): Promise<LoginStatusResult> {
    const source = record(await invoke<unknown>("service_login_status", withAddr({ loginId })));
    return {
      status: typeof source.status === "string" ? source.status : "",
      error: typeof source.error === "string" ? source.error : "",
      accountId: typeof source.accountId === "string" ? source.accountId : null,
    };
  },
};
