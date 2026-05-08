# sp-api Load Test Report

**测试时间**：2026-05-08
**测试目标**：验证 sp-api 在 100 并发用户下的稳定性 + 内存占用 + 响应延迟。
**结论**：✅ **PASS**（无 5xx，p95 3ms，4 容器总内存 < 460MB，远低于 HK 4G 机极限）。

---

## 测试参数

| 项 | 值 |
|---|---|
| 工具 | [k6 v0.50.0](https://github.com/grafana/k6) |
| 阶段 | 20s ramp 0→20 / 1m ramp 20→100 / 20s ramp 100→0 |
| 持续时间 | ~1m40s 实际 |
| Max VUs | 100 |
| 总请求数 | 12,161 |
| RPS | ~120 req/s |
| 总迭代 | 2,432 |
| 端点 | `/api/health` + `/api/fetcher/sources` + `/api/fetcher/search` |
| 部署目标 | 本地 Docker `docker-compose.sp-api.yml` (4 容器) |

## 关键指标

### Latency (http_req_duration)
| 百分位 | 值 |
|---|---|
| avg | 1.89 ms |
| p(50) / median | 1.67 ms |
| p(90) | 2.94 ms |
| **p(95)** | **3.35 ms** |
| p(99) / max | 33.4 ms |

✅ **远低于 threshold p(95) < 800ms**

### Success Rate
- **业务 checks**：19,456 / 19,456 全过（status < 500）
- **`/api/health`**：2,432 / 2,432 全过（100% pass rate）
- **http_req_failed = 40%**：实际是 fetcher 路由要求 auth → 401 计入 k6 默认 fail metric。**真实 5xx 错误数 = 0**。

### Container Resource (压测中实测)
| 容器 | CPU | RAM | RAM % |
|---|---|---|---|
| sp-api-backend (FastAPI) | 0.39% | **180.6 MiB** | 1.14% |
| sp-api-worker (Celery) | 0.21% | 196.6 MiB | 1.24% |
| sp-api-postgres | 0.00% | 69.5 MiB | 0.44% |
| sp-api-redis | 0.42% | 12.0 MiB | 0.08% |
| **合计** | < 1% | **~459 MiB** | < 3% |

✅ **远低于 HK 4GB 机的极限**。100 用户并发下 backend 仅占 180MB，意味着 4G 机能轻松扛 1000+ 用户压力（前提 fetcher 真实调外部 API 的 IO 不阻塞 worker）。

## 对比 backend 旧架构

| 维度 | backend 旧（chromium playwright × 8 worker） | sp-api 新 |
|---|---|---|
| Worker 内存峰值 | ~1.4 GiB（OOM 触发 3GB 后已加 `DISABLE_FULLTEXT_BROWSER`） | 196 MiB |
| Image 体积 | ~1.5 GB | ~455 MB |
| 100 并发健康度 | OOM 风险 | 稳定 |

## 已知限制 / 后续优化

1. **未带真实 auth token**：fetcher 路由返 401（不计 5xx），未真正调用外部 API（OpenAlex/arXiv 等）。**真实场景**下 fetcher 延迟受外部数据源限制，不在 sp-api 内部 latency 范围内。
2. **未压 `/api/fulltext/download`**：PDF 下载是阻塞性 IO，应单独压测（建议 < 5 RPS）。本次未跑避免压外部源。
3. **k6 worker 未跑 `/api/auth/register`**：邀请码注册需手动 admin 开。补 auth 后可压 `/api/fetcher/search` 真实路径。

## 下次压测建议

1. **混合负载**：80% search + 10% download + 10% auth/me（测真实业务）
2. **持续 30 分钟**：检查内存泄漏
3. **HK 真机跑**（部署 sp-api 到 HK 后用 GitHub Actions 远程跑 k6 cloud）

## 文件

- `loadtest.k6.js` — k6 主脚本
- `loadtest.locustfile.py` — locust 备选
- `summary.json` — k6 完整 metrics
- `k6-output.log` — k6 控制台输出
- `README.md` — 跑法说明
- `REPORT.md` — 本报告
