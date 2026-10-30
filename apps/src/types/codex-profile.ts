export type CodexProfileMode =
  | "missing"
  | "unmanaged"
  | "direct_account"
  | "gateway"
  | "managed_unknown";

export interface CodexProfileStatus {
  accountSwitch?: CodexAccountSwitch | null;
  codexHome: string;
  authPath: string;
  configPath: string;
  managedStorageRoot: string;
  markerPath: string;
  historyBackupRoot: string;
  historyBackupCount: number;
  historyBackupBytes: number;
  historyRetention: CodexProfileHistoryRetention;
  mode: CodexProfileMode;
  selectedAccountId: string | null;
  actualAccountId: string | null;
  identityConsistent: boolean;
  selectedApiKeyId: string | null;
  gatewayBaseUrl: string | null;
  providerId: string;
  hasBackup: boolean;
  lastAppliedAt: number | null;
  profileWritable: boolean;
  error: string | null;
  warnings: string[];
  historyRepair: CodexProfileHistoryRepairSummary | null;
}

export interface CodexAccountSwitch {
  syncDevices?: boolean;
  requestId: string;
  accountId: string;
  previousAccountId: string | null;
  codexHome: string;
  state: "pending" | "completed" | "failed" | "attention";
  reason: string;
  requestedAt: number;
  updatedAt: number;
}

export interface CodexDeviceTask {
  requestId:string;
  parentRequestId:string|null;
  accountId:string;
  kind:"switch"|"login";
  state:"pending"|"needs_login"|"authorizing"|"completed"|"failed"|"attention"|"cancelled";
  reason:string;
  requestedAt:number;
  updatedAt:number;
  verificationUrl:string|null;
  userCode:string|null;
}
export interface CodexDevice {
  id:string;
  label:string;
  lastSeenAt:number;
  currentAccountId:string|null;
  knownAccountIds:string[];
  task:CodexDeviceTask|null;
}

export interface CodexProfileHistoryRetention {
  maxHistoryBackupsPerProfile: number;
  maxHistoryBackupAgeDays: number;
  minHistoryBackupsPerProfile: number;
}

export interface CodexProfileHistoryRepairSummary {
  codexHome: string;
  targetProvider: string;
  changedRolloutFileCount: number;
  updatedSqliteRowCount: number;
  addedSessionIndexEntryCount: number;
  backupDir: string | null;
  warnings: string[];
  message: string;
}

export interface CodexProfilePruneHistoryBackupsResult {
  codexHome: string;
  historyBackupRoot: string;
  beforeCount: number;
  afterCount: number;
  removedCount: number;
  beforeBytes: number;
  afterBytes: number;
  removedBytes: number;
  retention: CodexProfileHistoryRetention;
  warnings: string[];
}

export interface CodexProfileAccountCandidate {
  id: string;
  label: string;
  groupName: string | null;
  status: string;
  chatgptAccountId: string | null;
  workspaceId: string | null;
  issuer: string;
  lastRefresh: number | null;
}

export interface CodexProfileApiKeyCandidate {
  id: string;
  name: string | null;
  status: string;
  modelSlug: string | null;
  reasoningEffort: string | null;
}

export interface CodexProfileCandidates {
  accounts: CodexProfileAccountCandidate[];
  apiKeys: CodexProfileApiKeyCandidate[];
}
