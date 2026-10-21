import { expect, test, type Page } from "@playwright/test";

const now = new Date("2026-08-31T12:00:00.000Z").toISOString();

const settings = {
  locale: "zh-CN",
  localeOptions: ["zh-CN", "en"],
  serviceAddr: "localhost:48760",
  webAuthMode: "none",
  theme: "tech",
  appearancePreset: "classic",
  lowTransparency: false,
};

const labContextOverview = {
  version: "test",
  generatedAt: now,
  defaultWorkspaceId: "workspace-1",
  configPath: "/tmp/labcontext.yaml",
  health: {
    overall: "healthy",
    generatedAt: now,
    checks: [],
  },
  workspaces: [
    {
      workspaceId: "workspace-1",
      name: "Example Research",
      root: "/tmp/example-research",
      aliases: [],
      adapters: [],
      isDefault: true,
      status: "ready",
      git: {
        branch: "main",
        commit: "abc123",
        headState: "clean",
        dirty: false,
        changedPathCount: 0,
      },
      description: "A mocked LabContext workspace.",
      overviewSource: "reviewed",
      context: { path: "/tmp/example-research/.labcontext/context.yaml", status: "ready", generation: null },
      assets: [],
      readableAssets: [],
      coverage: { fileCount: 0, totalBytes: 0, emptyAssets: 0 },
      researchMap: {
        status: "empty",
        mapRevision: 0,
        reviewState: "idle",
        coreIdea: null,
        activeClaim: null,
        currentTarget: null,
        nextExperiment: null,
        blockers: [],
        relatedNodes: [],
        counts: { nodes: 0, edges: 0, activeBranches: 0, openRisks: 0 },
        updatedAt: now,
        pendingProposals: 0,
      },
    },
  ],
  workerConfig: {
    model: "gpt-5.4",
    reasoningEffort: "medium",
    availableModels: ["gpt-5.4"],
    availableEfforts: { "gpt-5.4": ["medium"] },
    appliesTo: "new analysis jobs",
  },
  toolPolicy: {
    profile: "research",
    tools: [{
      name: "inspect_path",
      description: "Direct allowed-path inspection without workspace registration",
      latencyClass: "instant",
      dependencies: [],
      enabled: true,
      readOnly: true,
      computeCost: "none",
    }],
  },
  activity: { records: [], totalReturned: 0 },
  jobs: { jobs: [], statusCounts: {} },
};

const researchMapBundle = {
  workspaceId: "workspace-1",
  researchMap: {
    schemaVersion: 1,
    workspaceId: "workspace-1",
    revision: 0,
    reviewState: "idle",
    currentFocusNodeId: null,
    nodes: [],
    edges: [],
    createdAt: now,
    updatedAt: now,
    updatedBy: "test",
  },
  layout: {
    schemaVersion: 1,
    workspaceId: "workspace-1",
    nodes: [],
    viewport: { x: 0, y: 0, zoom: 1 },
    updatedAt: null,
    updatedBy: null,
  },
  focusCapsule: {
    status: "empty",
    mapRevision: 0,
    reviewState: "idle",
    coreIdea: null,
    activeClaim: null,
    currentTarget: null,
    nextExperiment: null,
    blockers: [],
    relatedNodes: [],
    counts: { nodes: 0, edges: 0, activeBranches: 0, openRisks: 0 },
    updatedAt: now,
  },
  proposals: [],
  events: [],
};

