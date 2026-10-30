import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test, { after } from "node:test";
import { pathToFileURL } from "node:url";
import ts from "../node_modules/typescript/lib/typescript.js";

const source = await fs.readFile(new URL("../src/lib/codex-login-activation.ts", import.meta.url), "utf8");
const dir = await fs.mkdtemp(path.join(os.tmpdir(), "aimanager-login-activation-"));
after(() => fs.rm(dir, { recursive: true, force: true }));
const file = path.join(dir, "activation.mjs");
await fs.writeFile(file, ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022 } }).outputText);
const { activateCodexLogin } = await import(pathToFileURL(file).href);
const methodsFile = path.join(dir, "methods.mjs");
await fs.writeFile(methodsFile, ts.transpileModule(await fs.readFile(new URL("../src/lib/codex-login-method.ts", import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.ES2022 } }).outputText);
const {DEFAULT_CODEX_LOGIN_METHOD, codexLoginOptions, validateCodexLoginStart, codexLoginError} = await import(pathToFileURL(methodsFile).href);

test("device login is the default and waits for the backend's full fifteen-minute window", () => {
  assert.equal(DEFAULT_CODEX_LOGIN_METHOD, "device");
  assert.deepEqual(codexLoginOptions("device"), {loginType:"chatgptDeviceCode", openBrowser:false, waitMs:900000});
  assert.deepEqual(codexLoginOptions("browser"), {loginType:"chatgpt", openBrowser:false, waitMs:300000});
  const result = {loginId:"fixture", verificationUrl:"https://auth.openai.com/codex/device", userCode:"TEST-ONLY"};
  assert.equal(validateCodexLoginStart(result, "device"), result.verificationUrl);
  assert.throws(() => validateCodexLoginStart({...result,userCode:null}, "device"), /缺少设备码/);
  assert.throws(() => validateCodexLoginStart({...result,verificationUrl:"http://localhost:1455/auth/callback"}, "device"), /HTTPS/);
});

test("device sign-in errors distinguish verification, unavailable, expiry and connectivity without exposing upstream content", () => {
  assert.match(codexLoginError("Cloudflare <!DOCTYPE html>secret"), /安全验证页/);
  assert.match(codexLoginError("device code login is not enabled for this Codex server"), /安全设置/);
  assert.match(codexLoginError("device auth timed out after 15 minutes"), /已过期/);
  assert.match(codexLoginError("device code request failed with status 403 Forbidden"), /不能判定具体原因/);
  assert.match(codexLoginError("network error sending request"), /服务主机/);
  assert.match(codexLoginError("access_denied"), /拒绝或取消/);
  assert.match(codexLoginError("HTTP 429"), /过于频繁/);
  assert.doesNotMatch(codexLoginError("<html>https://secret.invalid?code=SECRET</html>"), /SECRET|<html>/);
});

test("activates the account from this exact completed login", async () => {
  const result = await activateCodexLogin({ status: "success", accountId: "new" }, async id => {
    assert.equal(id, "new"); return { identityConsistent: true, selectedAccountId: id };
  });
  assert.equal(result.selectedAccountId, "new");
});
test("old server and incomplete login cannot activate a global current account", async () => {
  for (const login of [{ status: "success" }, { status: "pending", accountId: "new" }]) {
    await assert.rejects(activateCodexLogin(login, async () => assert.fail("must not switch")), /本次登录/);
  }
});
test("sync failure or wrong identity is not reported as login success", async () => {
  const login = { status: "success", accountId: "new" };
  await assert.rejects(activateCodexLogin(login, async () => { throw new Error("read-only profile"); }), /read-only/);
  await assert.rejects(activateCodexLogin(login, async () => ({ identityConsistent: true, selectedAccountId: "other" })), /校验未通过/);
  await assert.rejects(activateCodexLogin(login, async () => ({ identityConsistent: false, selectedAccountId: "new" })), /校验未通过/);
});

test("account activation has a bounded timeout and is not automatically replayed", async () => {
  const client = await fs.readFile(new URL("../src/lib/api/codex-profile-client.ts", import.meta.url), "utf8");
  assert.match(client, /service_codex_profile_apply_direct_account[\s\S]*?timeoutMs: 90_000, retries: 0/);
  const loginClient = await fs.readFile(new URL("../src/lib/api/account-client.ts", import.meta.url), "utf8");
  assert.match(loginClient, /service_login_start[\s\S]*?timeoutMs: 90_000, retries: 0/);
});

