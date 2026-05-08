"""
ROUND_COMPLETE hook — 轮次结束后触发 KG 增量刷新（B3）

触发时机：用户点"结束本轮" (search.py finalize_round endpoint fire)
动作：Celery 派发 rebuild_graph 后台任务，限定 bucket=highly_relevant
理由：
  - 本轮用户分类产生的新边（doc→concept / doc→author）应及时反映
  - 只对 highly_relevant 桶重建：最高 ROI；其他桶的 edge 信噪比低
  - 异步派发，不阻塞 finalize_round 响应
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from app.harness.hook_engine import HookEngine, HookPoint

logger = logging.getLogger(__name__)


async def refresh_kg_on_round_complete(ctx: Dict[str, Any]) -> Dict[str, Any]:
    project_id = ctx.get("project_id")
    if not project_id:
        return ctx

    try:
        from celery import chain
        from app.workers.graph_tasks import (
            rebuild_graph,
            enrich_concept_edges,
            enrich_citations,
            enrich_doc_relations,
        )
        # 必须串行：多任务并发读 JSON 再各自 save 会互相覆盖 llm_inferred 边
        chain(
            rebuild_graph.si(str(project_id), "highly_relevant"),
            enrich_concept_edges.si(str(project_id)),
            enrich_citations.si(str(project_id)),
            enrich_doc_relations.si(str(project_id)),
        ).apply_async()
        logger.info(
            "[kg_refresh] chain: rebuild → concept → citations → doc_relations project=%s",
            str(project_id)[:8],
        )
    except Exception as e:
        logger.warning("[kg_refresh] dispatch failed (benign): %s", e)

    return ctx


def register_kg_refresh_hook(engine: HookEngine) -> None:
    engine.register(
        HookPoint.ROUND_COMPLETE,
        refresh_kg_on_round_complete,
        name="kg_refresh",
        priority=60,
    )
