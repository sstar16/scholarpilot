"""
Verify Library API endpoints against a real running backend.

Requires: docker-compose up + at least one project with some .md files.
"""
from __future__ import annotations

import asyncio
import os

import httpx

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")
TOKEN = os.environ.get("VERIFY_TOKEN", "")  # 从前端 localStorage 拷一个 JWT


async def main() -> None:
    if not TOKEN:
        print("WARN: 需要设 VERIFY_TOKEN 环境变量 (JWT from frontend localStorage)")
        return

    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with httpx.AsyncClient(base_url=BACKEND_URL, headers=headers, timeout=30) as client:
        projects = await client.get("/api/projects")
        projects.raise_for_status()
        project_list = projects.json()
        if not project_list:
            print("FAIL: no projects")
            return
        pid = project_list[0]["id"]
        print(f"-> testing project {pid[:8]}")

        # 1. list
        r = await client.get(f"/api/projects/{pid}/library")
        print(f"GET /library -> {r.status_code}, total={r.json().get('total')}")
        r.raise_for_status()
        body = r.json()
        print(f"  by_bucket: {body.get('by_bucket')}")
        assert "total" in body
        assert "files" in body

        files = body["files"]
        if not files:
            print("WARN: library is empty - run a round or trigger rebuild first")
            return

        # 2. detail
        first = files[0]
        slug = first["slug"]
        r2 = await client.get(f"/api/projects/{pid}/library/{slug}")
        print(f"GET /library/{slug[:20]} -> {r2.status_code}")
        r2.raise_for_status()
        detail = r2.json()
        assert "frontmatter" in detail
        assert "body_md" in detail
        print(f"  frontmatter keys: {list(detail['frontmatter'].keys())[:8]}...")

        # 3. raw
        r3 = await client.get(f"/api/projects/{pid}/library/{slug}/raw")
        print(f"GET /library/{slug[:20]}/raw -> {r3.status_code}")
        r3.raise_for_status()
        assert r3.headers["content-type"].startswith("text/markdown")

        # 4. rebuild
        r4 = await client.post(f"/api/projects/{pid}/library/rebuild")
        print(f"POST /library/rebuild -> {r4.status_code}, task_id={r4.json().get('task_id')}")
        r4.raise_for_status()

        print("\nOK all 4 endpoints working")


if __name__ == "__main__":
    asyncio.run(main())
