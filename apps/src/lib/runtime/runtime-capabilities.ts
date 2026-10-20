import type { RuntimeCapabilities, RuntimeMode } from "@/types";

export const DEFAULT_WEB_RPC_BASE_URL = "/api/rpc";
export const DEFAULT_WEB_AUTHOR_CONTENT_URL = "/api/author-content";
export const DEFAULT_UNSUPPORTED_WEB_REASON =
  "当前页面缺少 AImanager Web 运行壳，无法访问管理 RPC。请通过 codexmanager-web 打开，或在反向代理中转发 /api/rpc。";
const CONFIGURED_AUTHOR_CONTENT_URL =
  normalizeAuthorContentUrl(
    process.env.NEXT_PUBLIC_CODEXMANAGER_AUTHOR_CONTENT_URL
  );
const CONFIGURED_WEB_AUTHOR_CONTENT_URL = normalizeAuthorContentUrl(
  process.env.NEXT_PUBLIC_CODEXMANAGER_AUTHOR_CONTENT_URL
);

export type RuntimeCapabilityView = {
  runtimeCapabilities: RuntimeCapabilities | null;
  mode: RuntimeMode;
  isDesktopRuntime: boolean;
  isUnsupportedWebRuntime: boolean;
  canAccessManagementRpc: boolean;
  canManageService: boolean;
  canSelfUpdate: boolean;
  canCloseToTray: boolean;
  canOpenLocalDir: boolean;
  canUseBrowserFileImport: boolean;
  canUseBrowserDownloadExport: boolean;
  authorContentUrl: string | null;
};

/**
 * 函数 `asRecord`
 *
 * 作者: gaohongshun
 *
 * 时间: 2026-04-02
 *
 * # 参数
 * - value: 参数 value
 *
 * # 返回
 * 返回函数执行结果
 */
function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/**
 * 函数 `asString`
 *
 * 作者: gaohongshun
 *
 * 时间: 2026-04-02
 *
 * # 参数
 * - value: 参数 value
 *
 * # 返回
 * 返回函数执行结果
 */
function asString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

/**
 * 函数 `asBoolean`
 *
 * 作者: gaohongshun
 *
 * 时间: 2026-04-02
 *
 * # 参数
 * - value: 参数 value
 * - fallback: 参数 fallback
 *
 * # 返回
 * 返回函数执行结果
 */
function asBoolean(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

export function normalizeAuthorContentUrl(
  value: string | null | undefined
): string {
  const normalized = asString(value);
  if (!normalized) {
    return "";
  }
  if (/^https?:\/\//i.test(normalized)) {
    return normalized;
  }
  return normalized.startsWith("/") && !normalized.startsWith("//")
    ? normalized
    : "";
}

/**
 * 函数 `normalizeRpcBaseUrl`
 *
 * 作者: gaohongshun
 *
 * 时间: 2026-04-02
 *
 * # 参数
 * - value: 参数 value
 *
 * # 返回
 * 返回函数执行结果
 */
export function normalizeRpcBaseUrl(value: string | null | undefined): string {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return "";
  }
  return normalized.endsWith("/")
    ? normalized.replace(/\/+$/, "") || DEFAULT_WEB_RPC_BASE_URL
    : normalized;
}

/**
 * 函数 `isRuntimeMode`
 *
 * 作者: gaohongshun
 *
 * 时间: 2026-04-02
 *
 * # 参数
 * - value: 参数 value
 *
 * # 返回
 * 返回函数执行结果
 */
export function isRuntimeMode(value: string): value is RuntimeMode {
  return (
    value === "desktop-tauri" ||
    value === "web-gateway" ||
    value === "unsupported-web"
  );
}

/**
 * 函数 `buildDesktopRuntimeCapabilities`
 *
 * 作者: gaohongshun
 *
 * 时间: 2026-04-02
 *
 * # 参数
 * 无
 *
 * # 返回
 * 返回函数执行结果
 */
export function buildDesktopRuntimeCapabilities(): RuntimeCapabilities {
  return {
    mode: "desktop-tauri",
    rpcBaseUrl: DEFAULT_WEB_RPC_BASE_URL,
    authorContentUrl: CONFIGURED_AUTHOR_CONTENT_URL || null,
    canManageService: true,
    canSelfUpdate: true,
    canCloseToTray: true,
    canOpenLocalDir: true,
    canUseBrowserFileImport: true,
    canUseBrowserDownloadExport: true,
    unsupportedReason: null,
  };
}

/**
 * 函数 `buildWebGatewayRuntimeCapabilities`
 *
 * 作者: gaohongshun
 *
 * 时间: 2026-04-02
 *
 * # 参数
 * - rpcBaseUrl: 参数 rpcBaseUrl
 *
 * # 返回
 * 返回函数执行结果
 */
export function buildWebGatewayRuntimeCapabilities(
  rpcBaseUrl = DEFAULT_WEB_RPC_BASE_URL
): RuntimeCapabilities {
  return {
    mode: "web-gateway",
    rpcBaseUrl: normalizeRpcBaseUrl(rpcBaseUrl) || DEFAULT_WEB_RPC_BASE_URL,
    authorContentUrl:
      CONFIGURED_WEB_AUTHOR_CONTENT_URL || DEFAULT_WEB_AUTHOR_CONTENT_URL,
    canManageService: false,
    canSelfUpdate: false,
    canCloseToTray: false,
    canOpenLocalDir: false,
    canUseBrowserFileImport: true,
    canUseBrowserDownloadExport: true,
    unsupportedReason: null,
  };
}