async function mockConsoleApi(
  page: Page,
  localRouter = false,
  recoveryOutcome: "succeeded" | "failed" | null = null,
) {
  const methods: string[] = [];
  let repairRequested = false;
  await page.route("http://127.0.0.1:1460/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/recovery/repair") {
      repairRequested = true;
      await route.fulfill({
        status: 202,
        contentType: "application/json; charset=utf-8",
        body: JSON.stringify({ schemaVersion: 1, phase: "queued", summary: "修复任务已创建" }),
      });
      return;
    }
    if (url.pathname === "/api/recovery") {
      const failed = recoveryOutcome === "failed";
      await route.fulfill({
        contentType: "application/json; charset=utf-8",
        body: JSON.stringify(repairRequested ? {
          schemaVersion: 1,
          phase: failed ? "failed" : "succeeded",
          summary: failed ? "服务器反向转发端口 17987 已被占用，无法安全自动接管" : "一键修复完成，LabContext 已完全连通",
          detail: failed ? "remote port forwarding failed for listen port 17987" : "全部能力检查通过",
          reasonCode: failed ? "ssh_reverse_port_in_use" : undefined,
          suggestions: failed ? ["停止服务器上的旧 LabContext SSH 会话后再次修复。"] : [],
          command: failed ? "labcontext repair" : undefined,
        } : { schemaVersion: 1, phase: "idle", summary: "当前没有恢复任务" }),
      });
      return;
    }
    if (url.pathname === "/api/status") {
      const providers: Record<string, unknown>[] = localRouter ? [{
        id: "local",
        label: "This computer",
        mcpUrl: "http://127.0.0.1:1456/mcp",
        adminEnabled: true,
        status: "ready",
        adminStatus: "ready",
        serverName: "LabContext",
        serverVersion: "0.9.0",
        minimumVersion: "0.7.0",
        protocolVersion: "2025-06-18",
        toolCount: 12,
        workspaceCount: 1,
        latencyMs: 8,
      }] : [];
      if (recoveryOutcome) providers.push({
        id: "server",
        label: "Research server",
        mcpUrl: "http://127.0.0.1:1455/mcp",
        adminEnabled: false,
        status: "unavailable",
        adminStatus: "disabled",
        error: "provider server is unavailable: connection refused",
      });
      await route.fulfill({
        contentType: "application/json; charset=utf-8",
        body: JSON.stringify({
          schemaVersion: 1,
          checkedAt: new Date().toISOString(),
          overall: recoveryOutcome ? "degraded" : localRouter ? "ready" : "unavailable",
          router: { status: "ready", name: "LabContext Router", version: "0.4.0", pid: 1234 },
          launcher: {
            status: "running",
            launcherPid: 1233,
            components: recoveryOutcome ? [{
              id: "ssh-bridge", label: "SSH bridge", pid: 1232, status: "retrying", exitCode: 255,
            }] : [],
          },
          providers,
          tunnel: { enabled: false, status: "disabled", detail: "未启用 Secure MCP Tunnel" },
        }),
      });
      return;
    }
    const body = JSON.parse(route.request().postData() || "{}");
    const result = body.operation === "getResearchMap" ? researchMapBundle : labContextOverview;
    await route.fulfill({
      contentType: "application/json; charset=utf-8",
      body: JSON.stringify({ result }),
    });
  });
  await page.route("**/api/runtime**", async (route) => {
    await route.fulfill({
      contentType: "application/json; charset=utf-8",
      body: JSON.stringify({
        mode: "web-gateway",
        rpcBaseUrl: "/api/rpc",
        canManageService: false,
        canSelfUpdate: false,
        canCloseToTray: false,
        canOpenLocalDir: false,
        canUseBrowserFileImport: true,
        canUseBrowserDownloadExport: true,
      }),
    });
  });
  await page.route("**/api/rpc", async (route) => {
    const request = route.request();
    const body = JSON.parse(request.postData() || "{}");
    methods.push(body.method);
    const responses: Record<string, unknown> = {
      "aiConnections/probe": { id: "gemini-web", status: "reachable", latencyMs: 12, models: ["gemini-argon", "gemini-flash-lite"], health: "reachable", healthSummary: { readyAccounts: 1, accounts: [{ index: 1, status: "ready", cooldownSeconds: 0 }, { index: 2, status: "cooldown", cooldownSeconds: 90 }] }, generationVerified: false, note: "未发送生成请求，不消耗模型额度。" },
      "appSettings/get": settings,
      "aiAccounts/action": { items: [
        { id: "claude-a", provider: "claude", label: "Claude personal", active: true, authStatus: "authenticated", quota: {state: "available", source: "official_oauth_usage", checkedAt: 1792491282, windows: [{label: "5 小时额度", remainingPercent: 82, usedPercent: 18, resetsAt: null}]}, models: { state: "available", items: [{id:"claude-example",name:"Example model"}], source: "official_cli_cache" } },
        { id: "agy-a", provider: "antigravity", label: "Antigravity personal", active: true, authStatus: "authenticated", quota: {state: "unavailable", windows: [], note: "需要完成首次设置"} },
      ], summary: {accounts:2,authenticated:2,quotaKnown:1} },
      "aiConnections/list": {items:[{id:"gemini-web",name:"Gemini 网页账号池",baseUrl:"http://127.0.0.1:16969/v1",credentialSource:"gemini-web-client",enabled:true}],host:"test-host",cli:[]},
      "aiConnections/quota": {readyAccounts:2,checkedAt:Math.floor(Date.now()/1000),note:"自动轮转",accounts:[{index:1,status:"available",tier:"PRO",stale:false,probeFailed:false,usageUpdatedAt:new Date().toISOString(),windows:[{label:"5 小时额度",remainingPercent:82,remainingCredits:1960,resetsAt:null},{label:"每周额度",remainingPercent:null,remainingCredits:null,resetsAt:null}]}]},
      "apikey/modelCatalogList": {items:[{slug:"gpt-example",displayName:"GPT example",sourceKind:"remote"}]},
      initialize: {
        userAgent: "codex_cli_rs/0.1.0",
        codexHome: "/tmp/codex",
        platformFamily: "unix",
        platformOs: "linux",
      },
      "account/list": {
        items: [{id: "account-2",label: "Backup account",status:"active",hasToken:true,planType:"plus"}, {
          id: "account-1",
          label: "Research account",
          status: "active",
          hasToken: true,
          planType: "plus",
        }],
        total: 1,
      },
      "account/usage/list": {
        items: [{
          accountId: "account-1",
          availabilityStatus: "available",
          usedPercent: 12,
          windowMinutes: 300,
          resetsAt: Math.floor(Date.now() / 1000) + 7_200,
          capturedAt: Math.floor(Date.now() / 1000),
        }],
      },
      "account/usage/pollingStatus": {
        usagePollingEnabled: true,
        usagePollIntervalSecs: 600,
      },
      "account/analytics/pricingRefresh": {
        attemptedAt: Math.floor(Date.now() / 1000),
        error: null,
        snapshot: {
          fetchedAt: Math.floor(Date.now() / 1000),
          usdPerCredit: 0.04,
          apiSource: "https://developers.openai.com/api/docs/pricing",
          creditSource: "https://learn.chatgpt.com/docs/pricing",
          apiSha256: "test-api",
          creditSha256: "test-credit",
          evidence: [],
        },
      },
      "account/analytics/read": {
        accountId: body.params?.accountId ?? "account-1",
        source: "chatgpt-wham",
        startDate: body.params?.startDate,
        endDate: body.params?.endDate,
        days: [{
          date: body.params?.startDate,
          totals: {
            credits: 2.5,
            turns: 8,
            uncachedInputTokens: 100,
            cachedInputTokens: 50,
            outputTokens: 25,
            totalTokens: 175,
          },
          capturedAt: Math.floor(Date.now() / 1000),
        }],
        sync: {
          attemptedAt: Math.floor(Date.now() / 1000),
          succeededAt: Math.floor(Date.now() / 1000),
          error: null,
          startDate: body.params?.startDate,
          endDate: body.params?.endDate,
        },
        usdPerCredit: null,
      },
      "codexProfile/get": {
        codexHome: "/tmp/codex",
        mode: "direct_account",
        selectedAccountId: "account-1",
        actualAccountId: "account-1",
        identityConsistent: true,
      },
      "sessionCatalog/list": {
        codexHome: "/tmp/codex",
        total: 1,
        items: [{
          id: "session-1",
          title: "Session Demo",
          cwd: "/tmp/example-research",
          rolloutPath: "/tmp/rollout.jsonl",
          modelProvider: "openai",
          model: "gpt-5.4",
          reasoningEffort: "medium",
          updatedAtMs: 1_788_000_000_000,
          archived: false,
          rolloutExists: true,
          cwdExists: true,
          visibility: "ready",
          resumeCommand: "codex resume session-1",
        }],
        diagnostics: {
          stateDbAvailable: true,
          checkedCount: 1,
          providerMismatchCount: 0,
          missingRolloutCount: 0,
          missingCwdCount: 0,
          message: "mocked",
        },
      },
      "labcontext/overview": labContextOverview,
      "labcontext/getResearchMap": researchMapBundle,
    };
    const result = body.method === "aiAccounts/action" && body.params?.action === "sessionCatalog" ? {
      accountId: body.params.accountId, provider: body.params.accountId === "claude-a" ? "claude" : "antigravity",
      total: body.params.accountId === "claude-a" && !body.params.query ? 1 : 0,
      items: body.params.accountId === "claude-a" && !body.params.query ? [{ id:"12345678-1234-4321-abcd-123456789abc",title:"Claude session demo",cwd:"/workspace/demo",updatedAtMs:1792491282000,source:"claude_jsonl",cwdExists:true,visibility:"ready",resumeCommand:"aimanager-cli claude --account-id claude-a -- --resume 12345678-1234-4321-abcd-123456789abc" }] : [],
      coverage:{filesScanned:1,partial:false}, checkedAt:1792491282, continueCommand:`aimanager-cli ${body.params.accountId === "claude-a" ? "claude" : "antigravity"} --account-id ${body.params.accountId} -- --continue`,note:"本地账号会话索引"
    } : body.method === "aiAccounts/action" && body.params?.action === "analytics" ? {
      accountId:body.params.accountId, provider:body.params.accountId === "claude-a" ? "claude" : "antigravity",
      days:body.params.accountId === "claude-a" ? [{date:body.params.startDate,capturedAt:Math.floor(Date.now()/1000),totals:{credits:null,turns:3,uncachedInputTokens:100,cachedInputTokens:50,outputTokens:20,totalTokens:170}}] : [],
      quotaHistory:[{capturedAt:Math.floor(Date.now()/1000),windows:[{label:"5 小时额度",remainingPercent:82,resetsAt:null}]}],
      coverage:{filesScanned:1,partial:false}, checkedAt:Math.floor(Date.now()/1000),note:"各平台来源独立"
    } : responses[body.method] ?? {};
    await route.fulfill({
      contentType: "application/json; charset=utf-8",
      body: JSON.stringify({ jsonrpc: "2.0", id: body.id ?? 1, result }),
    });
  });
  return methods;
}

