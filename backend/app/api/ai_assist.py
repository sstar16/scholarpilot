"""
AI Assist API — LLM-powered helpers for the frontend.

1. Suggest search config from project description
2. Natural language search refinement
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from app.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/ai", tags=["ai-assist"])


class SuggestConfigRequest(BaseModel):
    description: str
    domains: Optional[List[str]] = None


class RefineSearchRequest(BaseModel):
    project_id: str
    instruction: str  # e.g. "focus more on recent papers" or "exclude patents"


@router.post("/suggest-config")
async def suggest_config(
    req: SuggestConfigRequest,
    current_user: User = Depends(get_current_user),
):
    """
    AI-assisted project creation: suggest search configuration from description.
    Suggests domains, data sources, round configuration, and scoring weights.
    """
    from app.config import settings
    from app.services.core.llm_providers import LLMProviderManager
    from app.services.core.llm_config_store import load_llm_config
    import json
    import re

    llm = LLMProviderManager(default_ollama_host=settings.ollama_host)
    await load_llm_config(llm, settings.redis_url)

    prompt = (
        "You are a research search configuration advisor. "
        "Given a research project description, suggest optimal search configuration.\n\n"
        f"Description: {req.description[:500]}\n"
        f"User-specified domains: {req.domains or 'not specified'}\n\n"
        "Return a JSON object with:\n"
        '- "domains": array of 1-3 domain tags (e.g. ["biology", "chemistry"])\n'
        '- "suggested_rounds": number of search rounds (3-10)\n'
        '- "year_strategy": "progressive" | "last5" | "last10" | "all"\n'
        '- "language_scope": "chinese_first" | "international" | "global"\n'
        '- "enable_patents": true/false\n'
        '- "scoring_weights": {"keyword": 0.6, "citation": 0.25, "recency": 0.15}\n'
        '- "rationale": brief explanation in Chinese\n\n'
        "Return ONLY the JSON object."
    )

    try:
        result = await llm.generate(prompt, temperature=0.2)
        if result:
            match = re.search(r'\{[\s\S]*\}', result)
            if match:
                config = json.loads(match.group())
                return {"status": "ok", "suggestion": config}
    except Exception as e:
        return {"status": "fallback", "error": str(e), "suggestion": _default_suggestion(req)}

    return {"status": "fallback", "suggestion": _default_suggestion(req)}


@router.post("/refine-search")
async def refine_search(
    req: RefineSearchRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Natural language search refinement: parse user instruction into config changes.
    e.g. "focus more on recent papers" → adjust recency weight, narrow year range.
    """
    from app.config import settings
    from app.services.core.llm_providers import LLMProviderManager
    from app.services.core.llm_config_store import load_llm_config
    import json
    import re

    llm = LLMProviderManager(default_ollama_host=settings.ollama_host)
    await load_llm_config(llm, settings.redis_url)

    prompt = (
        "You are parsing natural language search refinement instructions. "
        "Convert the user's instruction into search configuration changes.\n\n"
        f'User instruction: "{req.instruction}"\n\n'
        "Return a JSON object with ONLY the fields that should change:\n"
        '- "year_strategy": "last5" | "last10" | "last20" | "all"\n'
        '- "scoring_weights": {"keyword": N, "citation": N, "recency": N}\n'
        '- "enable_patents": true/false\n'
        '- "add_sources": ["source_id"]\n'
        '- "remove_sources": ["source_id"]\n'
        '- "add_keywords": ["keyword"]\n'
        '- "exclude_keywords": ["keyword"]\n'
        '- "explanation": brief explanation in Chinese\n\n'
        "Return ONLY the JSON object with changed fields."
    )

    try:
        result = await llm.generate(prompt, temperature=0.2)
        if result:
            match = re.search(r'\{[\s\S]*\}', result)
            if match:
                changes = json.loads(match.group())
                return {"status": "ok", "changes": changes}
    except Exception as e:
        return {"status": "error", "error": str(e)}

    return {"status": "error", "error": "Could not parse instruction"}


def _default_suggestion(req: SuggestConfigRequest) -> Dict[str, Any]:
    """Fallback suggestion when LLM is unavailable."""
    return {
        "domains": req.domains or ["general"],
        "suggested_rounds": 5,
        "year_strategy": "progressive",
        "language_scope": "international",
        "enable_patents": True,
        "scoring_weights": {"keyword": 0.6, "citation": 0.25, "recency": 0.15},
        "rationale": "LLM 不可用，使用默认配置",
    }
