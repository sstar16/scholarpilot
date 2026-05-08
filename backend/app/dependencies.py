from typing import Optional
from datetime import datetime, timezone
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.database import get_db
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# Redis key 前缀：user:last_seen:{user_id} = ISO timestamp, TTL 300s
LAST_SEEN_TTL_SECONDS = 300
LAST_SEEN_KEY_PREFIX = "user:last_seen:"


async def _touch_last_seen(user_id) -> None:
    """非关键路径：刷新用户活跃时间戳。失败不影响鉴权。"""
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            await r.set(
                f"{LAST_SEEN_KEY_PREFIX}{user_id}",
                datetime.now(timezone.utc).isoformat(),
                ex=LAST_SEEN_TTL_SECONDS,
            )
        finally:
            await r.close()
    except Exception:
        pass


async def _user_from_token(token: str, db: AsyncSession) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exception
    await _touch_last_seen(user.id)
    return user


async def get_current_user_flexible(
    header_token: Optional[str] = Depends(oauth2_scheme),
    query_token: Optional[str] = Query(None, alias="token"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Auth dependency that accepts JWT from EITHER:
      - Authorization: Bearer <token> header (XHR/fetch via axios)
      - ?token=<jwt> query parameter (iframe / <a href> / direct browser navigation)
    Used for file streaming endpoints where iframe can't set headers.
    """
    token = header_token or query_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证 token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await _user_from_token(token, db)


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证 token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await _user_from_token(token, db)


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return current_user