/**
 * 函数 `buildUnsupportedWebCapabilities`
 *
 * 作者: gaohongshun
 *
 * 时间: 2026-04-02
 *
 * # 参数
 * - reason: 参数 reason
 * - rpcBaseUrl: 参数 rpcBaseUrl
 *
 * # 返回
 * 返回函数执行结果
 */
export function buildUnsupportedWebCapabilities(
  reason = DEFAULT_UNSUPPORTED_WEB_REASON,
  rpcBaseUrl = DEFAULT_WEB_RPC_BASE_URL
): RuntimeCapabilities {
  return {
    mode: "unsupported-web",
    rpcBaseUrl: normalizeRpcBaseUrl(rpcBaseUrl) || DEFAULT_WEB_RPC_BASE_URL,
    authorContentUrl: CONFIGURED_AUTHOR_CONTENT_URL || null,
    canManageService: false,
    canSelfUpdate: false,
    canCloseToTray: false,
    canOpenLocalDir: false,
    canUseBrowserFileImport: false,
    canUseBrowserDownloadExport: false,
    unsupportedReason: reason,
  };
}

/**
 * 函数 `normalizeRuntimeCapabilities`
 *
 * 作者: gaohongshun
 *
 * 时间: 2026-04-02
 *
 * # 参数
 * - payload: 参数 payload
 * - fallbackRpcBaseUrl: 参数 fallbackRpcBaseUrl
 *
 * # 返回
 * 返回函数执行结果
 */
export function normalizeRuntimeCapabilities(
  payload: unknown,
  fallbackRpcBaseUrl = DEFAULT_WEB_RPC_BASE_URL
): RuntimeCapabilities {
  const source = asRecord(payload) ?? {};
  const modeValue = asString(source.mode);
  const mode: RuntimeMode = isRuntimeMode(modeValue) ? modeValue : "web-gateway";
  const defaultCapabilities =
    mode === "desktop-tauri"
      ? buildDesktopRuntimeCapabilities()
      : mode === "unsupported-web"
        ? buildUnsupportedWebCapabilities(undefined, fallbackRpcBaseUrl)
        : buildWebGatewayRuntimeCapabilities(fallbackRpcBaseUrl);

  return {
    mode,
    rpcBaseUrl:
      normalizeRpcBaseUrl(asString(source.rpcBaseUrl)) ||
      defaultCapabilities.rpcBaseUrl,
    authorContentUrl:
      normalizeAuthorContentUrl(asString(source.authorContentUrl)) ||
      defaultCapabilities.authorContentUrl ||
      null,
    canManageService: asBoolean(
      source.canManageService,
      defaultCapabilities.canManageService
    ),
    canSelfUpdate: asBoolean(
      source.canSelfUpdate,
      defaultCapabilities.canSelfUpdate
    ),
    canCloseToTray: asBoolean(
      source.canCloseToTray,
      defaultCapabilities.canCloseToTray
    ),
    canOpenLocalDir: asBoolean(
      source.canOpenLocalDir,
      defaultCapabilities.canOpenLocalDir
    ),
    canUseBrowserFileImport: asBoolean(
      source.canUseBrowserFileImport,
      defaultCapabilities.canUseBrowserFileImport
    ),
    canUseBrowserDownloadExport: asBoolean(
      source.canUseBrowserDownloadExport,
      defaultCapabilities.canUseBrowserDownloadExport
    ),
    unsupportedReason:
      asString(source.unsupportedReason) || defaultCapabilities.unsupportedReason || null,
  };
}

/**
 * 函数 `resolveRuntimeCapabilityView`
 *
 * 作者: gaohongshun
 *
 * 时间: 2026-04-02
 *
 * # 参数
 * - runtimeCapabilities: 参数 runtimeCapabilities
 * - desktopFallback: 参数 desktopFallback
 *
 * # 返回
 * 返回函数执行结果
 */
export function resolveRuntimeCapabilityView(
  runtimeCapabilities: RuntimeCapabilities | null,
  desktopFallback: boolean
): RuntimeCapabilityView {
  const resolvedCapabilities = runtimeCapabilities ??
    (desktopFallback
      ? buildDesktopRuntimeCapabilities()
      : buildUnsupportedWebCapabilities());
  const mode = resolvedCapabilities.mode;
  const isDesktopRuntime = mode === "desktop-tauri";

  return {
    runtimeCapabilities,
    mode,
    isDesktopRuntime,
    isUnsupportedWebRuntime: mode === "unsupported-web",
    canAccessManagementRpc: mode !== "unsupported-web",
    canManageService: resolvedCapabilities.canManageService,
    canSelfUpdate: resolvedCapabilities.canSelfUpdate,
    canCloseToTray: resolvedCapabilities.canCloseToTray,
    canOpenLocalDir: resolvedCapabilities.canOpenLocalDir,
    canUseBrowserFileImport: resolvedCapabilities.canUseBrowserFileImport,
    canUseBrowserDownloadExport: resolvedCapabilities.canUseBrowserDownloadExport,
    authorContentUrl: resolvedCapabilities.authorContentUrl || null,
  };
}
