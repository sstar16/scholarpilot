"""User document ownership API（spec docs/spec-pdf-ownership-sync.md）。

3 个 endpoints:
  GET    /api/users/me/documents?project_id=&format=  列当前用户在指定 project 拥有的全部文档
  POST   /api/projects/{pid}/documents/{did}/own      标记 owned（客户端 upload_local 场景）
  DELETE /api/projects/{pid}/documents/{did}/own      取消 owned

辅助函数 mark_owned() 给现有 endpoints（download-fulltext / GET /file / upload-fulltext）
直接调用，自动写 ownership 不需要客户端额外请求。
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.user_document import UserDocument

logger = logging.getLogger(__name__)

# 两个 router：一个挂 /api/users/me 下，一个挂 /api/projects 下
users_router = APIRouter(prefix="/api/users/me", tags=["user-documents"])
projects_router = APIRouter(prefix="/api/projects", tags=["user-documents"])


# ── Schemas ─────────────────────────────────────────────────────────────


SourceLiteral = Literal["downloaded", "uploaded_local", "uploaded_synced"]
FormatLiteral = Literal["pdf", "html"]


class OwnedDocumentOut(BaseModel):
    document_id: uuid.UUID
    project_id: uuid.UUID
    source: str
    format: str
    owned_at: datetime
    last_seen_at: datetime

    class Config:
        from_attributes = True


class OwnedDocumentList(BaseModel):
    items: list[OwnedDocumentOut]


class OwnRequest(BaseModel):
    source: SourceLiteral
    format: FormatLiteral = "pdf"


class OwnResponse(BaseModel):
    document_id: uuid.UUID
    project_id: uuid.UUID
    source: str
    format: str
    owned_at: datetime
    last_seen_at: datetime
    created: bool  # True = 新建，False = 更新已有 last_seen_at

    class Config:
        from_attributes = True


class UnownResponse(BaseModel):
    removed: bool


# ── Internal helper（给 classification.py 等现有 endpoint 直接调）────────


async def mark_owned(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    source: SourceLiteral,
    format: FormatLiteral = "pdf",
) -> UserDocument:
    """幂等：已有则更新 last_seen_at，无则创建。返回最新记录。

    失败不抛错给上游 — ownership 写入失败不应阻塞用户拿 PDF binary 的主流程。
    """
    try:
        stmt = select(UserDocument).where(
            UserDocument.user_id == user_id,
            UserDocument.document_id == document_id,
            UserDocument.project_id == project_id,
            UserDocument.format == format,
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        now = datetime.now(timezone.utc)
        if existing:
            existing.last_seen_at = now
            # 升级 source: uploaded_local → uploaded_synced 是允许的；不降级
            _SOURCE_PRIORITY = {"uploaded_local": 1, "downloaded": 2, "uploaded_synced": 3}
            if _SOURCE_PRIORITY.get(source, 0) >= _SOURCE_PRIORITY.get(existing.source, 0):
                existing.source = source
            await db.commit()
            await db.refresh(existing)
            return existing

        new = UserDocument(
            user_id=user_id,
            document_id=document_id,
            project_id=project_id,
            source=source,
            format=format,
            owned_at=now,
            last_seen_at=now,
        )
        db.add(new)
        await db.commit()
        await db.refresh(new)
        return new
    except Exception as e:
        logger.warning(f"mark_owned failed (user={user_id} doc={document_id}): {e}")
        await db.rollback()
        raise


async def mark_unowned(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    format: FormatLiteral = "pdf",
) -> bool:
    """删除 ownership 记录。幂等（不存在也返 True）。"""
    stmt = delete(UserDocument).where(
        UserDocument.user_id == user_id,
        UserDocument.document_id == document_id,
        UserDocument.project_id == project_id,
        UserDocument.format == format,
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount >= 0


# ── Endpoints ───────────────────────────────────────────────────────────


@users_router.get("/documents", response_model=OwnedDocumentList)
async def list_owned_documents(
    project_id: Optional[uuid.UUID] = Query(None, description="按项目过滤；不传 = 全部项目"),
    format: Optional[FormatLiteral] = Query(None, description="按格式过滤；不传 = 全部"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """列当前用户拥有的文档（驱动客户端登录后静默批量下载）。

    粒度 per-project：同一 doc 在多 project 各算一条 — 物理 fs 路径
    `projects/<pid>/pdfs/<did>.pdf` 也是 per-project 隔离的。
    """
    stmt = select(UserDocument).where(UserDocument.user_id == current_user.id)
    if project_id is not None:
        stmt = stmt.where(UserDocument.project_id == project_id)
    if format is not None:
        stmt = stmt.where(UserDocument.format == format)
    stmt = stmt.order_by(UserDocument.owned_at.desc())

    result = await db.execute(stmt)
    rows = result.scalars().all()
    return OwnedDocumentList(items=[OwnedDocumentOut.model_validate(r) for r in rows])


@projects_router.post(
    "/{project_id}/documents/{document_id}/own",
    response_model=OwnResponse,
)
async def own_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    req: OwnRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """标记当前用户在指定 project 拥有 doc 的某个 format（pdf / html）副本。

    幂等：已有则更新 last_seen_at + 升级 source（uploaded_local → uploaded_synced）。
    主要场景是客户端用户主动 upload_local 时通知 backend；download-fulltext / GET /file
    成功路径已在内部自动调用 mark_owned()，客户端不需要再调本 endpoint。
    """
    # 检查 ownership 是否已存在以决定 created flag
    stmt = select(UserDocument).where(
        UserDocument.user_id == current_user.id,
        UserDocument.document_id == document_id,
        UserDocument.project_id == project_id,
        UserDocument.format == req.format,
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    created = existing is None

    record = await mark_owned(
        db,
        user_id=current_user.id,
        project_id=project_id,
        document_id=document_id,
        source=req.source,
        format=req.format,
    )

    return OwnResponse(
        document_id=record.document_id,
        project_id=record.project_id,
        source=record.source,
        format=record.format,
        owned_at=record.owned_at,
        last_seen_at=record.last_seen_at,
        created=created,
    )


@projects_router.delete(
    "/{project_id}/documents/{document_id}/own",
    response_model=UnownResponse,
)
async def unown_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    format: FormatLiteral = Query("pdf", description="哪个格式"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """取消 ownership（用户主动删除本地副本时调用）。幂等。"""
    removed = await mark_unowned(
        db,
        user_id=current_user.id,
        project_id=project_id,
        document_id=document_id,
        format=format,
    )
    return UnownResponse(removed=removed)
