"""sp-api Locust 压测（k6 不可用时备用）。

跑法：
    pip install locust
    locust -f loadtest.locustfile.py --host http://localhost:18000

然后浏览器开 http://localhost:8089 → Users 100 / Spawn rate 10。

无头跑：
    locust -f loadtest.locustfile.py --host http://localhost:18000 \
        --users 100 --spawn-rate 10 --run-time 2m --headless --csv result

阈值（手工核对，locust 没 k6 那种 thresholds DSL）：
    - failures / total < 5%（仅 5xx 算 failure，4xx 已 catch）
    - response p95 < 800ms

设计同 k6 脚本：不带 token，401 计 success（路由活）；只 5xx 计 failure。
"""
from locust import HttpUser, between, task


class SpApiUser(HttpUser):
    """模拟客户端流量。每个虚拟用户 1-3s 间隔轮询。"""

    wait_time = between(1, 3)

    @task(3)
    def health(self):
        """高频：客户端启动 / 心跳。"""
        with self.client.get("/health", catch_response=True, name="health") as r:
            if r.status_code == 200 and isinstance(r.json().get("sources"), list):
                r.success()
            elif r.status_code >= 500:
                r.failure(f"5xx: {r.status_code}")
            else:
                r.failure(f"unexpected: {r.status_code}")

    @task(1)
    def api_health(self):
        with self.client.get("/api/health", catch_response=True, name="api_health") as r:
            if r.status_code == 200:
                r.success()
            elif r.status_code >= 500:
                r.failure(f"5xx: {r.status_code}")

    @task(1)
    def root(self):
        with self.client.get("/", catch_response=True, name="root") as r:
            if r.status_code == 200:
                r.success()
            elif r.status_code >= 500:
                r.failure(f"5xx: {r.status_code}")

    @task(2)
    def fetcher_sources(self):
        """需 auth → 401 视为成功（路由活，门有锁）。"""
        with self.client.get(
            "/api/fetcher/sources", catch_response=True, name="fetcher_sources"
        ) as r:
            if r.status_code < 500:
                r.success()  # 401/403/200 都算 OK
            else:
                r.failure(f"5xx: {r.status_code}")

    @task(2)
    def fetcher_search(self):
        """POST + JSON schema + DI 解析路径。"""
        payload = {
            "source": "arxiv",
            "keywords": "transformer attention",
            "max_results": 3,
        }
        with self.client.post(
            "/api/fetcher/search",
            json=payload,
            catch_response=True,
            name="fetcher_search",
        ) as r:
            if r.status_code < 500:
                r.success()
            else:
                r.failure(f"5xx: {r.status_code}")
