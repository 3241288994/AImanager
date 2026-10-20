import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";
import ts from "../node_modules/typescript/lib/typescript.js";

const appsRoot = path.resolve(import.meta.dirname, "..");
const sourcePath = path.join(appsRoot, "src", "lib", "api", "transport-web-commands.ts");
const commandModuleNames = [
  "account",
  "ai-connections",
  "codex-profile",
  "labcontext",
  "login",
  "misc",
  "session-catalog",
  "shared",
];

function rewriteImports(outputText) {
  return commandModuleNames.reduce(
    (result, name) =>
      result.replaceAll(
        `./transport-web-commands/${name}`,
        `./transport-web-commands/${name}.js`,
      ).replaceAll(`./${name}`, `./${name}.js`),
    outputText,
  );
}

async function writeCompiledModule(inputPath, outputPath) {
  const source = await fs.readFile(inputPath, "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: inputPath,
  });
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, rewriteImports(compiled.outputText), "utf8");
}

async function loadTransportWebCommandsModule() {
  const tempDir = await fs.mkdtemp(
    path.join(os.tmpdir(), "codexmanager-transport-web-commands-"),
  );
  await writeCompiledModule(
    sourcePath,
    path.join(tempDir, "transport-web-commands.mjs"),
  );
  await Promise.all(
    commandModuleNames.map((name) =>
      writeCompiledModule(
        path.join(appsRoot, "src", "lib", "api", "transport-web-commands", `${name}.ts`),
        path.join(tempDir, "transport-web-commands", `${name}.js`),
      ),
    ),
  );
  return import(pathToFileURL(path.join(tempDir, "transport-web-commands.mjs")).href);
}

const transportWebCommands = await loadTransportWebCommandsModule();
const commandMap = transportWebCommands.createWebCommandMap();

test("current account and session commands have Web RPC mappings", () => {
  assert.deepEqual(commandMap.service_initialize, { rpcMethod: "initialize" });
  assert.deepEqual(commandMap.service_account_list, { rpcMethod: "account/list" });
  assert.deepEqual(commandMap.service_usage_list, { rpcMethod: "account/usage/list" });
  assert.deepEqual(commandMap.service_usage_analytics_read, {
    rpcMethod: "account/analytics/read",
  });
  assert.deepEqual(commandMap.service_usage_analytics_refresh, {
    rpcMethod: "account/analytics/refresh",
  });
  assert.deepEqual(commandMap.service_usage_analytics_set_rate, {
    rpcMethod: "account/analytics/setRate",
  });
  assert.deepEqual(commandMap.service_usage_analytics_pricing_refresh, {
    rpcMethod: "account/analytics/pricingRefresh",
  });
  assert.deepEqual(commandMap.service_session_catalog_list, {
    rpcMethod: "sessionCatalog/list",
  });
  assert.deepEqual(commandMap.service_session_catalog_repair_provider_index, {
    rpcMethod: "sessionCatalog/repairProviderIndex",
  });
});

test("login mapping preserves the selected login type and disables remote browser opening", () => {
  const descriptor = commandMap.service_login_start;
  assert.ok(descriptor.mapParams);
  assert.deepEqual(descriptor.mapParams({ loginType: "chatgpt" }), {
    loginType: "chatgpt",
    type: "chatgpt",
    openBrowser: false,
  });
});

test("all maintained LabContext operations map to the typed service RPC surface", () => {
  const expected = {
    service_labcontext_overview: "labcontext/overview",
    service_labcontext_set_default_workspace: "labcontext/setDefaultWorkspace",
    service_labcontext_refresh_workspace: "labcontext/refreshWorkspace",
    service_labcontext_test_tool: "labcontext/testTool",
    service_labcontext_set_tool_policy: "labcontext/setToolPolicy",
    service_labcontext_upsert_workspace: "labcontext/upsertWorkspace",
    service_labcontext_delete_workspace: "labcontext/deleteWorkspace",
    service_labcontext_set_workspace_overview: "labcontext/setWorkspaceOverview",
    service_labcontext_generate_workspace_overview: "labcontext/generateWorkspaceOverview",
    service_labcontext_set_worker_config: "labcontext/setWorkerConfig",
    service_labcontext_get_research_map: "labcontext/getResearchMap",
    service_labcontext_initialize_research_map: "labcontext/initializeResearchMap",
    service_labcontext_save_research_map_layout: "labcontext/saveResearchMapLayout",
    service_labcontext_apply_research_map_patch: "labcontext/applyResearchMapPatch",
    service_labcontext_review_research_map: "labcontext/reviewResearchMap",
    service_labcontext_research_map_proposal_action: "labcontext/researchMapProposalAction",
  };

  for (const [command, rpcMethod] of Object.entries(expected)) {
    assert.equal(commandMap[command]?.rpcMethod, rpcMethod, command);
  }
});

test("removed product surfaces are not accidentally exposed through the Web command map", () => {
  assert.equal(commandMap.service_aggregate_api_list, undefined);
  assert.equal(commandMap.service_plugin_install, undefined);
  assert.equal(commandMap.service_apikey_create, undefined);
});

test("model catalog and managed account requests retain their Web RPC contract", () => {
 assert.equal(commandMap.service_model_catalog_list.rpcMethod, "apikey/modelCatalogList");
 assert.equal(commandMap.service_ai_accounts_action.rpcMethod, "aiAccounts/action");
 assert.equal(commandMap.service_ai_connections_quota.rpcMethod, "aiConnections/quota");
 assert.deepEqual(commandMap.service_ai_accounts_action.mapParams({ params: { action: "models", accountId: "account" } }), { action: "models", accountId: "account" });
});
