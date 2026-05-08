# ScholarPilot Desktop Client

Tauri 2 + Vue 3 桌面客户端。Web frontend 已冻结（2026-05-06），所有新功能在这里落地。

[![Client Build](https://github.com/sstar16/scholarpilot/actions/workflows/client-build.yml/badge.svg?branch=main)](https://github.com/sstar16/scholarpilot/actions/workflows/client-build.yml)
[![CI](https://github.com/sstar16/scholarpilot/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/sstar16/scholarpilot/actions/workflows/ci.yml)

完整架构（M1 壳 / M2 本地数据层 / M3 BYOK）见 [`docs/architecture/06-desktop-client.md`](../docs/architecture/06-desktop-client.md)。

## 快速开始

```bash
cd client
npm install                # 首次 ~80MB
npm run tauri:dev          # 起 Tauri 窗口（首次 cargo 编译 5-10 分钟）
```

后端：默认连 `https://api.scholarpilot.top`（HK sp-api backend）。本地 dev 改 `client/.env`：

```bash
VITE_API_BASE_URL=http://localhost:8000   # 连本地 backend
VITE_CLIENT_TYPE=desktop
```

## 测试

```bash
# Vue/TS 单测（vitest，~600 case）
npm test

# Vue 类型检查（vue-tsc，0 error 期望）
npx vue-tsc --noEmit

# Playwright e2e（chromium，~20 case，~1 min）
# 直接对 Vite dev server 跑，不经过 Tauri；详见 e2e/README.md
npx playwright test

# Rust 类型检查 + 测试
cd src-tauri
cargo check --all-targets
cargo test --all-targets
```

CI 详见 [`CI.md`](./CI.md)；workflow 文件：

| Workflow | 触发 | 用途 |
|---|---|---|
| [`ci.yml`](../.github/workflows/ci.yml) | PR + main push | 单测 + 类型检查 + e2e（路径过滤，并行） |
| [`client-build.yml`](../.github/workflows/client-build.yml) | client/** push to main | 跨平台 Tauri build artifact（7 天） |
| [`release.yml`](../.github/workflows/release.yml) | tag `client-v*.*.*` | 发 Release，带 .msi/.dmg/.deb |

## 打包发布

### 本地打包（单平台）

```bash
npm run tauri:build
# 产物在 src-tauri/target/release/bundle/{msi,dmg,deb,appimage}/
```

### CI 自动发布（推荐）

```bash
# 1. 升 src-tauri/tauri.conf.json 的 version
# 2. 升 src-tauri/Cargo.toml 的 version
# 3. 升 package.json 的 version
# 4. tag + push
git tag client-v0.2.0
git push origin client-v0.2.0
```

`release.yml` 会跨 Windows/macOS/Linux 三平台并行 build → 自动建 GitHub Release（draft）→ 上传 .msi/.dmg/.deb/.AppImage。

## 项目结构

```
client/
├── src/                # Vue 3 源码
│   ├── views/          # 路由页面（chat / collab / round / graph 等）
│   ├── components/     # UI 组件
│   ├── stores/         # Pinia
│   ├── services/       # API client / sync orchestrator / memory
│   ├── workers/        # Comlink web worker
│   └── plugins/        # Element Plus 国际化等
├── src-tauri/          # Rust 后端
│   ├── src/            # commands / fs sandbox / pdf fetcher / ...
│   ├── Cargo.toml
│   └── tauri.conf.json
├── e2e/                # Playwright 用例（route mock + tauri invoke mock）
├── tests/              # vitest 单测 fixture
├── playwright.config.ts
├── vitest.config.ts
└── package.json
```

## 关键约定

- **API 调用**：统一走 `src/api/client.ts` 具名导出（authApi / projectApi / searchApi 等），不直接 axios
- **Auth**：OAuth2 双 token（access 短 / refresh 30d），存 OS keychain；401 拦截器自动 refresh 一次
- **客户端识别**：所有请求带 `X-Client-Type: desktop` + `X-Client-Version`
- **本地数据**：`<AppData>/scholarpilot/scholarpilot.db`（SQLite，11 表对齐 backend 模型）
- **BYOK（M3+）**：客户端注 `X-User-LLM-*` header → backend 切 active_provider
- **i18n**：Element Plus 必须 `import zhCn` + `app.use(ElementPlus, { locale: zhCn })`
- **el-table 内 el-select**：用字符串 value，不能用数字

## 历史踩坑

见 [`CI.md`](./CI.md) 历史踩坑表 + `docs/architecture/06-desktop-client.md` 决策记录。
