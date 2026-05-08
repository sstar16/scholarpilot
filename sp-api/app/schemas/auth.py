from pydantic import BaseModel, EmailStr
from typing import Optional
import uuid


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str
    password: str
    # 2026-05-08: 客户端注册去掉邀请码门槛 → invitation_code 改为可选；
    # 仅当 X-Client-Type ≠ desktop（即 web）时 register API 会强制要求。
    invitation_code: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # access_token TTL，单位秒


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    is_active: bool
    is_admin: bool = False

    class Config:
        from_attributes = True