test("managed CLI accounts complete browser handoff, selection and official quota refresh", async ({ page }) => {
  await mockConsoleApi(page);
  const item = { id: "a".repeat(32), provider: "claude", label: "Research Claude", active: false, authStatus: "unknown", quota: { state: "unknown", windows: [] as unknown[] } };
  let created = false;
  let complete = false;
  let usage = false;
  await page.route("**/api/rpc", async route => {
    const body = route.request().postDataJSON();
    if (body.method !== "aiAccounts/action") { await route.fallback(); return; }
    const params = body.params;
    const auth = { id: "b".repeat(32), accountId: item.id, kind: usage ? "usage" : "login", phase: usage || complete ? "succeeded" : "awaiting_code", authorizationUrl: "https://claude.com/cai/oauth/authorize?code=true&client_id=test&state=test", message: "Official CLI test handoff", startedAt: 1, updatedAt: 1 };
    let result: unknown;
    if (params.action === "connect") { created = true; result = auth; }
    else if (["list", "sync"].includes(params.action)) result = { items: created ? [item] : [], summary: { accounts: created ? 1 : 0, authenticated: complete ? 1 : 0, quotaKnown: usage ? 1 : 0 } };
    else if (params.action === "input") { expect(params.code).toBe("dummy-return-code"); complete = true; item.authStatus = "authenticated"; result = { ...auth, phase: "verifying" }; }
    else if (params.action === "select") { item.active = true; result = { activeAccountId: item.id, note: "New tasks only" }; }
    else if (params.action === "usage") { usage = true; item.quota = { state: "available", windows: [{ label: "Current session", usedPercent: 20, remainingPercent: 80, resetsAt: null }] }; result = { ...auth, kind: "usage", phase: "succeeded" }; }
    else result = auth;
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result }) });
  });
  await page.goto("/connections/#claude");
  await page.getByRole("button", { name: "登录 Claude Code", exact: true }).click();
  await expect(page.getByRole("link", { name: "打开官方授权页面" })).toHaveAttribute("href", /https:\/\/claude\.com\/cai\/oauth\/authorize\?code=true/);
  await page.getByLabel("官方授权返回码", { exact: true }).fill("dummy-return-code");
  await page.getByRole("button", { name: "提交返回码" }).click();
  await expect(page.getByText("已完成同步", { exact: true })).toBeVisible();
  await expect(page.getByLabel("官方授权返回码", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "关闭结果", exact: true }).click();
  await expect(page.getByText("已登录", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "设为默认", exact: true }).click();
  await expect(page.getByRole("button", { name: "当前默认", exact: true })).toBeVisible();
  await page.goto("/#claude");
  await page.getByRole("button", { name: "刷新官方额度", exact: true }).click();
  await expect(page.getByText("已完成同步", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "关闭结果", exact: true }).click();
  await expect(page.getByText("剩余 80%", { exact: true })).toBeVisible();
});

