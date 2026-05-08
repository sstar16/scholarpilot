"""Stack Exchange 数据源 Fetcher

GET `https://api.stackexchange.com/2.3/search/advanced` — 300 req/day 不需 key。
覆盖 stackoverflow（默认）；也可通过 site 参数切到 cs.stackexchange / biology /
math 等。doc_type='qa'。

Inspired by: LDR `search_engine_stackexchange.py`（公开 API）
ScholarPilot 改动：默认 site=stackoverflow（最常见），按 votes 排序；不抓
answers（避免双倍 rate-limit；scoring stage 已能从 question body 评估）。
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from app.services.fetchers.base import AbstractFetcher

logger = logging.getLogger(__name__)

STACK_BASE = "https://api.stackexchange.com/2.3"


class StackExchangeFetcher(AbstractFetcher):
    source_id = "stackexchange"
    DEFAULT_TIMEOUT = 20.0

    def _site(self) -> str:
        return os.getenv("STACKEXCHANGE_SITE", "stackoverflow") or "stackoverflow"

    async def fetch(
        self,
        query: str,
        max_results: int = 20,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        language: Optional[str] = None,
    ) -> List[Dict]:
        params: Dict[str, object] = {
            "q": query,
            "order": "desc",
            "sort": "votes",
            "site": self._site(),
            "pagesize": min(max_results, 100),
            "filter": "withbody",  # 拿到 body（HTML）作为 abstract
        }
        if year_from:
            from datetime import datetime as _dt
            params["fromdate"] = int(_dt(year_from, 1, 1).timestamp())
        if year_to:
            from datetime import datetime as _dt
            params["todate"] = int(_dt(year_to, 12, 31).timestamp())

        papers: List[Dict] = []
        async with self._http_client(headers={"User-Agent": "ScholarPilot/2.0"}) as client:
            try:
                r = await client.get(f"{STACK_BASE}/search/advanced", params=params)
                if r.status_code != 200:
                    logger.warning("[StackExchange] HTTP %d: %s", r.status_code, r.text[:200])
                    return []
                items = (r.json() or {}).get("items", []) or []
                import re as _re
                for q in items[:max_results]:
                    qid = q.get("question_id")
                    title = q.get("title") or ""
                    body_html = q.get("body") or ""
                    body = _re.sub(r"<[^>]+>", "", body_html).strip() if body_html else ""
                    # 截断长 body 以免占爆 LLM 上下文
                    if len(body) > 1500:
                        body = body[:1500] + "..."
                    score = q.get("score") or 0
                    answer_count = q.get("answer_count") or 0
                    is_answered = q.get("is_answered") or False
                    tags = q.get("tags") or []
                    creation_date = q.get("creation_date")
                    last_activity = q.get("last_activity_date")
                    owner = (q.get("owner") or {}).get("display_name") or ""
                    abstract_parts = []
                    if body:
                        abstract_parts.append(body)
                    if tags:
                        abstract_parts.append(f"Tags: {', '.join(tags[:8])}")
                    abstract_parts.append(f"Score: {score} / Answers: {answer_count}{' (answered)' if is_answered else ''}")
                    pub_date = None
                    if creation_date:
                        from datetime import datetime as _dt, timezone as _tz
                        try:
                            pub_date = _dt.fromtimestamp(int(creation_date), tz=_tz.utc).strftime("%Y-%m-%d")
                        except Exception:
                            pub_date = None
                    papers.append({
                        "source": "stackexchange",
                        "external_id": str(qid) if qid else (q.get("link") or ""),
                        "doc_type": "qa",
                        "title": title,
                        "authors": owner,
                        "abstract": " | ".join(abstract_parts),
                        "publication_date": pub_date,
                        "journal": params["site"],
                        "doi": None,
                        # score 当 citation_count（"投票数 ≈ 影响力"）
                        "citation_count": score,
                        "pdf_url": None,
                        "url": q.get("link"),
                        "metadata": {
                            "tags": tags,
                            "answer_count": answer_count,
                            "is_answered": is_answered,
                            "last_activity_date": last_activity,
                        },
                    })
            except Exception as e:
                logger.error("[StackExchange] %s: %s", type(e).__name__, e, exc_info=True)
        return papers
