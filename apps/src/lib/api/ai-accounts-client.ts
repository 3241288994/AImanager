import type { AnalyticsDay } from "./usage-analytics-client";
import { invoke, withAddr } from "./transport";

export type AiProvider = "claude" | "antigravity";
export interface ManagedAiAccount {
  id: string;
  provider: AiProvider;
  label: string;
  active: boolean;
  authStatus: "unknown" | "authenticated" | "signed_out";
  authMethod?: string;
  authNote?: string;
  checkedAt?: number;
  quota: { lastError?: string; lastAttemptAt?: number; reasonCode?: string; state: "unknown" | "available" | "unavailable"; source?: string; checkedAt?: number; note?: string;
    windows: { label: string; usedPercent: number; remainingPercent: number; resetsAt: string | null }[] };
}
export interface AiAccountList {
  items: ManagedAiAccount[];
  summary: { accounts: number; authenticated: number; quotaKnown: number };
}
export interface AiAuthSession {
  id: string;
  accountId: string;
  kind: "login" | "usage";
  phase: string;
  authorizationUrl: string | null;
  message: string;
  reasonCode?: string | null;
  startedAt: number;
  updatedAt: number;
}
export const FINAL_AUTH_PHASES = new Set(["succeeded", "failed", "cancelled", "expired"]);
export function officialAuthUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password || url.hash) return null;
    if (["access_token", "refresh_token", "id_token", "client_secret"].some(key => url.searchParams.has(key))) return null;
    const manualFlow = ["claude.ai", "claude.com"].includes(url.hostname) && ["/oauth/authorize", "/cai/oauth/authorize"].includes(url.pathname) && url.searchParams.getAll("code").length === 1 && url.searchParams.get("code") === "true";
    if (url.searchParams.has("code") && !manualFlow) return null;
    return ["claude.ai", "claude.com", "console.anthropic.com", "auth.anthropic.com", "accounts.google.com", "antigravity.google", "antigravity.google.com", "codeassist.google.com"].includes(url.hostname) ? value : null;
  } catch { return null; }
}
function action<T>(params: Record<string, unknown>): Promise<T> {
  return invoke<T>("service_ai_accounts_action", withAddr({ params }), { timeoutMs: 30_000 });
}
export interface CliAnalyticsReport {
  accountId: string; provider: AiProvider; source: string; startDate: string; endDate: string;
  days: AnalyticsDay[]; checkedAt: number; note: string;
  coverage: { filesScanned: number; partial: boolean };
  quotaHistory: { capturedAt: number; windows: { label: string; remainingPercent: number; resetsAt: string | null }[] }[];
}
export interface CliSessionItem {
  id: string; title: string; cwd: string | null; updatedAtMs: number; source: string;
  cwdExists: boolean; visibility: "ready" | "missing_workspace" | "unknown_workspace"; resumeCommand: string;
}
export interface CliSessionCatalog {
  accountId: string; provider: AiProvider; items: CliSessionItem[]; total: number;
  coverage: { filesScanned: number; partial: boolean }; checkedAt: number; continueCommand: string; note: string;
}
export const aiAccountsClient = {
  sessions: (accountId: string, query = "", limit = 100) => action<CliSessionCatalog>({ action: "sessionCatalog", accountId, query, limit }),
  analytics: (accountId: string, startDate: string, endDate: string) => action<CliAnalyticsReport>({ action: "analytics", accountId, startDate, endDate }),
  list: () => action<AiAccountList>({ action: "list" }),
  sync: (force = false) => action<AiAccountList>({ action: "sync", force }),
  connect: (provider: AiProvider) => action<AiAuthSession>({ action: "connect", provider }),
  create: (provider: AiProvider, label: string) => action<ManagedAiAccount>({ action: "create", provider, label }),
  select: (accountId: string) => action<{ activeAccountId: string; note: string }>({ action: "select", accountId }),
  check: (accountId: string) => action<{ authStatus: string }>({ action: "check", accountId }),
  login: (accountId: string) => action<AiAuthSession>({ action: "login", accountId }),
  usage: (accountId: string) => action<AiAuthSession>({ action: "usage", accountId }),
  session: (sessionId: string) => action<AiAuthSession>({ action: "session", sessionId }),
  sendCode: (sessionId: string, code: string) => action<AiAuthSession>({ action: "input", sessionId, inputAction: "code", code }),
  confirm: (sessionId: string) => action<AiAuthSession>({ action: "input", sessionId, inputAction: "confirm" }),
  cancel: (sessionId: string) => action<AiAuthSession>({ action: "cancel", sessionId }),
};
