import type { WebCommandDescriptor } from "./shared";

export function createMiscWebCommands(): Record<string, WebCommandDescriptor> {
  return {
    service_model_catalog_list: { rpcMethod: "apikey/modelCatalogList" },
    service_initialize: { rpcMethod: "initialize" },
    app_settings_get: { rpcMethod: "appSettings/get" },
    app_settings_set: {
      rpcMethod: "appSettings/set",
      mapParams: (params) =>
        params && typeof params.patch === "object" && params.patch !== null
          ? (params.patch as Record<string, unknown>)
          : {},
    },
  };
}