test("managed CLI login keeps actionable errors visible without exposing return codes", async ({ page }, testInfo) => {
  await mockConsoleApi(page);
  const accountId = "a".repeat(32);
  const sessionId = "b".repeat(32);
  let failed = false;
  const callback = "https://platform.claude.com/oauth/code/callback?code=example-private-code&state=example-private-state";
  await page.route("**/api/rpc", async route => {
    const body = route.request().postDataJSON();
    if (body.method !== "aiAccounts/action") { await route.fallback(); return; }
    const auth = { id: sessionId, accountId, kind: "login", phase: failed ? "failed" : "awaiting_code", reasonCode: failed ? "authorization_state_mismatch" : null,
      authorizationUrl: failed ? null : "https://claude.com/cai/oauth/authorize?code=true&client_id=test&state=test",
      message: failed ? "raw output with example-private-code and example-private-token" : "Official CLI is waiting", startedAt: 1, updatedAt: 1 };
    if (body.params.action === "input" && body.params.code === callback) {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, error: { code: -32000, message: "粘贴的是回调网址，不是授权返回码。请在官方授权页点击“复制授权码 / Copy code”，不要复制地址栏网址。" } }) });
      return;
    }
    let result: unknown = auth;
    if (["sync", "list"].includes(body.params.action)) result = { items: [], summary: { accounts: 0, authenticated: 0, quotaKnown: 0 } };
    if (body.params.action === "input") { failed = true; result = { ...auth, phase: "failed", reasonCode: "authorization_state_mismatch" }; }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result }) });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/connections/#claude");
  await page.getByRole("button", { name: "登录 Claude Code", exact: true }).click();
  await expect(page.getByText(/不要复制地址栏网址/)).toBeVisible();
  await page.getByLabel("官方授权返回码", { exact: true }).fill(callback);
  await page.getByRole("button", { name: "提交返回码", exact: true }).click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText("粘贴的是回调网址，不是授权返回码");
  await expect(page.getByLabel("官方授权返回码", { exact: true })).toHaveValue("");
  await page.getByLabel("官方授权返回码", { exact: true }).fill("example-private-code");
  await page.getByRole("button", { name: "提交返回码", exact: true }).click();
  await expect(page.getByRole("heading", { name: "授权会话不匹配", exact: true })).toBeVisible();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText("从当前 AImanager 窗口重新发起");
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText("authorization_state_mismatch");
  await expect(page.getByRole("dialog")).not.toContainText("example-private");
  await expect(page.getByLabel("官方授权返回码", { exact: true })).toHaveCount(0);
  const browserStorage = await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }));
  expect(browserStorage).not.toContain("example-private");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("auth-state-mismatch-mobile.png"), animations: "disabled" });
});

