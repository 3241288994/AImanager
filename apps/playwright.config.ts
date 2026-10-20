import { defineConfig } from "@playwright/test";

const PORT = 3200;
const LOCAL_TEST_HOST = "localhost";

const noProxyHosts = ["localhost", "127.0.0.1", "::1"];
const noProxy = [process.env.NO_PROXY, process.env.no_proxy, ...noProxyHosts]
  .filter(Boolean)
  .join(",");

process.env.NO_PROXY = noProxy;
process.env.no_proxy = noProxy;

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  fullyParallel: false,
  use: {
    launchOptions: process.env.AIMANAGER_TEST_BROWSER ? { executablePath: process.env.AIMANAGER_TEST_BROWSER } : {},
    baseURL: `http://${LOCAL_TEST_HOST}:${PORT}`,
    trace: "on-first-retry",
    video: "retain-on-failure",
  },
  webServer: {
    command: "corepack pnpm@10.30.3 run build:desktop && node tests/support/static-server.mjs",
    url: `http://${LOCAL_TEST_HOST}:${PORT}`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      NO_PROXY: noProxy,
      PORT: String(PORT),
      no_proxy: noProxy,
    },
  },
});
