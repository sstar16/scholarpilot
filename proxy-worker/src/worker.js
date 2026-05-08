/**
 * ScholarPilot Proxy Worker
 *
 * 反代被中国大陆 IP 屏蔽的学术源。
 *
 * 路由规则:
 *   /biorxiv/<path>    → https://api.biorxiv.org/<path>
 *   /googleapis/<path> → https://www.googleapis.com/<path>
 *
 * 使用场景：后端 fetcher 通过 source_config_store.get_proxy_for_source()
 * 拿到本 Worker 的 URL 前缀，按 source_id 走对应路径。
 */

const ALLOW = {
  biorxiv: "api.biorxiv.org",
  googleapis: "www.googleapis.com",
};

// 防止误用：要求请求带这个自定义 header（env-configurable）才放行。
// 值从 Worker Secret 里读：wrangler secret put ACCESS_TOKEN
// 后端通过 config 将此值塞进 headers。

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // 健康检查
    if (url.pathname === "/" || url.pathname === "/__ping") {
      return json({
        ok: true,
        service: "scholarpilot-proxy",
        routes: Object.keys(ALLOW),
      });
    }

    // 访问令牌校验（可选，但强烈建议）
    const requiredToken = env.ACCESS_TOKEN;
    if (requiredToken) {
      const got = request.headers.get("X-Proxy-Token") || url.searchParams.get("proxy_token");
      if (got !== requiredToken) {
        return new Response("Forbidden: bad or missing proxy token", { status: 403 });
      }
    }

    const parts = url.pathname.split("/").filter(Boolean);
    if (parts.length === 0) {
      return new Response("Missing route prefix. Try /biorxiv/... or /googleapis/...", { status: 400 });
    }
    const key = parts[0];
    const target = ALLOW[key];
    if (!target) {
      return new Response(`Unknown route: ${key}. Whitelist: ${Object.keys(ALLOW).join(", ")}`, { status: 404 });
    }

    const restPath = parts.slice(1).join("/");
    // 清理可能包含 proxy_token 的 query
    const upstreamSearch = new URLSearchParams(url.search);
    upstreamSearch.delete("proxy_token");
    const qs = upstreamSearch.toString();
    const upstreamUrl = `https://${target}/${restPath}${qs ? "?" + qs : ""}`;

    // 重建请求，剔除 CF 注入头，覆盖 Host
    const upstreamHeaders = new Headers(request.headers);
    ["cf-connecting-ip", "cf-visitor", "cf-ipcountry", "cf-ray", "x-forwarded-for", "x-real-ip", "X-Proxy-Token"].forEach(
      (h) => upstreamHeaders.delete(h)
    );
    upstreamHeaders.set("Host", target);

    const upstreamReq = new Request(upstreamUrl, {
      method: request.method,
      headers: upstreamHeaders,
      body: ["GET", "HEAD"].includes(request.method) ? null : request.body,
      redirect: "follow",
    });

    try {
      const resp = await fetch(upstreamReq);
      // 直接透传响应
      const out = new Response(resp.body, resp);
      out.headers.set("X-Proxied-By", "scholarpilot-proxy");
      return out;
    } catch (e) {
      return new Response(`Upstream error: ${e.message}`, { status: 502 });
    }
  },
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj, null, 2), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