test("managed CLI login explains legacy generic failures without inventing a cause", async ({ page }, testInfo) => {
  await mockConsoleApi(page);
  await page.route("**/api/rpc", async route => {
    const body = route.request().postDataJSON();
    if (body.method !== "aiAccounts/action") { await route.fallback(); return; }
    const result = ["sync", "list"].includes(body.params.action) ? { items: [], summary: { accounts: 0, authenticated: 0, quotaKnown: 0 } }
      : { id: "c".repeat(32), accountId: "a".repeat(32), kind: "login", phase: "failed", reasonCode: "authorization_not_verified", authorizationUrl: null, message: "Sign-in was not verified; retry in this profile or check server network/CLI compatibility", startedAt: 1, updatedAt: 1 };
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result }) });
  });
  await page.goto("/connections/#claude");
  await page.getByRole("button", { name: "登录 Claude Code", exact: true }).click();
  await expect(page.getByRole("heading", { name: "登录尚未确认", exact: true })).toBeVisible();
  await expect(page.getByRole("dialog")).toContainText("未返回可识别的具体原因");
  await expect(page.getByRole("dialog")).toContainText("先同步登录状态");
  await expect(page.getByRole("dialog")).not.toContainText("Sign-in was not verified");
  await page.screenshot({ path: testInfo.outputPath("auth-unverified-desktop.png"), animations: "disabled" });
});

