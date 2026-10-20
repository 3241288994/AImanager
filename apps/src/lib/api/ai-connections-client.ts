import { invoke, withAddr } from "./transport";

export interface AiConnection {
  id: string;
  name: string;
  baseUrl: string;
  credentialSource: "gemini-web-client" | "aimanager-env";
  enabled: boolean;
}
export interface AiConnectionsOverview {
  items: AiConnection[];
  host: string;
  cli: { id: string; name: string; installed: boolean; command: string; authStatus: "not_checked" }[];
}
export interface AiConnectionProbe {
  id: string;
  status: string;
  latencyMs: number;
  models: string[];
  health: string;
  healthSummary?: { readyAccounts: number | null; accounts: { index: number; status: string; cooldownSeconds: number | null }[] | null } | null;
  healthError?: string | null;
  generationVerified: boolean;
  note: string;
}
export const aiConnectionsClient = {
  list: () => invoke<AiConnectionsOverview>("service_ai_connections_list", withAddr()),
  save: (connection: AiConnection) => invoke<{ items: AiConnection[] }>("service_ai_connections_save", withAddr({ connection })),
  remove: (id: string) => invoke<{ items: AiConnection[] }>("service_ai_connections_delete", withAddr({ id })),
  probe: (id: string) => invoke<AiConnectionProbe>("service_ai_connections_probe", withAddr({ id }), { timeoutMs: 30_000 }),
};
