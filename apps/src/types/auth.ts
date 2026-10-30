export interface LoginStatusResult {
  status: string;
  error: string;
  accountId?: string | null;
}

export interface DeviceAuthInfo {
  userCodeUrl: string;
  tokenUrl: string;
  verificationUrl: string;
  redirectUri: string;
}

export interface LoginStartResult {
  type: string;
  authUrl?: string | null;
  loginId: string;
  verificationUrl?: string | null;
  userCode?: string | null;
}

export interface CurrentAccessTokenAccount {
  type: string;
  accountId: string;
  email: string;
  planType: string;
  planTypeRaw?: string | null;
  hasSubscription?: boolean | null;
  subscriptionPlan?: string | null;
  subscriptionExpiresAt?: number | null;
  subscriptionRenewsAt?: number | null;
  chatgptAccountId: string | null;
  workspaceId: string | null;
  status: string;
}

export interface CurrentAccessTokenAccountReadResult {
  account: CurrentAccessTokenAccount | null;
  requiresOpenaiAuth: boolean;
}

export interface ChatgptAuthTokensRefreshResult {
  accessToken: string;
  chatgptAccountId: string;
  chatgptPlanType: string | null;
  hasSubscription?: boolean | null;
  subscriptionPlan?: string | null;
  subscriptionExpiresAt?: number | null;
  subscriptionRenewsAt?: number | null;
}

export interface ChatgptAuthTokensRefreshAllItem {
  accountId: string;
  accountName: string;
  ok: boolean;
  message: string | null;
}

export interface ChatgptAuthTokensRefreshAllResult {
  requested: number;
  succeeded: number;
  failed: number;
  skipped: number;
  results: ChatgptAuthTokensRefreshAllItem[];
}
