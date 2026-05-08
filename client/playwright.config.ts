import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright e2e config for ScholarPilot client.
 *
 * Strategy（option B）：直接对 Vite dev server 跑测试，不经过 Tauri。
 * - Vite dev server 起在 5173（vite.config.ts 写死 strictPort）
 * - 通过 init script + route mock 拦截：
 *   - @tauri-apps/api/core invoke（secureStorage / fs / DB）
 *   - axios 走 https://api.scholarpilot.top → 全部 fulfill 假 JSON
 * - 真 Tauri (.msi) e2e 留给 user 手测，配置见 e2e/README.md
 *
 * 环境变量：
 *   E2E_BASE_URL — 默认 http://localhost:5173；Tauri 模式下传 webview URL
 *   E2E_KEEP_OPEN — '1' 保留浏览器（debug 用）
 */
export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.ts',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: process.env.CI ? [['github'], ['list']] : [['list']],
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },

  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
    // 客户端 UI 是中文，确保浏览器 locale 一致
    locale: 'zh-CN',
  },

  projects: [
    {
      name: 'chromium-desktop',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
      },
    },
  ],

  webServer: process.env.E2E_NO_SERVER
    ? undefined
    : {
        command: 'npm run dev',
        port: 5173,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
        stdout: 'ignore',
        stderr: 'pipe',
      },
})
