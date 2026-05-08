"""FeatureGate — 3 大功能 × 3 场景 准入校验（单一真相源）。

blocked 时返回结构化 reason + suggested_action 用于富消息引导。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.project_scene import ProjectScene, resolve_scene


FEATURES = ("new_round", "collaboration", "schedule", "pdf_import")


ACCESS_MATRIX: dict[str, dict[str, bool]] = {
    "new_round":     {"fresh": True,  "empty": True,  "has_lib": True},
    "collaboration": {"fresh": False, "empty": False, "has_lib": True},
    "schedule":      {"fresh": False, "empty": True,  "has_lib": True},
    "pdf_import":    {"fresh": True,  "empty": True,  "has_lib": True},
}


# (feature, scene) -> (reason, action_trigger, action_label)
BLOCK_REASONS: dict[tuple[str, str], tuple[str, str, str]] = {
    ("collaboration", "fresh"): (
        "需要先完成一次检索建立文献库",
        "new_round", "开始新检索",
    ),
    ("collaboration", "empty"): (
        "文献库为空，先完成一轮检索",
        "new_round", "开始新检索",
    ),
    ("schedule", "fresh"): (
        "定时推送需要先有画像，请先完成首轮检索",
        "new_round", "开始新检索",
    ),
}


@dataclass
class FeatureGateResult:
    allowed: bool
    scene: str
    feature: str
    reason: Optional[str] = None
    suggested_action: Optional[dict] = None


async def check(
    feature: str, project_id: uuid.UUID, db: AsyncSession
) -> FeatureGateResult:
    if feature not in FEATURES:
        raise ValueError(f"unknown feature: {feature}")
    scene = await resolve_scene(project_id, db)
    allowed = ACCESS_MATRIX[feature][scene.value]
    if allowed:
        return FeatureGateResult(allowed=True, scene=scene.value, feature=feature)
    reason, trigger, label = BLOCK_REASONS[(feature, scene.value)]
    return FeatureGateResult(
        allowed=False,
        scene=scene.value,
        feature=feature,
        reason=reason,
        suggested_action={"trigger": trigger, "label": label},
    )


async def check_all(
    project_id: uuid.UUID, db: AsyncSession
) -> dict[str, FeatureGateResult]:
    """批量校验，前端 mount 时一次性拿到 4 个按钮状态。"""
    scene = await resolve_scene(project_id, db)
    out: dict[str, FeatureGateResult] = {}
    for feat in FEATURES:
        allowed = ACCESS_MATRIX[feat][scene.value]
        if allowed:
            out[feat] = FeatureGateResult(
                allowed=True, scene=scene.value, feature=feat
            )
        else:
            reason, trigger, label = BLOCK_REASONS[(feat, scene.value)]
            out[feat] = FeatureGateResult(
                allowed=False,
                scene=scene.value,
                feature=feat,
                reason=reason,
                suggested_action={"trigger": trigger, "label": label},
            )
    return out
