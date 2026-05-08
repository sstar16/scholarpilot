import pytest
import uuid
from unittest.mock import AsyncMock, patch
from app.services.feature_gate import (
    ACCESS_MATRIX, check, FeatureGateResult,
)
from app.services.project_scene import ProjectScene

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("feature,scene,expected_allowed", [
    ("new_round", ProjectScene.FRESH, True),
    ("new_round", ProjectScene.EMPTY_LIBRARY, True),
    ("new_round", ProjectScene.HAS_LIBRARY, True),
    ("collaboration", ProjectScene.FRESH, False),
    ("collaboration", ProjectScene.EMPTY_LIBRARY, False),
    ("collaboration", ProjectScene.HAS_LIBRARY, True),
    ("schedule", ProjectScene.FRESH, False),
    ("schedule", ProjectScene.EMPTY_LIBRARY, True),
    ("schedule", ProjectScene.HAS_LIBRARY, True),
    ("pdf_import", ProjectScene.FRESH, True),
    ("pdf_import", ProjectScene.EMPTY_LIBRARY, True),
    ("pdf_import", ProjectScene.HAS_LIBRARY, True),
])
async def test_access_matrix_covers_all_cases(feature, scene, expected_allowed):
    project_id = uuid.uuid4()
    with patch(
        "app.services.feature_gate.resolve_scene",
        new=AsyncMock(return_value=scene),
    ):
        result = await check(feature, project_id, db=None)
    assert result.allowed == expected_allowed
    if not expected_allowed:
        assert result.reason, "blocked result must have a reason"
        assert result.suggested_action, "blocked result must have a suggested_action"


async def test_blocked_returns_structured_suggestion():
    project_id = uuid.uuid4()
    with patch(
        "app.services.feature_gate.resolve_scene",
        new=AsyncMock(return_value=ProjectScene.FRESH),
    ):
        result = await check("collaboration", project_id, db=None)
    assert result.allowed is False
    assert "检索" in result.reason
    assert result.suggested_action["trigger"] == "new_round"
    assert "检索" in result.suggested_action["label"]


async def test_check_all_returns_all_four_features():
    from app.services.feature_gate import check_all
    project_id = uuid.uuid4()
    with patch(
        "app.services.feature_gate.resolve_scene",
        new=AsyncMock(return_value=ProjectScene.HAS_LIBRARY),
    ):
        results = await check_all(project_id, db=None)
    assert set(results.keys()) == {"new_round", "collaboration", "schedule", "pdf_import"}
    for feat in results:
        assert results[feat].allowed is True


async def test_unknown_feature_raises():
    project_id = uuid.uuid4()
    with pytest.raises(ValueError):
        await check("bogus_feature", project_id, db=None)
