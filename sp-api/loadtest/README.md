# sp-api Load Test

k6 压测脚本，针对 sp-api（HK client-only backend）的 fetcher 代理层。

## 文件

- `loadtest.k6.js` — k6 主脚本
- `REPORT.md` — 最近一次跑的结果（手填或脚本生成）

## 前置

### 1. 起 sp-api 本地栈

```powershell
cd D:\AI\scholarpilot-dev
docker compose -f docker-compose.sp-api.yml up -d --build
docker compose -f docker-compose.sp-api.yml ps
# 等到 sp-api-backend 显示 (healthy)
```

默认端口：`localhost:18000`（`SP_API_PORT` 可改）。

### 2. 装 k6（任选）

**A. 本地 portable binary**（推荐，winget 可能装不上）：
```powershell
$k6Dir = "$env:USERPROFILE\bin"
mkdir $k6Dir -ErrorAction SilentlyContinue
Invoke-WebRequest "https://github.com/grafana/k6/releases/download/v0.50.0/k6-v0.50.0-windows-amd64.zip" -OutFile "$k6Dir\k6.zip"
Expand-Archive "$k6Dir\k6.zip" -DestinationPath $k6Dir -Force
Move-Item "$k6Dir\k6-v0.50.0-windows-amd64\k6.exe" "$k6Dir\k6.exe" -Force
& "$k6Dir\k6.exe" version
```

**B. Docker 跑 k6**（不想装本地）：
```powershell
docker run --rm -i --network host `
  -v "D:\AI\scholarpilot-dev\sp-api\loadtest:/scripts" `
  grafana/k6:latest run /scripts/loadtest.k6.js
```

注意：Windows Docker Desktop 上 `--network host` 不能直通宿主，必须用宿主可达地址。
建议从容器视角写 BASE：`-e SP_API_URL=http://host.docker.internal:18000`。

## 跑法

```powershell
# 默认 stages：20s/20vu → 1m/100vu → 20s/0vu
& "$env:USERPROFILE\bin\k6.exe" run D:\AI\scholarpilot-dev\sp-api\loadtest\loadtest.k6.js

# 自定义 base URL
$env:SP_API_URL = "http://localhost:18000"
& "$env:USERPROFILE\bin\k6.exe" run D:\AI\scholarpilot-dev\sp-api\loadtest\loadtest.k6.js

# 短测试（冒烟）
& "$env:USERPROFILE\bin\k6.exe" run --vus 5 --duration 15s D:\AI\scholarpilot-dev\sp-api\loadtest\loadtest.k6.js

# 输出 JSON 摘要
& "$env:USERPROFILE\bin\k6.exe" run --summary-export=summary.json D:\AI\scholarpilot-dev\sp-api\loadtest\loadtest.k6.js
```

## 覆盖路由

| 路由 | Auth | 期望 |
|---|---|---|
| `GET /health` | 无 | 200 + `sources[]` |
| `GET /api/health` | 无 | 200 |
| `GET /` | 无 | 200 |
| `GET /api/fetcher/sources` | OAuth2 | 401（路由活，门有锁） |
| `POST /api/fetcher/search` | OAuth2 | 401/422（同上） |

**为什么不带 token？** 压测目标是 uvicorn workers 的吞吐 / latency / middleware overhead，
不是 fetcher 本身（fetcher 真打外部 API 会被限流 + 干扰真实流量）。401 也走 middleware
+ DI + dependency 解析，是有效负载样本。

## 阈值

- `http_req_failed` rate < 5%（只 5xx 算 failed）
- `http_req_duration` p95 < 800ms / p99 < 2000ms
- `app_5xx_total` count < 50（30s+1m+20s 总跑约 120 万请求路径里的硬上限）
- `health_ok_rate` > 95%

## 容器资源监控（并行跑压测时）

另开终端：
```powershell
docker stats sp-api-backend sp-api-worker sp-api-postgres sp-api-redis --no-stream
# 或循环采样
while ($true) { docker stats --no-stream --format "{{.Name}}: cpu={{.CPUPerc}} mem={{.MemUsage}}" sp-api-backend sp-api-worker sp-api-postgres sp-api-redis; Start-Sleep 5 }
```

## 看结果

k6 cli 自带 summary 表（终端），含：
- `iterations` —— 总迭代次数
- `vus_max` —— 峰值并发
- `http_req_duration` p50/p95/p99
- `http_req_failed` 占比
- 自定义指标：`app_5xx_total`、`health_ok_rate`、`sources_latency_ms`

填到 `REPORT.md` 对照阈值。
