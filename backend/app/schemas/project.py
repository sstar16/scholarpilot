from pydantic import BaseModel
from typing import Optional
import uuid
from datetime import datetime


class ProjectCreate(BaseModel):
    title: str
    description: str  # 研究方向的完整描述
    domain: str       # biology / chemistry / cs / economics / materials / ...


class ProjectOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    domain: str
    current_round: int
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
