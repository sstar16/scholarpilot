"""
Tests for MemoryAgent v4 (LLM-free file map) + v3 fallback.

Cases:
  A - new v4 schema (files list) → _files_from_llm_response path
  B - old v3 schema (flat fields) → _files_from_parsed fallback
  C - v4 schema but files empty   → fallback to _files_from_parsed
  D - malformed JSON               → _parse_memory_response returns None
"""
from __future__ import annotations

import json
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub heavy imports so the module can be collected without real DB/Redis deps
# ---------------------------------------------------------------------------
for mod_name in [
    "app.config",
    "app.models.user_profile",
    "app.models.document",
    "app.models.document_classification",
    "sqlalchemy",
    "sqlalchemy.orm",
    "redis",
    "redis.asyncio",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

# Stub prompt loader so build_memory_update_prompt doesn't hit disk
_prompt_loader_stub = types.ModuleType("app.services.prompt_loader")


class _FakePromptFile:
    def render(self, **kwargs):
        return "stub prompt"


_prompt_loader_stub.load_prompt = MagicMock(return_value=_FakePromptFile())
sys.modules["app.services.prompt_loader"] = _prompt_loader_stub

# Stub harness.prompts.memory_update (imports prompt_loader internally)
_pmu_stub = types.ModuleType("app.harness.prompts.memory_update")
_pmu_stub.build_memory_update_prompt = MagicMock(return_value="stub prompt")
sys.modules["app.harness.prompts.memory_update"] = _pmu_stub

from app.harness.agents.memory_agent import (  # noqa: E402
    MemoryAgent,
    MemoryUpdateResult,
    _files_from_llm_response,
    _files_from_parsed,
    _parse_memory_response,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

V4_RESPONSE = json.dumps({
    "version_summary": "Added focus on transformer inference",
    "research_focus": "Transformer inference optimization for edge devices",
    "files": [
        {
            "filename": "transformer_inference_focus.md",
            "type": "identity",
            "name": "核心研究方向",
            "description": "专注 transformer 推理优化",
            "body": "## 核心研究方向\n\ntransformer 推理在边缘设备上的优化。",
        },
        {
            "filename": "preferred_quantization_methods.md",
            "type": "preference",
            "name": "偏好量化方法",
            "description": "INT8/FP16 量化偏好",
            "body": "## 偏好量化方法\n\n- INT8\n- FP16\n- GPTQ",
        },
    ],
})

V3_RESPONSE = json.dumps({
    "research_focus": "Battery materials for EVs",
    "preferred_topics": ["solid-state electrolyte", "lithium anode"],
    "excluded_topics": ["lead-acid battery"],
    "methodology_preferences": ["DFT simulation"],
    "key_authors": ["Y. Cui"],
    "source_preferences": ["Nature Energy"],
    "notes": "Interested in Chinese institutions",
})

V4_EMPTY_FILES = json.dumps({
    "version_summary": "no valid files",
    "research_focus": "Some focus",
    "files": [],
})

MALFORMED = "this is not json at all {{{}"


# ---------------------------------------------------------------------------
# Unit tests: _parse_memory_response
# ---------------------------------------------------------------------------

def test_parse_v4_detects_files_key():
    parsed = _parse_memory_response(V4_RESPONSE)
    assert parsed is not None
    assert "files" in parsed
    assert isinstance(parsed["files"], list)
    assert len(parsed["files"]) == 2


def test_parse_v3_detects_flat_fields():
    parsed = _parse_memory_response(V3_RESPONSE)
    assert parsed is not None
    assert "research_focus" in parsed
    assert "files" not in parsed


def test_parse_malformed_returns_none():
    assert _parse_memory_response(MALFORMED) is None


def test_parse_v4_empty_files_still_parses():
    parsed = _parse_memory_response(V4_EMPTY_FILES)
    assert parsed is not None
    assert parsed["files"] == []


# ---------------------------------------------------------------------------
# Unit tests: _files_from_llm_response
# ---------------------------------------------------------------------------

def test_files_from_llm_response_returns_correct_specs():
    parsed = _parse_memory_response(V4_RESPONSE)
    files = _files_from_llm_response(parsed)
    assert len(files) == 2
    filenames = {f["filename"] for f in files}
    assert "transformer_inference_focus.md" in filenames
    assert "preferred_quantization_methods.md" in filenames
    # types preserved
    types_found = {f["type"] for f in files}
    assert "identity" in types_found
    assert "preference" in types_found


def test_files_from_llm_response_rejects_invalid_filename():
    bad = {
        "research_focus": "x",
        "files": [
            {"filename": "../../etc/passwd", "type": "note", "name": "bad", "description": "x", "body": "y"},
            {"filename": "valid_file.md", "type": "note", "name": "ok", "description": "desc", "body": "content"},
        ],
    }
    files = _files_from_llm_response(bad)
    assert len(files) == 1
    assert files[0]["filename"] == "valid_file.md"


def test_files_from_llm_response_deduplicates_filenames():
    dup = {
        "research_focus": "x",
        "files": [
            {"filename": "focus.md", "type": "identity", "name": "A", "description": "d", "body": "b1"},
            {"filename": "focus.md", "type": "identity", "name": "B", "description": "d", "body": "b2"},
        ],
    }
    files = _files_from_llm_response(dup)
    assert len(files) == 1


# ---------------------------------------------------------------------------
# Integration: MemoryAgent.update_memory
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_llm():
    llm = MagicMock()
    llm.generate = AsyncMock()
    return llm


@pytest.mark.asyncio
async def test_case_a_v4_schema_uses_llm_files(fake_llm):
    """Case A: v4 schema → files come directly from LLM output."""
    fake_llm.generate.return_value = V4_RESPONSE
    agent = MemoryAgent(llm_manager=fake_llm)
    result = await agent.update_memory(
        project_description="Edge AI research",
        current_memory="",
        memory_version=0,
        feedback_buckets={2: [{"title": "T1", "one_line_summary": "s", "source": "arXiv"}], 1: [], 0: [], -1: []},
    )
    assert isinstance(result, MemoryUpdateResult)
    assert result.version == 1
    assert len(result.files) == 2
    filenames = {f["filename"] for f in result.files}
    assert "transformer_inference_focus.md" in filenames
    assert "preferred_quantization_methods.md" in filenames


@pytest.mark.asyncio
async def test_case_b_v3_schema_uses_fixed_files(fake_llm):
    """Case B: v3 schema → fallback to fixed 7-category mapping."""
    fake_llm.generate.return_value = V3_RESPONSE
    agent = MemoryAgent(llm_manager=fake_llm)
    result = await agent.update_memory(
        project_description="Battery research",
        current_memory="",
        memory_version=2,
        feedback_buckets={2: [{"title": "T1", "one_line_summary": "s", "source": "Nature"}], 1: [], 0: [], -1: []},
    )
    assert isinstance(result, MemoryUpdateResult)
    assert result.version == 3
    # v3 path produces fixed filenames
    filenames = {f["filename"] for f in result.files}
    assert "research_focus.md" in filenames
    assert "preferred_topics.md" in filenames
    assert len(result.files) >= 2


@pytest.mark.asyncio
async def test_case_c_v4_empty_files_falls_back_to_v3(fake_llm):
    """Case C: v4 schema with empty files → fallback to _files_from_parsed."""
    # Inject research_focus into the empty-files response so v3 fallback works
    payload = json.dumps({
        "version_summary": "empty files",
        "research_focus": "Quantum computing",
        "preferred_topics": ["qubits", "error correction"],
        "files": [],
    })
    fake_llm.generate.return_value = payload
    agent = MemoryAgent(llm_manager=fake_llm)
    result = await agent.update_memory(
        project_description="Quantum research",
        current_memory="",
        memory_version=1,
        feedback_buckets={2: [{"title": "T", "one_line_summary": "s", "source": "arXiv"}], 1: [], 0: [], -1: []},
    )
    assert isinstance(result, MemoryUpdateResult)
    filenames = {f["filename"] for f in result.files}
    # v3 fallback should produce research_focus.md
    assert "research_focus.md" in filenames


@pytest.mark.asyncio
async def test_case_d_malformed_json_returns_none(fake_llm):
    """Case D: malformed JSON → update_memory returns None."""
    fake_llm.generate.return_value = MALFORMED
    agent = MemoryAgent(llm_manager=fake_llm)
    result = await agent.update_memory(
        project_description="Any research",
        current_memory="",
        memory_version=0,
        feedback_buckets={2: [{"title": "T", "one_line_summary": "s", "source": "x"}], 1: [], 0: [], -1: []},
    )
    assert result is None
