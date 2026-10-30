import { invoke, withAddr } from "./transport";
import type { CodexDevice } from "@/types/codex-profile";

export const codexDevicesClient = {
  status(): Promise<CodexDevice[]> {
    return invoke("service_codex_devices_status",withAddr());
  },
  login(deviceId:string,accountId:string): Promise<CodexDevice[]> {
    return invoke("service_codex_devices_login",withAddr({deviceId,accountId}),{timeoutMs:15000,retries:0});
  },
};
