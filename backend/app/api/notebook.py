"""
Notebook API — 项目级笔记本（多 page）。

页面存活于项目生命周期，协作模式内外均可读写。
AI 通过 collaboration_question 决策 create_page / update_page / append_to_page；
用户通过 UI 可 CRUD 任意 page。
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, get_current_user_flexible
from fastapi.responses import PlainTextResponse
from app.models.project import Project
from app.models.research_note_page import ResearchNotePage
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/notebook", tags=["notebook"])


# ──────────── Schemas ────────────

class PageCreate(BaseModel):
    title: Optional[str] = None
    body_md: Optional[str] = None


class PageUpdate(BaseModel):
    title: Optional[str] = None
    body_md: Optional[str] = None


class PageReorder(BaseModel):
    sort_order: int


# ──────────── Helpers ────────────

async def _ensure_project_owner(
    project_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession,
) -> Project:
    res = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    p = res.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="项目不存在")
    return p


def page_to_dict(p: ResearchNotePage) -> dict:
    return {
        "id": str(p.id),
        "title": p.title,
        "body_md": p.body_md,
        "sort_order": p.sort_order,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "updated_by": p.updated_by,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


async def _list_pages(db: AsyncSession, project_id: uuid.UUID) -> list[ResearchNotePage]:
    res = await db.execute(
        select(ResearchNotePage)
        .where(ResearchNotePage.project_id == project_id)
        .order_by(ResearchNotePage.sort_order, ResearchNotePage.created_at)
    )
    return list(res.scalars().all())


async def _next_sort_order(db: AsyncSession, project_id: uuid.UUID) -> int:
    r = await db.execute(
        select(func.max(ResearchNotePage.sort_order))
        .where(ResearchNotePage.project_id == project_id)
    )
    return (r.scalar() or 0) + 1


async def _migrate_legacy_note_if_needed(
    db: AsyncSession, proj: Project,
) -> Optional[ResearchNotePage]:
    """首次访问时，如果 pages 空但老的 research_note_md 非空，迁移进"首页"。"""
    legacy = (proj.research_note_md or "").strip()
    if not legacy:
        return None
    existing = await _list_pages(db, proj.id)
    if existing:
        return None
    page = ResearchNotePage(
        project_id=proj.id,
        title="首页",
        body_md=legacy,
        sort_order=0,
        updated_by="user",
    )
    db.add(page)
    await db.commit()
    await db.refresh(page)
    logger.info("[notebook] migrated legacy note to page for project=%s", str(proj.id)[:8])
    return page


# ──────────── Endpoints ────────────

@router.get("/pages")
async def list_pages(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    proj = await _ensure_project_owner(project_id, current_user.id, db)
    pages = await _list_pages(db, project_id)
    if not pages:
        migrated = await _migrate_legacy_note_if_needed(db, proj)
        if migrated:
            pages = [migrated]
    return {"pages": [page_to_dict(p) for p in pages]}


@router.post("/pages")
async def create_page(
    project_id: uuid.UUID,
    req: PageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_project_owner(project_id, current_user.id, db)
    sort_order = await _next_sort_order(db, project_id)
    page = ResearchNotePage(
        project_id=project_id,
        title=((req.title or "新页面").strip() or "新页面")[:200],
        body_md=(req.body_md or "")[:200_000],
        sort_order=sort_order,
        updated_by="user",
    )
    db.add(page)
    await db.commit()
    await db.refresh(page)
    return page_to_dict(page)


@router.get("/pages/{page_id}")
async def get_page(
    project_id: uuid.UUID,
    page_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_project_owner(project_id, current_user.id, db)
    r = await db.execute(
        select(ResearchNotePage).where(
            ResearchNotePage.id == page_id,
            ResearchNotePage.project_id == project_id,
        )
    )
    page = r.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    return page_to_dict(page)


@router.put("/pages/{page_id}")
async def update_page(
    project_id: uuid.UUID,
    page_id: uuid.UUID,
    req: PageUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_project_owner(project_id, current_user.id, db)
    r = await db.execute(
        select(ResearchNotePage).where(
            ResearchNotePage.id == page_id,
            ResearchNotePage.project_id == project_id,
        )
    )
    page = r.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    if req.title is not None:
        page.title = req.title.strip()[:200] or page.title
    if req.body_md is not None:
        page.body_md = req.body_md[:200_000]
    page.updated_at = datetime.now(timezone.utc)
    page.updated_by = "user"
    await db.commit()
    await db.refresh(page)
    return page_to_dict(page)


@router.delete("/pages/{page_id}")
async def delete_page(
    project_id: uuid.UUID,
    page_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_project_owner(project_id, current_user.id, db)
    r = await db.execute(
        select(ResearchNotePage).where(
            ResearchNotePage.id == page_id,
            ResearchNotePage.project_id == project_id,
        )
    )
    page = r.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    await db.delete(page)
    await db.commit()
    return {"ok": True, "deleted_id": str(page_id)}


@router.get("/export.md")
async def export_notebook_md(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user_flexible),
    db: AsyncSession = Depends(get_db),
):
    """
    导出项目笔记本为 Markdown（拼接所有 page，按 sort_order 排序）。
    支持 ?token=JWT 查询参数鉴权，方便直接下载链接使用。
    """
    proj = await _ensure_project_owner(project_id, current_user.id, db)

    pages = await _list_pages(db, project_id)
    # 生成 md 内容
    lines: list[str] = [
        f"# {proj.title or '研究项目笔记'}",
        "",
        f"<sub>导出于 {datetime.now(timezone.utc).isoformat()} · 共 {len(pages)} 页</sub>",
        "",
    ]
    if proj.description:
        lines.append("## 项目描述")
        lines.append(proj.description)
        lines.append("")
    lines.append("---")
    lines.append("")

    if not pages:
        lines.append("_（笔记本为空）_")
    else:
        for p in pages:
            title = (p.title or "未命名").strip()
            lines.append(f"## {title}")
            lines.append("")
            updated = p.updated_at.isoformat() if p.updated_at else ""
            updated_by = p.updated_by or "unknown"
            lines.append(f"<sub>最后更新: {updated} · by {updated_by}</sub>")
            lines.append("")
            body = (p.body_md or "").strip()
            if body:
                lines.append(body)
            else:
                lines.append("_（空白页）_")
            lines.append("")
            lines.append("---")
            lines.append("")

    md_text = "\n".join(lines)
    # 用 ASCII 安全的文件名，避免 header 里出中文时编码错
    safe_slug = (proj.title or "notebook").encode("ascii", "ignore").decode() or "notebook"
    safe_slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in safe_slug)[:50] or "notebook"
    filename = f"{safe_slug}-notebook.md"
    return PlainTextResponse(
        content=md_text,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/pages/{page_id}/reorder")
async def reorder_page(
    project_id: uuid.UUID,
    page_id: uuid.UUID,
    req: PageReorder,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_project_owner(project_id, current_user.id, db)
    r = await db.execute(
        select(ResearchNotePage).where(
            ResearchNotePage.id == page_id,
            ResearchNotePage.project_id == project_id,
        )
    )
    page = r.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")
    page.sort_order = max(0, int(req.sort_order))
    await db.commit()
    await db.refresh(page)
    return page_to_dict(page)
