"""GitHub 数据源 Fetcher（仓库检索）

GET `https://api.github.com/search/repositories` — 最高 5000 req/h（带 token）
or 60 req/h（无 token）。给"工程类项目研究"补一个"现成实现"维度。

Inspired by: LDR `search_engine_github.py`（多 search_type，REST v3）
ScholarPilot 改动：只做 repositories 一种 search_type（最常用），
sort=stars desc；缺 GITHUB_TOKEN 时 fetcher 仍可用，但 60/h 速率上限。

doc_type='code_repo'。
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from app.services.fetchers.base import AbstractFetcher

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class GitHubFetcher(AbstractFetcher):
    source_id = "github"
    DEFAULT_TIMEOUT = 20.0

    def _token(self) -> str:
        return os.getenv("GITHUB_TOKEN", "") or ""

    async def fetch(
        self,
        query: str,
        max_results: int = 20,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        language: Optional[str] = None,
    ) -> List[Dict]:
        # GitHub 搜索语法：可在 query 里加 "stars:>10 language:python"，这里只透传 query
        q = query
        if year_from:
            q += f" created:>={year_from}-01-01"
        if year_to:
            q += f" created:<={year_to}-12-31"

        params = {
            "q": q,
            "sort": "stars",
            "order": "desc",
            "per_page": min(max_results, 100),
        }
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ScholarPilot/2.0",
        }
        token = self._token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        papers: List[Dict] = []
        async with self._http_client(headers=headers) as client:
            try:
                r = await client.get(f"{GITHUB_API_BASE}/search/repositories", params=params)
                if r.status_code != 200:
                    # 403 / 422 通常是限流或语法问题，warn 不抛
                    logger.warning("[GitHub] HTTP %d: %s", r.status_code, r.text[:200])
                    return []
                items = (r.json() or {}).get("items", []) or []
                for repo in items[:max_results]:
                    full_name = repo.get("full_name") or ""
                    description = repo.get("description") or ""
                    stars = repo.get("stargazers_count") or 0
                    forks = repo.get("forks_count") or 0
                    lang = repo.get("language") or ""
                    topics = repo.get("topics") or []
                    created = repo.get("created_at") or ""
                    pushed = repo.get("pushed_at") or ""
                    owner = (repo.get("owner") or {}).get("login") or ""
                    abstract_parts = [description] if description else []
                    if topics:
                        abstract_parts.append(f"Topics: {', '.join(topics[:10])}")
                    if lang:
                        abstract_parts.append(f"Language: {lang}")
                    abstract_parts.append(f"Stars: {stars} / Forks: {forks}")
                    if pushed:
                        abstract_parts.append(f"Last push: {pushed[:10]}")
                    papers.append({
                        "source": "github",
                        "external_id": str(repo.get("id") or full_name),
                        "doc_type": "code_repo",
                        "title": full_name,
                        "authors": owner,
                        "abstract": " | ".join(abstract_parts),
                        "publication_date": (created or "")[:10] or None,
                        "journal": "GitHub",
                        "doi": None,
                        # 用 stars 当 citation_count 类比（"被引/影响力"指标）
                        "citation_count": stars,
                        "pdf_url": None,
                        "url": repo.get("html_url"),
                        "metadata": {
                            "stars": stars,
                            "forks": forks,
                            "language": lang,
                            "topics": topics,
                            "pushed_at": pushed,
                        },
                    })
            except Exception as e:
                logger.error("[GitHub] %s: %s", type(e).__name__, e, exc_info=True)
        return papers
