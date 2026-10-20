import type { WebCommandDescriptor } from "./shared";

export function createAiConnectionsWebCommands(): Record<string, WebCommandDescriptor> {
  return {
    service_ai_accounts_action: { rpcMethod: "aiAccounts/action", mapParams: p => p?.params as Record<string, unknown> },
    service_ai_connections_list: { rpcMethod: "aiConnections/list" },
    service_ai_connections_save: { rpcMethod: "aiConnections/save", mapParams: p => p?.connection as Record<string, unknown> },
    service_ai_connections_delete: { rpcMethod: "aiConnections/delete" },
    service_ai_connections_probe: { rpcMethod: "aiConnections/probe" },
  };
}
