from pydantic import BaseModel, field_validator
from typing import Optional, List, Dict, Any
import uuid
from datetime import datetime


# 默认搜索配置
DEFAULT_SEARCH_CONFIG = {
    "rounds": [
        {"years": 5,  "max_results": 10, "scope": "chinese_first"},
        {"years": 10, "max_results": 10, "scope": "chinese_first"},
        {"years": 20, "max_results": 20, "scope": "international"},
        {"years": None, "max_results": 200, "scope": "international"},
        {"years": None, "max_results": 200, "scope": "global"},
    ],
    "scoring_weights": {
        "keyword": 0.60,
        "citation": 0.25,
        "recency": 0.15,
    },
    "disabled_sources": [],
}


class ProjectCreate(BaseModel):
    title: str
    description: str
    domain: str = ""  # 向后兼容：单领域
    domains: List[str] = []  # 新：多领域
    search_config: Optional[Dict[str, Any]] = None
    max_rounds: int = 5

    @field_validator("domains", mode="before")
    @classmethod
    def ensure_domains(cls, v, info):
        return v or []

    def get_domains(self) -> List[str]:
        """获取领域列表，向后兼容单领域字段"""
        if self.domains:
            return self.domains
        if self.domain:
            return [self.domain]
        return []


class ProjectOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    domain: str
    domains: Optional[List[str]] = None
    search_config: Optional[Dict[str, Any]] = None
    current_round: int
    max_rounds: int = 5
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    search_config: Optional[Dict[str, Any]] = None
    max_rounds: Optional[int] = None
