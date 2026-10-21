import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test, { after } from "node:test";
import { pathToFileURL } from "node:url";
import ts from "../node_modules/typescript/lib/typescript.js";

const source = await fs.readFile(new URL("../src/lib/cli-auth-feedback.ts", import.meta.url), "utf8");
const directory = await fs.mkdtemp(path.join(os.tmpdir(), "aimanager-auth-feedback-"));
after(() => fs.rm(directory, { recursive: true, force: true }));
const file = path.join(directory, "feedback.mjs");
await fs.writeFile(file, ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
}).outputText);
const { cliAuthFeedback } = await import(pathToFileURL(file).href);

test("login failures show distinct causes and concrete next steps", () => {
  for (const reasonCode of ["authorization_code_invalid", "authorization_code_expired", "authorization_code_used", "authorization_state_mismatch", "authorization_rejected", "authorization_denied", "session_expired", "network_unavailable", "auth_service_unavailable", "credential_store_unavailable", "cli_incompatible", "auth_status_unavailable", "authorization_not_verified"]) {
    const result = cliAuthFeedback({ kind: "login", phase: "failed", reasonCode });
    assert.equal(result.reasonCode, reasonCode);
    assert.ok(result.title.length > 0);
    assert.ok(result.description.length > 0);
    assert.ok(result.nextStep.length > 0);
  }
  assert.match(cliAuthFeedback({ kind: "login", phase: "failed", reasonCode: "network_unavailable" }).nextStep, /Service/);
  assert.match(cliAuthFeedback({ kind: "login", phase: "failed", reasonCode: "authorization_rejected" }).description, /不能确定/);
});

test("legacy and unknown reasons do not expose server text or invent a cause", () => {
  for (const reasonCode of [undefined, null, "example-private-code", "constructor", "__proto__"]) {
    const result = cliAuthFeedback({ kind: "login", phase: "failed", reasonCode, message: "example-private-token" });
    assert.equal(result.reasonCode, "authorization_not_verified");
    assert.doesNotMatch(JSON.stringify(result), /example-private/);
    assert.match(result.description, /未返回可识别的具体原因/);
  }
  assert.equal(cliAuthFeedback({ kind: "login", phase: "expired" }).reasonCode, "session_expired");
  assert.equal(cliAuthFeedback({ kind: "login", phase: "expired", reasonCode: "network_unavailable" }).reasonCode, "session_expired");
});

test("successful, cancelled and quota sessions never inherit login failures", () => {
  assert.equal(cliAuthFeedback(), null);
  for (const phase of ["succeeded", "cancelled", "awaiting_code", "verifying"]) {
    assert.equal(cliAuthFeedback({ kind: "login", phase }), null);
  }
  assert.equal(cliAuthFeedback({ kind: "login", phase: "succeeded", reasonCode: "authorization_code_invalid" }), null);
  assert.equal(cliAuthFeedback({ kind: "usage", phase: "failed", reasonCode: "network_unavailable" }), null);
  assert.equal(cliAuthFeedback({ kind: "login", phase: "awaiting_code", reasonCode: "authorization_code_invalid" }).title, "返回码无效");
});
