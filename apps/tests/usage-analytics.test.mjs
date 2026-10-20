import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";
import ts from "../node_modules/typescript/lib/typescript.js";

const source = await fs.readFile(new URL("../src/lib/usage-analytics.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 } }).outputText;
const { sumMetrics, cacheRatio, analyticsCsv, offsetDate, valuation, referenceAmount } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const day = (date, cached, uncached) => ({ date, capturedAt: 1, totals: { credits: 0, turns: null, cachedInputTokens: cached, uncachedInputTokens: uncached, outputTokens: 0, totalTokens: cached + uncached } });

test("cache ratio uses weighted token totals and unknowns remain missing", () => {
  const totals = sumMetrics([day("2026-01-01", 10, 0), day("2026-01-02", 0, 90)]);
  assert.equal(cacheRatio(totals), 0.1);
  assert.equal(totals.credits, 0);
  assert.equal(totals.turns, null);
  assert.equal(cacheRatio(sumMetrics([])), null);
  assert.equal(cacheRatio(day("2026-01-01", 0, 0).totals), null);
});

test("official reference valuation preserves unknowns, manual zero and cached price provenance", () => {
  const report = { source: "chatgpt-wham", days: [day("2026-01-01", 10, 90)], usdPerCredit: null,
    pricing: { error: "offline", snapshot: { usdPerCredit: 0.04, fetchedAt: 1, apiSource: "official-api", creditSource: "official-credits" } } };
  report.days[0].totals.credits = 12.5;
  assert.equal(referenceAmount(12.5, valuation(report).rate), 0.5);
  assert.equal(referenceAmount(null, 0.04), null);
  assert.equal(referenceAmount(1, null), null);
  assert.equal(valuation({ ...report, usdPerCredit: 0 }).rate, 0);
  assert.equal(valuation({ ...report, usdPerCredit: 0 }).method, "manual-credit-rate");
  assert.equal(valuation(undefined).rate, null);
  const csv = analyticsCsv(report);
  assert.match(csv, /"0.5"/);
  assert.match(csv, /"official-tables-derived-reference","0.04","1970-01-01T00:00:01.000Z","official-api","official-credits","true"/);
});
test("CSV retains zeros, missing values, estimates and source without auth", () => {
  const csv = analyticsCsv({ source: "chatgpt-wham", days: [day("2026-01-01", 10, 90)], usdPerCredit: null });
  assert.ok(csv.startsWith("\uFEFF"));
  assert.match(csv, /"2026-01-01","0","90","10","0","100","","0.1",""/);
  assert.equal(offsetDate("2026-03-01", -1), "2026-02-28");
});

const orderSource = await fs.readFile(new URL("../src/lib/account-order.ts", import.meta.url), "utf8");
const orderCompiled = ts.transpileModule(orderSource, { compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 } }).outputText;
const { activeFirst } = await import(`data:text/javascript;base64,${Buffer.from(orderCompiled).toString("base64")}`);
test("active accounts sort first without mutating cached data or backup order", () => {
  const input = [{id:"backup-a", active:false}, {id:"current", active:true}, {id:"backup-b", active:false}];
  assert.deepEqual(activeFirst(input, item => item.active).map(item => item.id), ["current", "backup-a", "backup-b"]);
  assert.equal(input[0].id, "backup-a");
});
