from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import jwt
from passlib.context import CryptContext

from app.database import get_db
from app.config import settings
from app.models.user import User
from app.models.invitation_code import InvitationCode
from app.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserOut,
)
from app.services.auth_tokens import (
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
    verify_refresh_token,
)
from app.dependencies import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode(
        {"sub": user_id, "exp": expire},
        settings.secret_key,
        algorithm=settings.algorithm,
    )


def _client_info(request: Request) -> tuple[str, str | None]:
    """读 X-Client-Type / X-Client-Version 头（M1.T9 middleware 也会写到 request.state，
    这里直接读 header 是冗余但 robust——middleware 不在时也能用）。"""
    client_type = request.headers.get("X-Client-Type", "web")
    client_version = request.headers.get("X-Client-Version")
    return client_type, client_version


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    req: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    code_str = req.invitation_code.strip().lower()
    if not code_str:
        raise HTTPException(status_code=400, detail="邀请码不能为空")

    inv_result = await db.execute(select(InvitationCode).where(InvitationCode.code == code_str))
    inv = inv_result.scalar_one_or_none()
    if inv is None:
        raise HTTPException(status_code=400, detail="邀请码无效")
    if inv.is_used:
        raise HTTPException(status_code=400, detail="邀请码已被使用")
    if inv.is_expired:
        raise HTTPException(status_code=400, detail="邀请码已过期")

    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="邮箱已注册")

    user = User(
        email=req.email,
        name=req.name,
        hashed_pw=pwd_context.hash(req.password),
    )
    db.add(user)
    await db.flush()  # 拿到 user.id 但不 commit，后面一起

    inv.used_at = datetime.now(timezone.utc)
    inv.used_by = user.id

    await db.commit()
    await db.refresh(user)

    access_token = create_access_token(str(user.id))
    client_type, client_version = _client_info(request)
    refresh_plain, _ = await issue_refresh_token(
        db,
        user_id=user.id,
        client_type=client_type,
        client_version=client_version,
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_plain,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    req: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    if not user or not pwd_context.verify(req.password, user.hashed_pw) or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )

    access_token = create_access_token(str(user.id))
    client_type, client_version = _client_info(request)
    refresh_plain, _ = await issue_refresh_token(
        db,
        user_id=user.id,
        client_type=client_type,
        client_version=client_version,
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_plain,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    req: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """用 refresh token 换新 access + 新 refresh（旧 refresh 立即作废）。"""
    record = await verify_refresh_token(db, req.refresh_token)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="refresh token 无效或已过期",
        )

    new_plain, _ = await rotate_refresh_token(db, record)
    access_token = create_access_token(str(record.user_id))
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_plain,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/logout", status_code=204)
async def logout(
    req: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """撤销 refresh token；要 access token 防 DoS（撤别人的 refresh）。
    幂等：refresh 不存在或不属于当前用户都返回 204，不报错。"""
    record = await verify_refresh_token(db, req.refresh_token)
    if record is not None and record.user_id == current_user.id:
        await revoke_refresh_token(db, record.id)
    return None