test("AI connection center distinguishes CLI installation from auth and probes private model catalogs", async ({ page }) => {
  const methods = await mockConsoleApi(page);
  await page.goto("/connections/");
  await expect(page).toHaveTitle("AImanager");
  await expect(page.getByText("AI 接入中心", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: /Claude Code/ }).click();
  await expect(page.locator('[data-slot="card-title"]').filter({ hasText: "Claude Code" })).toBeVisible();
  await expect(page.getByText("登录状态：尚未验证")).toHaveCount(0);
  await expect(page.getByLabel("账号备注", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "添加独立账号", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "检测连接", exact: true }).click();
  await expect(page.getByText("gemini-argon", { exact: true })).toHaveCount(0);
  await expect(page.getByText("未发送生成请求，不消耗模型额度。", { exact: true })).toBeVisible();
  await expect(page.getByText("上游报告可用账号：1", { exact: true })).toBeVisible();
  await expect(page.getByText("账号 2 · 冷却中 · 冷却 90s", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await expect(page.getByLabel("服务主机 API 地址")).toHaveValue("http://127.0.0.1:16969/v1");
  await expect(page.locator("input[type=password]")).toHaveCount(0);
  await page.screenshot({ path: "test-results/ai-connections.png", fullPage: true });
  expect(methods).toContain("aiConnections/list");
  expect(methods).toContain("aiConnections/probe");
});

test("saved logins synchronize across connection and account views without recreating profiles", async ({ page }) => {
  await mockConsoleApi(page);
  let signedIn = false;
  const actions: string[] = [];
  await page.route("**/api/rpc", async route => {
    const body = route.request().postDataJSON();
    if (body.method !== "aiAccounts/action") { await route.fallback(); return; }
    actions.push(body.params.action);
    const items = ["claude", "antigravity"].map((provider, index) => ({
      id: (index ? "c" : "a").repeat(32), provider, label: index ? "Antigravity 科研账号" : "Claude 个人会员", authStatus: signedIn ? "authenticated" : "unknown", active: false, checkedAt: Math.floor(Date.now() / 1000), quota: { state: "unknown", windows: [] },
    }));
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ jsonrpc: "2.0", id: body.id, result: { items, summary: { accounts: 2, authenticated: signedIn ? 2 : 0, quotaKnown: 0 } } }) });
  });
  await page.goto("/connections/#claude");
  await expect(page.getByText("待同步", { exact: true })).toHaveCount(1);
  signedIn = true;
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(page.getByText("已登录", { exact: true })).toHaveCount(1);
  await page.getByRole("tab", { name: /Antigravity/ }).click();
  await expect(page.getByText("已登录", { exact: true })).toHaveCount(1);
  await expect(page.getByLabel("账号备注", { exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: "查看账号额度", exact: true }).click();
  await page.getByRole("tab", { name: /Claude Code/ }).click();
  await expect(page.getByText("Claude 个人会员", { exact: true })).toBeVisible();
  await expect(page.getByText("额度尚未同步", { exact: true })).toBeVisible();
  await page.screenshot({ path: "test-results/ai-accounts-desktop.png", fullPage: true });
  await page.getByRole("tab", { name: /Antigravity/ }).click();
  await expect(page.getByText("Antigravity 科研账号", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator("aside")).toHaveCSS("width", "56px");
  await expect(page.getByRole("tab", { name: /Antigravity/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "test-results/ai-accounts-mobile.png", fullPage: true });
  expect(actions).not.toContain("connect");
  expect(actions).not.toContain("create");
});

test("the maintained account, analytics, session, and LabContext routes load through Web RPC", async ({ page }) => {
  const methods = await mockConsoleApi(page);

  await page.goto("/");
  await expect(page.getByText("账号与额度", { exact: true }).first()).toBeVisible();
  await expect(page.getByTitle("Research account")).toBeVisible();
  await expect(page.getByText("服务已连接", { exact: true })).toBeVisible();

  await page.getByRole("link", { name: "用量分析" }).click();
  await expect(page.getByRole("heading", { name: "用量分析", level: 1 })).toBeVisible();
  await expect(page.getByTestId("usage-chart")).toBeVisible();

  await page.getByRole("link", { name: "会话与恢复" }).click();
  await expect(page.getByText("Session Demo", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("本地会话", { exact: true })).toBeVisible();

  await page.getByRole("link", { name: "工作区" }).click();
  await expect(page.getByRole("heading", { name: "让 ChatGPT 读懂你的项目" })).toBeVisible();
  await expect(page.getByText("路径直读无需注册：")).toBeVisible();
  await expect(page.getByRole("button", { name: "本地电脑" }).first()).toBeDisabled();
  await expect(page.getByText("LabContext 连接需要处理", { exact: true })).toBeVisible();
  await expect(page.getByText("连接链路需要恢复", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "复制命令" })).toBeVisible();
  await expect(page.getByRole("button", { name: "一键修复" })).toBeVisible();
  await expect(page.getByText("Example Research", { exact: true })).toBeVisible();
  await expect(page.getByText("模型可见工具", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "添加工作区" }).click();
  await expect(page.getByRole("dialog")).toContainText("两步完成注册");
  await expect(page.getByRole("radio", { name: /本地电脑/ })).toBeDisabled();
  await page.getByRole("button", { name: "取消" }).click();

  for (const method of [
    "appSettings/get",
    "initialize",
    "account/list",
    "account/usage/list",
    "account/analytics/pricingRefresh",
    "account/analytics/read",
    "codexProfile/get",
    "sessionCatalog/list",
    "labcontext/overview",
    "labcontext/getResearchMap",
  ]) {
    expect(methods).toContain(method);
  }
});

test("the Web console unlocks local workspaces when the loopback Router is ready", async ({ page }) => {
  const connectionRequests: string[] = [];
  page.on("request", request => {
    if (new URL(request.url()).pathname.startsWith("/api/connections")) connectionRequests.push(request.url());
  });
  await mockConsoleApi(page, true);
  await page.goto("/labcontext/");

  await expect(page.getByText("LabContext 本机链路已就绪")).toBeVisible();
  const localButton = page.getByRole("button", { name: "本地电脑" }).first();
  await expect(localButton).toBeEnabled();
  await localButton.click();
  await expect(page.getByText("当前设备", { exact: true })).toBeVisible();
  await expect(page.getByText("Example Research", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "换号准备", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "验证 ChatGPT 调用", exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: "添加工作区" }).click();
  await page.getByRole("radio", { name: /本地电脑/ }).click();
  const root = page.getByLabel("本地项目目录");
  await expect(root).toBeEditable();
  await root.fill("/Users/research/project");
  expect(connectionRequests).toEqual([]);
});

test("the connection center runs one-click recovery and reports an exact safe failure", async ({ page }) => {
  await mockConsoleApi(page, true, "failed");
  await page.goto("/labcontext/");

  await expect(page.getByText("LabContext 当前为降级可用")).toBeVisible();
  await page.getByRole("button", { name: "一键修复" }).click();
  await expect(page.getByText("服务器反向转发端口 17987 已被占用，无法安全自动接管")).toBeVisible();
  await expect(page.getByText("原因代码：ssh_reverse_port_in_use")).toBeVisible();
  await expect(page.getByText("停止服务器上的旧 LabContext SSH 会话后再次修复。")).toBeVisible();
  await expect(page.getByRole("button", { name: "再次修复" })).toBeVisible();
});

test("AI connections owns identity changes; usage stays focused on quotas without model catalogs", async ({ page }) => {
  const methods = await mockConsoleApi(page);
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByTitle("Research account")).toBeVisible();
  await expect(page.getByRole("button", { name: "添加 Codex 账号" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "切换到此账号" })).toHaveCount(0);
  await page.getByRole("tab", { name: /Claude Code/ }).click();
  await expect(page.getByText("剩余 82%", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Example model", { exact: true })).toHaveCount(0);
  expect(methods).not.toContain("apikey/modelCatalogList");
  await expect(page.getByRole("button", { name: /网页登录|登录其他|设为默认/ })).toHaveCount(0);
  await page.getByRole("link", { name: "AI 接入", exact: true }).click();
  await expect(page.getByRole("heading", { name: "AI 接入中心" })).toBeVisible();
  await expect(page.getByRole("button", { name: "添加 Codex 账号" })).toBeVisible();
  await expect(page.getByRole("button", { name: /刷新.*额度/ })).toHaveCount(0);
  await page.getByRole("tab", { name: /Claude Code/ }).click();
  await expect(page.getByRole("button", { name: "登录其他 Claude Code 账号" })).toBeVisible();
  await expect(page.getByText("剩余 82%", { exact: true }).first()).toHaveCount(0);
  await page.getByRole("tab", { name: /Antigravity/ }).click();
  await expect(page.getByRole("button", { name: "登录其他 Antigravity 账号" })).toBeVisible();
  await page.setViewportSize({width:390,height:844});
  await expect(page.getByRole("heading", { name: "AI 接入中心" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(errors).toEqual([]);
  expect(methods).toContain("aiAccounts/action");
});


test("active accounts lead, web quota preserves unknowns, and CLI analytics switches independently", async ({ page }) => {
  const methods = await mockConsoleApi(page);
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByTestId("codex-quota-card").first()).toContainText("Research account");
  await expect(page.getByTestId("codex-quota-card").first()).toHaveAttribute("data-active-account", "true");
  const pool = page.getByRole("region", {name:"网页账号池额度"});
  await expect(pool).toContainText("剩余 82%");
  await expect(pool).toContainText("剩余未知");
  await expect(page.getByText("Codex 模型目录", {exact:true})).toHaveCount(0);
  await page.getByRole("link", {name:"用量分析",exact:true}).click();
  await page.getByRole("tab", {name:/Claude Code/}).click();
  await expect(page.getByRole("heading", {name:"Claude Code 使用概览"})).toBeVisible();
  await expect(page.getByTestId("usage-chart")).toBeVisible();
  await expect(page.getByText("模型回复次数", {exact:true})).toBeVisible();
  await expect(page.getByText("参考金额 · USD", {exact:true})).toHaveCount(0);
  await page.getByRole("tab", {name:/Antigravity/}).click();
  await expect(page.getByRole("heading", {name:"Antigravity 使用概览"})).toBeVisible();
  await expect(page.getByTestId("quota-history-chart")).toBeVisible();
  await expect(page.getByTestId("usage-chart")).toHaveCount(0);
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(methods).toContain("aiConnections/quota");
  expect(errors).toEqual([]);
});


test("sessions switch across three CLIs with pinned recovery and honest empty state", async ({ page }) => {
  await mockConsoleApi(page);
  await page.goto("/sessions/");
  await expect(page.getByText("Session Demo", { exact: true }).first()).toBeVisible();
  await page.getByRole("tab", { name: "Claude Code" }).click();
  await expect(page.getByText("Claude session demo", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Claude Code 会话账号" })).toHaveValue("claude-a");
  await expect(page.locator("code").filter({hasText:"--resume"})).toContainText("--account-id claude-a");
  await page.getByRole("textbox", {name:"Claude Code 搜索会话"}).fill("no-match");
  await page.getByRole("button", {name:"搜索会话",exact:true}).click();
  await expect(page.getByText("没有匹配的会话，请尝试其他关键词。")).toBeVisible();
  await page.getByRole("tab", { name: "Antigravity" }).click();
  await expect(page.getByText("此账号暂无已保存的会话。")).toBeVisible();
  await expect(page.locator("code").filter({hasText:"--continue"})).toContainText("--account-id agy-a");
  await expect(page.locator("body")).not.toContainText("CodexManager");
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test("README screenshots show current screens using only isolated demo data", async ({ page }) => {
  await mockConsoleApi(page, true);
  await page.setViewportSize({ width: 1440, height: 1240 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.getByTestId("codex-quota-card").first()).toContainText("Research account");
  await expect(page.getByRole("region", { name: "网页账号池额度" })).toContainText("剩余 82%");
  await page.getByRole("tab", { name: /Claude Code/ }).click();
  await expect(page.getByRole("region", { name: "官方账号额度" })).toContainText("剩余 82%");
  await page.screenshot({ path: "test-results/readme-accounts.png", fullPage: true, animations: "disabled" });

  await page.goto("/connections/#claude");
  await expect(page.getByText("Claude personal", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "当前默认", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "添加独立账号", exact: true })).toHaveCount(0);
  await page.screenshot({ path: "test-results/readme-connections.png", fullPage: true, animations: "disabled" });

  await page.goto("/analytics/");
  await page.getByRole("tab", { name: /Claude Code/ }).click();
  await expect(page.getByRole("heading", { name: "Claude Code 使用概览" })).toBeVisible();
  await expect(page.getByTestId("usage-chart")).toBeVisible();
  await page.screenshot({ path: "test-results/readme-analytics.png", fullPage: true, animations: "disabled" });

  await page.goto("/labcontext/");
  await expect(page.getByText("LabContext 本机链路已就绪")).toBeVisible();
  await expect(page.getByText("Example Research", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "收起", exact: true }).click();
  await page.screenshot({ path: "test-results/readme-workspaces.png", fullPage: true, animations: "disabled" });
});