test("queued authorization keeps the old selection and does not pretend to be activated", async () => {
  const queued = {identityConsistent: true, selectedAccountId: "old", accountSwitch: {state: "pending", accountId: "new"}};
  assert.equal(await activateCodexLogin({status: "success", accountId: "new"}, async () => queued), queued);
  for (const state of ["failed", "attention"]) {
    await assert.rejects(activateCodexLogin({status: "success", accountId: "new"}, async () => ({...queued, accountSwitch: {state, accountId: "new"}})), /切换尚未完成/);
  }
});

test("queued switch feedback distinguishes blocked, changed, expired and unverified states", async () => {
  const text = await fs.readFile(new URL("../src/lib/codex-switch-feedback.ts", import.meta.url), "utf8");
  const file = path.join(dir, "feedback.mjs");
  await fs.writeFile(file, ts.transpileModule(text, {compilerOptions: {module: ts.ModuleKind.ES2022}}).outputText);
  const {codexSwitchMessage} = await import(pathToFileURL(file).href);
  assert.equal(codexSwitchMessage({state: "completed"}), null);
  assert.match(codexSwitchMessage({state: "pending", reason: "sessions_loaded"}), /2 秒.*空闲会话无需退出/);
  assert.match(codexSwitchMessage({state: "pending", reason: "background_unreachable"}), /尚未替换/);
  assert.match(codexSwitchMessage({state: "failed", reason: "expired"}), /24 小时/);
  assert.match(codexSwitchMessage({state: "failed", reason: "profile_changed"}), /其他入口/);
  assert.match(codexSwitchMessage({state: "attention"}), /尚未核实/);
});

test("current Free entitlement overrides a historical Pro billing label without guessing on missing data", async () => {
  const file = path.join(dir,"plan.mjs");
  await fs.writeFile(file,ts.transpileModule(await fs.readFile(new URL("../src/lib/codex-plan-display.ts",import.meta.url),"utf8"),{compilerOptions:{module:ts.ModuleKind.ES2022}}).outputText);
  const {codexPlanDisplay}=await import(pathToFileURL(file).href);
  assert.equal(codexPlanDisplay({planType:"free",subscriptionPlan:"pro",hasSubscription:false}).label,"FREE");
  assert.equal(codexPlanDisplay({planType:"free",subscriptionPlan:"pro",hasSubscription:true}).free,true);
  assert.equal(codexPlanDisplay({planType:"pro",subscriptionPlan:"plus",hasSubscription:false}).label,"PRO");
  assert.equal(codexPlanDisplay({planType:null,subscriptionPlan:"pro",hasSubscription:true,subscriptionExpiresAt:1},100).free,false);
  assert.equal(codexPlanDisplay({planType:null,subscriptionPlan:null,hasSubscription:false}).label,"暂无套餐数据");
  const pro={planType:"pro",subscriptionPlan:"pro",hasSubscription:true,planMonthlyUsd:200,planPriceSource:"user_confirmed"};
  assert.equal(codexPlanDisplay(pro).label,"Pro 200$");
  assert.equal(codexPlanDisplay({...pro,planMonthlyUsd:100}).label,"Pro 100$");
  assert.equal(codexPlanDisplay({...pro,planMonthlyUsd:999}).label,"PRO");
  assert.equal(codexPlanDisplay({...pro,planPriceSource:null}).label,"PRO");
  assert.equal(codexPlanDisplay({...pro,planType:"free"}).label,"FREE");
  assert.equal(codexPlanDisplay({...pro,subscriptionExpiresAt:1},100).label,"PRO");
});

test("device status and login use typed transport; heartbeat is deliberately not browser mapped", async () => {
  const client=await fs.readFile(new URL("../src/lib/api/codex-devices-client.ts",import.meta.url),"utf8");
  const commands=await fs.readFile(new URL("../src/lib/api/transport-web-commands/codex-profile.ts",import.meta.url),"utf8");
  assert.match(client,/service_codex_devices_login/);
  assert.match(commands,/codexDevices\/status/);
  assert.match(commands,/codexDevices\/login/);
  assert.doesNotMatch(commands,/codexDevices\/heartbeat/);
});
