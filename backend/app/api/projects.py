from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import List
import uuid

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=List[ProjectOut])
async def list_projects(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project)
        .where(Project.user_id == current_user.id)
        .order_by(Project.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    req: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    domains = req.get_domains()
    project = Project(
        user_id=current_user.id,
        title=req.title,
        description=req.description,
        domain=domains[0] if domains else (req.domain or "other"),
        domains=domains or [req.domain or "other"],
        search_config=req.search_config,
        max_rounds=req.max_rounds,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project_or_404(project_id, current_user.id, db)
    return project


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID,
    req: ProjectUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project_or_404(project_id, current_user.id, db)
    if req.title is not None:
        project.title = req.title
    if req.description is not None:
        project.description = req.description
    if req.status is not None:
        project.status = req.status
    if req.search_config is not None:
        project.search_config = req.search_config
    if req.max_rounds is not None:
        project.max_rounds = req.max_rounds
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, current_user.id, db)

    # 先把挂到该项目的 conversation_sessions 归位到 idle 并 deactivate —
    # ConversationSession.project_id 是 ondelete=SET NULL，删项目后 session 会悬空，
    # 若 current_state 还停在 keyword_confirmation / searching 等非终态，
    # 新建项目的前端 ChatPanel 可能读到这些残留状态，锁死输入框。
    from sqlalchemy import update as _sql_update
    from app.models.conversation_session import ConversationSession
    await db.execute(
        _sql_update(ConversationSession)
        .where(ConversationSession.project_id == project_id)
        .values(current_state="idle", state_data=None, is_active=False)
    )

    await db.execute(delete(Project).where(Project.id == project_id))
    await db.commit()

    # 级联清理：文献 workspace + 知识图谱文件
    import shutil
    from pathlib import Path
    import os
    pid = str(project_id)
    ws_dir = Path(os.environ.get("PROJECT_WORKSPACE_DIR", "/app/data/projects")) / pid
    if ws_dir.exists():
        shutil.rmtree(ws_dir, ignore_errors=True)
    kg_file = Path(os.environ.get("KG_DATA_DIR", "/app/data/knowledge_graphs")) / f"{pid}.json"
    if kg_file.exists():
        kg_file.unlink(missing_ok=True)


async def _get_project_or_404(project_id: uuid.UUID, user_id, db: AsyncSession) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


# ── Staleness hint endpoints ───────────────────────────────────────────────
# 调用语义：前端进入项目视图时 POST /stale-check（idempotent + 含副作用：可
# 能注入一条 stale_hint 富消息）。逻辑都收敛到 services/staleness.py，端点
# 只做鉴权 + 转发。


@router.post("/{project_id}/stale-check")
async def stale_check(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, current_user.id, db)

    from app.services.staleness import check_and_inject_stale_hint
    status = await check_and_inject_stale_hint(project_id, db)
    return {
        "is_stale": status.is_stale,
        "days_ago": status.days_ago,
        "threshold_days": status.threshold_days,
        "suppressed_until": (
            status.suppressed_until.isoformat()
            if status.suppressed_until else None
        ),
        "just_injected": status.just_injected,
    }


@router.post("/{project_id}/stale-dismiss")
async def stale_dismiss(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, current_user.id, db)

    from app.services.staleness import dismiss_stale_hint
    status = await dismiss_stale_hint(project_id, db)
    return {
        "ok": True,
        "suppressed_until": (
            status.suppressed_until.isoformat()
            if status.suppressed_until else None
        ),
    }
