"""
渐进式检索状态机
管理 SearchRound 的生命周期：创建 → 检索 → 摘要 → 等待反馈 → 完成 → 下一轮
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.models.project import Project
from app.models.search_round import SearchRound
from app.models.document import Document
from app.models.round_document import RoundDocument
from app.models.monitor_job import MonitorJob
from app.services.query_builder import ROUND_CONFIGS, build_query, _get_round_config, get_max_rounds


async def create_next_round(
    project: Project,
    db: AsyncSession,
) -> SearchRound:
    """创建下一轮（project.current_round + 1），支持自定义轮数"""
    next_num = project.current_round + 1
    max_rounds = project.max_rounds or get_max_rounds(project.search_config)
    if next_num > max_rounds:
        raise ValueError(f"已完成全部{max_rounds}轮检索")

    config = _get_round_config(next_num, project.search_config)
    round_ = SearchRound(
        project_id=project.id,
        round_number=next_num,
        status="pending",
        time_horizon_years=config.get("years"),
        max_results=config.get("max_results", 20),
        language_scope=config.get("scope", "international"),
    )
    db.add(round_)
    project.current_round = next_num
    await db.flush()
    return round_


async def mark_round_awaiting_keywords(round_id: uuid.UUID, db: AsyncSession):
    """Phase 1 完成后标记为等待用户确认关键词"""
    await db.execute(
        update(SearchRound).where(SearchRound.id == round_id).values(
            status="awaiting_keywords",
            progress=0.05,
            progress_message="关键词已生成，等待确认...",
        )
    )
    await db.commit()


async def mark_round_searching(round_id: uuid.UUID, db: AsyncSession):
    await db.execute(
        update(SearchRound).where(SearchRound.id == round_id).values(
            status="searching",
            started_at=datetime.now(timezone.utc),
            progress=0.1,
            progress_message="正在检索数据库...",
        )
    )
    await db.commit()


async def mark_round_summarizing(
    round_id: uuid.UUID,
    total_candidates: int,
    selected_count: int,
    db: AsyncSession,
    source_stats: Optional[Dict] = None,
):
    values = dict(
        status="summarizing",
        total_candidates=total_candidates,
        selected_count=selected_count,
        progress=0.6,
        progress_message=f"已检索到 {total_candidates} 篇，AI 正在生成摘要...",
    )
    if source_stats is not None:
        values["source_stats"] = source_stats
    await db.execute(
        update(SearchRound).where(SearchRound.id == round_id).values(**values)
    )
    await db.commit()


async def mark_round_awaiting_feedback(round_id: uuid.UUID, db: AsyncSession):
    await db.execute(
        update(SearchRound).where(SearchRound.id == round_id).values(
            status="awaiting_feedback",
            progress=1.0,
            progress_message="摘要生成完毕，请评分",
        )
    )
    await db.commit()


async def mark_round_complete(round_id: uuid.UUID, db: AsyncSession):
    await db.execute(
        update(SearchRound).where(SearchRound.id == round_id).values(
            status="complete",
            completed_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()


async def save_round_documents(
    round_id: uuid.UUID,
    docs: list,
    db: AsyncSession,
):
    """将检索结果批量保存为 Document + RoundDocument"""
    for rank, raw_doc in enumerate(docs, start=1):
        # 尝试查找已有文档（去重）
        result = await db.execute(
            select(Document).where(
                Document.source == raw_doc.get("source"),
                Document.external_id == str(raw_doc.get("external_id", "")),
            )
        )
        doc = result.scalar_one_or_none()

        if doc:
            # 已存在的文档：如果新数据有更完整的字段，更新之
            updated = False
            new_abstract = raw_doc.get("abstract")
            if new_abstract and not doc.abstract:
                doc.abstract = new_abstract
                updated = True
            new_doi = raw_doc.get("doi")
            if new_doi and not doc.doi:
                doc.doi = new_doi
                updated = True
            new_cite = raw_doc.get("citation_count", 0)
            if new_cite and (doc.citation_count or 0) == 0:
                doc.citation_count = new_cite
                updated = True
            if updated:
                await db.flush()

        if not doc:
            pub_date = None
            raw_date = raw_doc.get("publication_date")
            if raw_date:
                try:
                    from dateutil import parser as dateparser
                    pub_date = dateparser.parse(str(raw_date)).date()
                except Exception:
                    pass

            doc = Document(
                source=raw_doc.get("source", "unknown"),
                external_id=str(raw_doc.get("external_id", "")),
                doc_type=raw_doc.get("doc_type", "paper"),
                title=raw_doc.get("title", ""),
                authors=raw_doc.get("authors"),
                abstract=raw_doc.get("abstract"),
                publication_date=pub_date,
                url=raw_doc.get("url"),
                doi=raw_doc.get("doi"),
                journal=raw_doc.get("journal"),
                citation_count=raw_doc.get("citation_count", 0),
                pdf_url=raw_doc.get("pdf_url"),
            )
            db.add(doc)
            await db.flush()

        # 关联到本轮
        existing = await db.execute(
            select(RoundDocument).where(
                RoundDocument.round_id == round_id,
                RoundDocument.document_id == doc.id,
            )
        )
        if not existing.scalar_one_or_none():
            rd = RoundDocument(
                round_id=round_id,
                document_id=doc.id,
                rank_in_round=rank,
                initial_score=raw_doc.get("_relevance_score"),
                agent_score=raw_doc.get("_agent_score"),
                agent_rationale=raw_doc.get("_agent_rationale"),
                one_line_summary=raw_doc.get("_one_line_summary"),
                below_cutoff=raw_doc.get("_below_cutoff", False),
            )
            db.add(rd)

            # 同步更新 Document 的规范一句话总结
            one_line = raw_doc.get("_one_line_summary")
            if one_line and not doc.one_line_summary:
                doc.one_line_summary = one_line

    await db.commit()


async def activate_monitoring(project: Project, db: AsyncSession):
    """最后一轮完成后激活每日监控"""
    max_rounds = project.max_rounds or get_max_rounds(project.search_config)
    result = await db.execute(
        select(SearchRound).where(
            SearchRound.project_id == project.id,
            SearchRound.round_number == max_rounds,
        )
    )
    round5 = result.scalar_one_or_none()
    search_config = {
        "queries": round5.search_queries if round5 else {},
        "sources": round5.sources_used if round5 else [],
        "language_scope": "global",
    }

    job = MonitorJob(
        project_id=project.id,
        user_id=project.user_id,
        schedule="daily",
        is_active=True,
        search_config=search_config,
    )
    db.add(job)
    project.status = "monitoring"
    await db.commit()
