"""监控管理 API — 用户可随时开关和配置"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.document import Document
from app.models.monitor_job import MonitorJob, MonitorResult
from app.models.monitoring_push import MonitoringPush
from app.services.progressive_search import activate_monitoring

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["monitoring"])


@router.post("/{project_id}/monitoring/enable")
async def enable_monitoring(
    project_id: uuid.UUID,
    body: dict = {},
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """开启项目监控"""
    project = await _get_project(project_id, current_user.id, db)

    schedule = body.get("schedule", "daily")
    search_config = body.get("search_config")

    job = await activate_monitoring(project, db, schedule=schedule, search_config=search_config)
    return {
        "status": "enabled",
        "schedule": job.schedule,
        "is_active": job.is_active,
        "project_status": project.status,
    }


@router.post("/{project_id}/monitoring/disable")
async def disable_monitoring(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """关闭项目监控"""
    project = await _get_project(project_id, current_user.id, db)

    result = await db.execute(
        select(MonitorJob).where(MonitorJob.project_id == project_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="未找到监控任务")

    job.is_active = False
    project.status = "active"
    await db.commit()

    return {"status": "disabled"}


@router.get("/{project_id}/monitoring")
async def get_monitoring(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取监控配置和最新结果"""
    await _get_project(project_id, current_user.id, db)

    result = await db.execute(
        select(MonitorJob).where(MonitorJob.project_id == project_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        return {"enabled": False, "config": None, "latest_results": []}

    # 获取最近3次结果
    results_q = await db.execute(
        select(MonitorResult)
        .where(MonitorResult.job_id == job.id)
        .order_by(MonitorResult.run_at.desc())
        .limit(3)
    )
    latest = results_q.scalars().all()

    return {
        "enabled": job.is_active,
        "schedule": job.schedule,
        "search_config": job.search_config,
        "last_run_at": job.last_run_at.isoformat() if job.last_run_at else None,
        "next_run_at": job.next_run_at.isoformat() if job.next_run_at else None,
        "latest_results": [
            {
                "id": str(r.id),
                "run_at": r.run_at.isoformat(),
                "new_docs_found": r.new_docs_found,
                "docs": r.docs,
            }
            for r in latest
        ],
    }


@router.patch("/{project_id}/monitoring")
async def update_monitoring(
    project_id: uuid.UUID,
    body: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新监控配置"""
    await _get_project(project_id, current_user.id, db)

    result = await db.execute(
        select(MonitorJob).where(MonitorJob.project_id == project_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="未找到监控任务")

    if "schedule" in body:
        job.schedule = body["schedule"]
    if "search_config" in body:
        job.search_config = body["search_config"]
    if "is_active" in body:
        job.is_active = body["is_active"]
    if "novelty_threshold" in body:
        job.novelty_threshold = body["novelty_threshold"]
    if "push_config" in body:
        job.push_config = body["push_config"]

    await db.commit()
    return {"status": "updated", "schedule": job.schedule, "is_active": job.is_active}


@router.get("/{project_id}/monitoring/results")
async def get_monitoring_results(
    project_id: uuid.UUID,
    page: int = 1,
    page_size: int = 10,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """分页获取监控结果"""
    await _get_project(project_id, current_user.id, db)

    result = await db.execute(
        select(MonitorJob).where(MonitorJob.project_id == project_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        return {"results": [], "total": 0}

    results_q = await db.execute(
        select(MonitorResult)
        .where(MonitorResult.job_id == job.id)
        .order_by(MonitorResult.run_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    return {
        "results": [
            {
                "id": str(r.id),
                "run_at": r.run_at.isoformat(),
                "new_docs_found": r.new_docs_found,
                "docs": r.docs,
            }
            for r in results_q.scalars().all()
        ],
    }


@router.get("/{project_id}/monitoring/pushes")
async def get_pending_pushes(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取待分类的推送文献"""
    await _get_project(project_id, current_user.id, db)

    result = await db.execute(
        select(MonitoringPush, Document)
        .join(Document, MonitoringPush.document_id == Document.id)
        .where(
            MonitoringPush.project_id == project_id,
            MonitoringPush.status == "pending",
        )
        .order_by(MonitoringPush.novelty_score.desc())
        .limit(50)
    )

    pushes = []
    for push, doc in result.all():
        pushes.append({
            "push_id": str(push.id),
            "document_id": str(doc.id),
            "title": doc.title,
            "source": doc.source,
            "abstract": (doc.abstract or "")[:200],
            "novelty_score": push.novelty_score,
            "push_summary": push.push_summary,
            "created_at": push.created_at.isoformat(),
        })

    return {"pushes": pushes, "total": len(pushes)}


@router.post("/{project_id}/monitoring/pushes/{push_id}/classify")
async def classify_push(
    project_id: uuid.UUID,
    push_id: uuid.UUID,
    body: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """分类推送文献到桶（复用 4 桶系统）"""
    await _get_project(project_id, current_user.id, db)

    result = await db.execute(
        select(MonitoringPush).where(
            MonitoringPush.id == push_id,
            MonitoringPush.project_id == project_id,
        )
    )
    push = result.scalar_one_or_none()
    if not push:
        raise HTTPException(status_code=404, detail="推送记录不存在")

    bucket = body.get("bucket")
    if bucket not in ("very_relevant", "relevant", "uncertain", "irrelevant"):
        raise HTTPException(status_code=400, detail="无效的桶名称")

    # Classify via existing classification system
    from app.models.document_classification import DocumentClassification
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    existing = await db.execute(
        select(DocumentClassification).where(
            DocumentClassification.user_id == current_user.id,
            DocumentClassification.project_id == project_id,
            DocumentClassification.document_id == push.document_id,
        )
    )
    classification = existing.scalar_one_or_none()
    if classification:
        classification.bucket = bucket
        classification.moved_at = now
    else:
        classification = DocumentClassification(
            user_id=current_user.id,
            project_id=project_id,
            document_id=push.document_id,
            bucket=bucket,
            classified_at=now,
        )
        db.add(classification)

    # Update push status
    push.status = "classified"

    # Decrement pending count on MonitorJob
    job_result = await db.execute(
        select(MonitorJob).where(MonitorJob.project_id == project_id)
    )
    job = job_result.scalar_one_or_none()
    if job and job.pending_push_count > 0:
        job.pending_push_count -= 1

    await db.commit()
    return {"status": "classified", "bucket": bucket}


@router.post("/{project_id}/monitoring/pushes/{push_id}/dismiss")
async def dismiss_push(
    project_id: uuid.UUID,
    push_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """忽略推送"""
    await _get_project(project_id, current_user.id, db)

    result = await db.execute(
        select(MonitoringPush).where(
            MonitoringPush.id == push_id,
            MonitoringPush.project_id == project_id,
        )
    )
    push = result.scalar_one_or_none()
    if not push:
        raise HTTPException(status_code=404, detail="推送记录不存在")

    push.status = "dismissed"

    job_result = await db.execute(
        select(MonitorJob).where(MonitorJob.project_id == project_id)
    )
    job = job_result.scalar_one_or_none()
    if job and job.pending_push_count > 0:
        job.pending_push_count -= 1

    await db.commit()
    return {"status": "dismissed"}


@router.post("/{project_id}/monitoring/pushes/clear")
async def clear_all_pushes(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """清空所有待处理推送"""
    await _get_project(project_id, current_user.id, db)

    from sqlalchemy import update
    await db.execute(
        update(MonitoringPush).where(
            MonitoringPush.project_id == project_id,
            MonitoringPush.status == "pending",
        ).values(status="dismissed")
    )

    job_result = await db.execute(
        select(MonitorJob).where(MonitorJob.project_id == project_id)
    )
    job = job_result.scalar_one_or_none()
    if job:
        job.pending_push_count = 0

    await db.commit()
    return {"status": "cleared"}


async def _get_project(project_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession):
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project
