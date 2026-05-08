# Client CI

GitHub Actions 三端打包配置在 `.github/workflows/client-build.yml`。

- 触发：push to main 改了 `client/**` 或 `.github/workflows/client-build.yml` / PR / 手动 dispatch。
- 平台：Windows / macOS / Ubuntu 22.04 三端 matrix。
- Step: setup-node 20 + Rust stable + Linux deps (libwebkit2gtk + libsecret) + `npm install` + `npm run tauri:build`。
- 产物：`client/src-tauri/target/release/bundle/**` 上传 7 天。

## 历史踩坑

| 日期 | 问题 | 修复 commit |
|---|---|---|
| 2026-04-30 | `npm ci` 跨平台 lock 缺 native deps（@emnapi/core / esbuild Linux x64） | `0a7684c`（改用 `npm install --no-audit --no-fund`）|
