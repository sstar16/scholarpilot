# ScholarPilot Proxy Worker

Cloudflare Workers 反代 bioRxiv + googleapis，解决大陆 IP 被屏蔽问题。

## 路由

| Path 前缀 | 上游 |
|---|---|
| `/biorxiv/...` | `https://api.biorxiv.org/...` |
| `/googleapis/...` | `https://www.googleapis.com/...` |

## 部署（首次）

```bash
cd proxy-worker
npm install -g wrangler    # 如已安装跳过
wrangler login             # 浏览器弹出 CF 登录授权
wrangler secret put ACCESS_TOKEN
# 粘一个随机长串（比如 openssl rand -hex 32 生成的），当作访问令牌
wrangler deploy
```

部署后输出形如：
```
Deployed scholarpilot-proxy triggers (0.54 sec)
  https://scholarpilot-proxy.<your-subdomain>.workers.dev
```

记下这个 URL，以及刚才设置的 `ACCESS_TOKEN`。

## 验证

```bash
TOKEN=<your-access-token>
WORKER=https://scholarpilot-proxy.<your-subdomain>.workers.dev

# 1) 健康检查（不需要 token）
curl -s "$WORKER/__ping"

# 2) 代理 bioRxiv（需要 token）
curl -sH "X-Proxy-Token: $TOKEN" \
  "$WORKER/biorxiv/details/biorxiv/2025-01-01/2025-01-07/0" | head -c 300

# 3) 代理 googleapis
curl -sH "X-Proxy-Token: $TOKEN" \
  "$WORKER/googleapis/discovery/v1/apis" | head -c 300
```

bioRxiv 的响应应该包含 `"collection":[{...}]` 且有真实 DOI 条目，
不再是 `"Not available at this time"`。

## 配到 ScholarPilot

部署通过后，把 Worker URL 和 Token 告诉 Claude，
会自动把 `proxy_overrides` 写到 Redis 给 biorxiv / medrxiv / bigquery_patents 三个 fetcher：

```
biorxiv          → <WORKER>/biorxiv
medrxiv          → <WORKER>/biorxiv   (同上游)
bigquery_patents → <WORKER>/googleapis
```

后端 `source_config_store.get_proxy_for_source()` 会自动应用，
fetcher 改动极小（已有基础设施）。

## 免费套餐额度

- 10 万请求/天
- 每请求 10ms CPU
- 10 MB 内存

ScholarPilot 一轮检索 bioRxiv + medRxiv + bigquery_patents 加起来大约 5-20 个请求，
一天几百轮也远远用不完。
