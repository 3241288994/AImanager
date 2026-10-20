import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const appsRoot = path.resolve(import.meta.dirname, "..");
const repoRoot = path.resolve(appsRoot, "..");

async function routeDirectories(root, relative = "") {
  const entries = await fs.readdir(path.join(root, relative), { withFileTypes: true });
  const routes = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const child = path.join(relative, entry.name);
    const files = await fs.readdir(path.join(root, child));
    if (files.includes("page.tsx")) routes.push(child.replaceAll(path.sep, "/"));
    routes.push(...(await routeDirectories(root, child)));
  }
  return routes;
}

test("the public console exposes only its maintained top-level routes", async () => {
  const routes = (await routeDirectories(path.join(appsRoot, "src", "app"))).sort();
  assert.deepEqual(routes, ["analytics", "connections", "labcontext", "sessions"]);

  const rootPage = path.join(appsRoot, "src", "app", "page.tsx");
  await fs.access(rootPage);
  const sidebar = await fs.readFile(
    path.join(appsRoot, "src", "components", "layout", "sidebar.tsx"),
    "utf8",
  );
  for (const href of ['href: "/"', 'href: "/connections"', 'href: "/analytics"', 'href: "/sessions"', 'href: "/labcontext"']) {
    assert.match(sidebar, new RegExp(href.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
});

test("public source has no bundled personal author-content endpoint or default promotions", async () => {
  const files = [
    path.join(appsRoot, "src", "lib", "runtime", "runtime-capabilities.ts"),
    path.join(appsRoot, "src", "app", "labcontext", "page.tsx"),
    path.join(appsRoot, "src-tauri", "tauri.conf.json"),
    path.join(repoRoot, "crates", "service", "src", "app_settings", "api", "author_links.rs"),
  ];
  const source = (await Promise.all(files.map((file) => fs.readFile(file, "utf8")))).join("\n");
  assert.doesNotMatch(
    source,
    /author\.qxnm\.top|visioncoder|xingsiyan|racknerd|luoyingfeng|\/ldy\//i,
  );
});

test("the public plugin template has no user-specific registered connection", async () => {
  const pluginRoot = path.join(repoRoot, "plugins", "codexmanager-connector");
  const manifest = JSON.parse(
    await fs.readFile(path.join(pluginRoot, ".codex-plugin", "plugin.json"), "utf8"),
  );
  assert.equal(manifest.name, "codexmanager-connector");
  assert.equal("apps" in manifest, false);
  await assert.rejects(fs.access(path.join(pluginRoot, ".app.json")));
});
